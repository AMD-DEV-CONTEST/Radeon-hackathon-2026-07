"""
Redis Stream 事件总线
====================
封装 Redis Stream 的生产/消费/ACK/死信/监控逻辑，
替代纯 Pub/Sub 的事件推送通道，实现可靠投递。

核心特性：
  a1: XREADGROUP + BLOCK 消费
  a2: MAXLEN ~ 防止内存暴涨
  a3: 业务成功后 XACK
  a4: XPENDING 监控
  a5: 消息幂等（基于 seq 去重）
  a6: XAUTOCLAIM 消息认领超时
  a7: 死信队列（多次失败 → deadletter stream）
"""

import json
import os
import time
import uuid
from typing import Optional

import redis as sync_redis
import redis.asyncio as aioredis
from loguru import logger

# ── 配置 ──────────────────────────────────────────────
REDIS_URL = os.environ.get("AIQUANT_REDIS_URL", "redis://127.0.0.1:6379/0")

STREAM_KEY_PREFIX = "aiquant:task:stream:"
DEADLETTER_KEY_PREFIX = "aiquant:task:deadletter:"
LAST_SEQ_KEY_PREFIX = "aiquant:task:last_seq:"
CONSUMER_GROUP = "sse_group"

# a2: MAXLEN 防内存暴涨（近似修剪，~ 表示不精确修剪性能更好）
STREAM_MAXLEN = 10000
# a6: 消息认领超时（ms），超过此 idle 时间可被其他消费者认领
CLAIM_MIN_IDLE_MS = 120_000  # 120 秒
# a7: 最大重试次数，超过后进入死信队列
MAX_DELIVERY_COUNT = 3
# 死信队列 MAXLEN
DEADLETTER_MAXLEN = 5000


def _stream_key(task_id: str) -> str:
    return f"{STREAM_KEY_PREFIX}{task_id}"


def _deadletter_key(task_id: str) -> str:
    return f"{DEADLETTER_KEY_PREFIX}{task_id}"


def _last_seq_key(task_id: str, consumer: str) -> str:
    return f"{LAST_SEQ_KEY_PREFIX}{task_id}:{consumer}"


# ── 同步客户端（Worker 侧使用） ────────────────────────

def _get_sync_redis() -> sync_redis.Redis:
    return sync_redis.Redis.from_url(REDIS_URL, decode_responses=True)


def ensure_stream_group(r: sync_redis.Redis, task_id: str):
    """确保消费组存在（幂等创建）"""
    stream_key = _stream_key(task_id)
    try:
        r.xgroup_create(stream_key, CONSUMER_GROUP, id="0", mkstream=True)
    except sync_redis.ResponseError as e:
        if "BUSYGROUP" not in str(e):
            raise


def stream_publish(task_id: str, event: dict) -> str:
    """a2: 发布事件到 Stream（带 MAXLEN 修剪）。
    
    返回 Stream entry ID。
    同时保留 Pub/Sub 发布以兼容旧消费者。
    """
    r = _get_sync_redis()
    stream_key = _stream_key(task_id)
    payload = json.dumps(event, ensure_ascii=False, default=str)

    # a2: XADD with MAXLEN ~（近似修剪，避免内存暴涨）
    entry_id = r.xadd(stream_key, {"data": payload}, maxlen=STREAM_MAXLEN, approximate=True)

    # 确保消费组存在
    ensure_stream_group(r, task_id)

    # 兼容：同时发布到 Pub/Sub（过渡期保留）
    channel = f"aiquant:task:events:{task_id}"
    r.publish(channel, payload)

    return entry_id


# ── 异步客户端（API 侧使用） ──────────────────────────

async def get_async_redis() -> aioredis.Redis:
    return aioredis.from_url(REDIS_URL, decode_responses=True)


async def ensure_stream_group_async(r: aioredis.Redis, task_id: str):
    """异步确保消费组存在"""
    stream_key = _stream_key(task_id)
    try:
        await r.xgroup_create(stream_key, CONSUMER_GROUP, id="0", mkstream=True)
    except aioredis.ResponseError as e:
        if "BUSYGROUP" not in str(e):
            raise


async def stream_read_block(
    r: aioredis.Redis,
    task_id: str,
    consumer: str,
    count: int = 10,
    block_ms: int = 2000,
) -> list[dict]:
    """a1: XREADGROUP + BLOCK 消费消息。
    
    返回 [{"id": entry_id, "data": event_dict}, ...] 列表。
    """
    stream_key = _stream_key(task_id)
    await ensure_stream_group_async(r, task_id)

    # XREADGROUP GROUP {group} {consumer} COUNT {count} BLOCK {block_ms} STREAMS {key} >
    resp = await r.xreadgroup(
        groupname=CONSUMER_GROUP,
        consumername=consumer,
        streams={stream_key: ">"},
        count=count,
        block=block_ms,
    )

    results = []
    if resp:
        for _stream_name, messages in resp:
            for msg_id, fields in messages:
                raw = fields.get("data", "")
                try:
                    event = json.loads(raw)
                except json.JSONDecodeError:
                    event = {"type": "raw", "content": raw}
                results.append({"id": msg_id, "data": event})
    return results


