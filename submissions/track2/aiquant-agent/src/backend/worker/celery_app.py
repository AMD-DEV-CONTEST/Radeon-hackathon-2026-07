"""
Celery 应用配置
===============
- Broker: Redis（支持生产级消息持久化）
- Backend: Redis（存储任务结果）
- 任务序列化: JSON
- 结果过期: 24 小时
- Worker 初始化: 自动配置 RD-Agent LLM 设置（继承主应用的 .env）
"""

import os
import sys
from pathlib import Path

# 确保项目根目录在 path 中（Worker 进程启动时会在此初始化）
_project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_project_root))

from celery import Celery
from celery.signals import worker_init, task_revoked, worker_shutting_down
from kombu import Queue
from loguru import logger

# 统一日志配置：终端彩色 + JSON 文件轮转 + 纯文本文件轮转
from backend.shared.log_config import setup_logging
setup_logging(log_level=os.environ.get("AIQUANT_LOG_LEVEL", "INFO"))

# ── Worker 日志可读性优化 ──────────────────────────────
# Celery 默认日志包含大量 heartbeat / mingle / pool 噪音，
# 将 celery 内部 logger 级别提升，保留 WARNING+ 级别的事件
import logging as _logging
# Celery 底层依赖的日志模块
for _log_name in [
    "celery", "celery.worker", "celery.app", "celery.bootsteps",
    "kombu", "kombu.mixins", "kombu.transport.redis",
    "redis", "urllib3", "httpx",
]:
    _logging.getLogger(_log_name).setLevel(_logging.WARNING)

# 保留自定义 task 日志的 INFO 级别
_logging.getLogger("celery.app.trace").setLevel(_logging.INFO)

# 添加自定义日志过滤：仅在日志消息包含特定前缀时显示
class CeleryLogFilter(_logging.Filter):
    def filter(self, record):
        msg = record.getMessage()
        # 保留 Worker 自定义日志
        if msg.startswith(("[Worker", "✅", "❌", "📊", "ℹ️", "收到任务", "任务结果")):
            return True
        # 保留错误和警告
        if record.levelno >= _logging.WARNING:
            return True
        # 保留关键事件
        if any(k in msg for k in ["Connected to", "ready.", "Task", "Succeeded", "Failed"]):
            return True
        return False

_logging.getLogger("celery.worker.strategy").addFilter(CeleryLogFilter())
_logging.getLogger("celery.app.trace").addFilter(CeleryLogFilter())

# ── Redis 连接配置
REDIS_URL = os.environ.get("AIQUANT_REDIS_URL", "redis://127.0.0.1:6379/0")

app = Celery(
    "aiquant_worker",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=["backend.worker.tasks"],
)

# 序列化配置
app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Shanghai",
    enable_utc=True,
    # a3: 业务成功后才 ACK，失败不 ACK 留给重试
    task_acks_late=True,
    # a6: Worker 丢失时拒绝任务（归还队列），防止并发重复执行
    task_reject_on_worker_lost=True,
    task_track_started=True,
    result_expires=86400,
    # 一次只取一个任务，防止预取导致消息堆积
    worker_prefetch_multiplier=1,
    # 每 10 个任务重启子进程，防止内存泄漏
    worker_max_tasks_per_child=10,
    broker_transport_options={
        # a6: 回测长任务的消息认领超时（2 小时），
        # 超过此时间未 ACK 的消息会被重新投递给其他 Worker
        "visibility_timeout": 7200,
    },
    # a7: 重试配置 — 失败后最多重试 3 次，超过则进入死信（Celery 层面）
    task_default_retry_delay=30,
    task_default_max_retries=3,
    task_queues=(
        Queue("default", routing_key="default"),
        Queue("factor_evolution", routing_key="factor_evolution"),
    ),
    task_routes={
        "backend.worker.tasks.run_factor_evolution": {"queue": "factor_evolution"},
    },
)


@worker_init.connect
def configure_rdagent_llm(**kwargs):
    """
    Worker 启动信号：初始化 RD-Agent LLM 配置。
    
    必须在 Worker 启动时做，因为 Celery Worker 是独立进程，
    不会继承 FastAPI 主进程通过 load_dotenv() 设置的 RD-Agent config。
    """
    try:
        # ── 加载 .env（Worker 不经过 FastAPI 的 load_dotenv） ──
        env_file = _project_root / ".env"
        if env_file.exists():
            from dotenv import load_dotenv
            load_dotenv(env_file, override=True)
            logger.info("[Worker Init] .env 已加载")
        
        _deepseek_key = os.environ.get("DEEPSEEK_API_KEY", "")
        _openai_key = os.environ.get("OPENAI_API_KEY", "")
        
        # ── 设置环境变量 ──
        if _deepseek_key:
            os.environ.setdefault("DEEPSEEK_API_KEY", _deepseek_key)
            logger.info(f"[Worker Init] DEEPSEEK_API_KEY configured ({_deepseek_key[:10]}...)")
        if _openai_key and not _deepseek_key:
            os.environ.setdefault("OPENAI_API_KEY", _openai_key)
        
        # ── 覆盖 RD-Agent LLM 配置 ──
        if _deepseek_key:
            try:
                from rdagent.oai.llm_conf import LLM_SETTINGS
                LLM_SETTINGS.chat_model = "deepseek/deepseek-v4-flash"
                LLM_SETTINGS.openai_api_key = _deepseek_key
                logger.info("[Worker Init] RD-Agent LLM: chat_model → deepseek/deepseek-v4-flash")
            except Exception as e:
                logger.warning(f"[Worker Init] RD-Agent LLM 配置覆盖失败: {e}")
            
            # ── 配置 embedding ──
            _proxy_key = os.environ.get("LITELLM_PROXY_API_KEY", "") or os.environ.get("SILICONFLOW_API_KEY", "")
            _proxy_base = os.environ.get("LITELLM_PROXY_API_BASE", "") or os.environ.get("SILICONFLOW_API_BASE", "https://api.siliconflow.cn/v1")
            if _proxy_key:
                os.environ["LITELLM_PROXY_API_KEY"] = _proxy_key
                os.environ["LITELLM_PROXY_API_BASE"] = _proxy_base
                try:
                    from rdagent.oai.backend.litellm import LITELLM_SETTINGS as _LITELLM_SETTINGS
                    _LITELLM_SETTINGS.embedding_model = "litellm_proxy/BAAI/bge-m3"
                    logger.info(f"[Worker Init] RD-Agent embedding: litellm_proxy/BAAI/bge-m3")
                except Exception as e:
                    logger.warning(f"[Worker Init] embedding 配置失败: {e}")
        else:
            logger.warning("[Worker Init] DEEPSEEK_API_KEY 未配置，使用默认 OpenAI gpt-4-turbo")
            
    except Exception as e:
        logger.warning(f"[Worker Init] 配置初始化异常: {e}（将使用 RD-Agent 默认配置）")


# 事件推送的 Redis 频道前缀
EVENTS_CHANNEL_PREFIX = "aiquant:task:events:"


def get_events_channel(task_id: str) -> str:
    """获取任务事件推送的 Redis Pub/Sub 频道名"""
    return f"{EVENTS_CHANNEL_PREFIX}{task_id}"


# ── A4: 优雅关机 & 任务取消信号处理 ─────────────────────────────

@task_revoked.connect
def on_task_revoked(sender, request=None, terminated=False, signum=None, exp=None, **kwargs):
    """
    任务被 revoke（取消/终止）时触发：保存中间状态到 Redis，
    避免跑到一半的任务直接丢失。
    """
    try:
        task_id = getattr(request, "id", None) if request else kwargs.get("task_id")
        if not task_id:
            return
        import json, time
        import redis as _redis
        r = _redis.from_url(REDIS_URL, decode_responses=True)
        raw = r.get(f"aiquant:task:progress:{task_id}")
        if raw:
            data = json.loads(raw)
            data["status"] = "revoked"
            data["end_time"] = time.time()
            data["revoked_reason"] = f"signum={signum}, terminated={terminated}"
            r.set(f"aiquant:task:progress:{task_id}", json.dumps(data))
            # 推送事件通知前端
            channel = get_events_channel(task_id)
            r.publish(channel, json.dumps({
                "type": "revoked",
                "task_id": task_id,
                "message": "任务已被取消（优雅关机）",
                "timestamp": time.time(),
            }, ensure_ascii=False))
            logger.warning(f"[A4] 任务 {task_id} 被 revoke，中间状态已保存到 Redis")
    except Exception as e:
        logger.error(f"[A4] task_revoked 信号处理异常: {e}")


@worker_shutting_down.connect
def on_worker_shutting_down(sender, **kwargs):
    """Worker 即将关闭：通知前端正在进行的任务，避免前端无限等待。"""
    try:
        import json, time
        import redis as _redis
        r = _redis.from_url(REDIS_URL, decode_responses=True)
        # 查找所有 status=running 的任务
        for key in r.scan_iter("aiquant:task:progress:*"):
            raw = r.get(key)
            if not raw:
                continue
            data = json.loads(raw)
            if data.get("status") == "running":
                task_id = key.split(":")[-1]
                data["status"] = "interrupted"
                data["end_time"] = time.time()
                data["interrupted_reason"] = "worker_shutdown"
                r.set(key, json.dumps(data))
                channel = get_events_channel(task_id)
                r.publish(channel, json.dumps({
                    "type": "interrupted",
                    "task_id": task_id,
                    "message": "Worker 正在关闭，任务已中断保存",
                    "timestamp": time.time(),
                }, ensure_ascii=False))
                logger.info(f"[A4] 任务 {task_id} 标记为 interrupted")
        logger.info("[A4] Worker 优雅关机处理完成")
    except Exception as e:
        logger.error(f"[A4] worker_shutting_down 信号处理异常: {e}")