async def stream_ack(r: aioredis.Redis, task_id: str, entry_id: str):
    """a3: 业务处理成功后执行 XACK"""
    stream_key = _stream_key(task_id)
    await r.xack(stream_key, CONSUMER_GROUP, entry_id)


async def is_duplicate(
    r: aioredis.Redis,
    task_id: str,
    consumer: str,
    seq: int,
) -> bool:
    """a5: 消息幂等检查 — 基于 seq 去重。
    
    如果 seq <= last_processed_seq 则为重复消息。
    """
    if seq is None or seq <= 0:
        return False
    key = _last_seq_key(task_id, consumer)
    last = await r.get(key)
    if last is None:
        await r.set(key, str(seq), ex=86400)
        return False
    last_seq = int(last)
    if seq <= last_seq:
        return True
    await r.set(key, str(seq), ex=86400)
    return False


async def get_pending_info(r: aioredis.Redis, task_id: str) -> dict:
    """a4: XPENDING 监控 — 返回 pending 消息统计"""
    stream_key = _stream_key(task_id)
    try:
        info = await r.xpending(stream_key, CONSUMER_GROUP)
        # info: {"pending": count, "min": id, "max": id, "consumers": [...]}
        return {
            "pending_count": info.get("pending", 0) if isinstance(info, dict) else 0,
            "min_id": info.get("min", None) if isinstance(info, dict) else None,
            "max_id": info.get("max", None) if isinstance(info, dict) else None,
            "consumers": info.get("consumers", []) if isinstance(info, dict) else [],
        }
    except Exception as e:
        logger.debug(f"[Stream] XPENDING 查询失败: {e}")
        return {"pending_count": 0, "error": str(e)}


async def get_pending_details(r: aioredis.Redis, task_id: str, count: int = 20) -> list[dict]:
    """a4: XPENDING 详情 — 返回每条 pending 消息的详情"""
    stream_key = _stream_key(task_id)
    try:
        details = await r.xpending_range(
            stream_key, CONSUMER_GROUP, min="-", max="+", count=count
        )
        # 每条: {"message_id": id, "consumer": name, "time_since_delivered": ms, "times_delivered": n}
        return [
            {
                "message_id": d.get("message_id", str(d)),
                "consumer": d.get("consumer", ""),
                "idle_ms": d.get("time_since_delivered", 0),
                "delivery_count": d.get("times_delivered", 1),
            }
            for d in details
        ]
    except Exception:
        return []


async def auto_claim_stale(
    r: aioredis.Redis,
    task_id: str,
    consumer: str,
    min_idle_ms: int = CLAIM_MIN_IDLE_MS,
    count: int = 10,
) -> list[str]:
    """a6: XAUTOCLAIM — 认领超时消息，防止消费者断线后消息永久留在 pending。
    
    返回被认领的 entry ID 列表。
    """
    stream_key = _stream_key(task_id)
    try:
        # XAUTOCLAIM key group consumer min_idle_time start [COUNT count]
        result = await r.xautoclaim(
            stream_key, CONSUMER_GROUP, consumer,
            min_idle_time=min_idle_ms, start_id="0", count=count,
        )
        # result: (next_start_id, [(entry_id, fields), ...], [deleted_ids])
        if isinstance(result, tuple) and len(result) >= 2:
            claimed = result[1]
            return [entry_id for entry_id, _ in claimed]
        return []
    except Exception as e:
        logger.debug(f"[Stream] XAUTOCLAIM 失败: {e}")
        return []


async def check_and_move_deadletter(
    r: aioredis.Redis,
    task_id: str,
    entry_id: str,
    delivery_count: int,
    event_data: dict,
) -> bool:
    """a7: 死信队列 — 超过 MAX_DELIVERY_COUNT 的消息转移到死信 Stream。
    
    返回 True 表示已转入死信。
    """
    if delivery_count < MAX_DELIVERY_COUNT:
        return False

    dl_key = _deadletter_key(task_id)
    deadletter_entry = {
        **{k: str(v) if not isinstance(v, str) else v for k, v in event_data.items()},
        "original_entry_id": entry_id,
        "dead_at": str(time.time()),
        "delivery_count": str(delivery_count),
    }
    # redis stream field values must be str or bytes
    try:
        await r.xadd(dl_key, deadletter_entry, maxlen=DEADLETTER_MAXLEN, approximate=True)
        # 从原 Stream 删除（已进入死信，不再保留）
        await r.xdel(_stream_key(task_id), entry_id)
        # ACK 掉原消息（从 pending 移除）
        await r.xack(_stream_key(task_id), CONSUMER_GROUP, entry_id)
        logger.warning(
            f"[Stream] 消息 {entry_id} (task={task_id}) 重试 {delivery_count} 次后转入死信队列"
        )
        return True
    except Exception as e:
        logger.error(f"[Stream] 死信转移失败: {e}")
        return False


async def get_deadletter_count(r: aioredis.Redis, task_id: str) -> int:
    """a7: 获取死信队列消息数"""
    dl_key = _deadletter_key(task_id)
    try:
        info = await r.xinfo_stream(dl_key)
        return info.get("length", 0) if isinstance(info, dict) else 0
    except Exception:
        return 0


def gen_consumer_id() -> str:
    """生成唯一消费者 ID"""
    return f"sse-{uuid.uuid4().hex[:8]}"
