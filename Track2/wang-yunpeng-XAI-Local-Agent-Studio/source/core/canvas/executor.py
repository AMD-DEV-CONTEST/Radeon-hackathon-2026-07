"""画布节点执行引擎（Phase 1 — 可执行任务画布）。

职责：按节点 type 真调 ToolBus/Adapter，推送 SSE 状态（idle→running→done/failed），
       Guardian 审批门（P0/P1 节点阻止执行），Token 记账。

用法：
    POST /api/canvas/execute { nodeId, session } → SSE stream
    事件类型：status(更新 node status) / log(执行日志行) / done(完成) / error(失败)
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional

from ..guardian import classify, Action as GuardianAction

logger = logging.getLogger(__name__)

# ── 状态机 ──
STATUS_IDLE = "idle"
STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_FAILED = "failed"
STATUS_FAILED_GUARDIAN = "failed_guardian"

VALID_STATUSES = {STATUS_IDLE, STATUS_PENDING, STATUS_RUNNING, STATUS_DONE, STATUS_FAILED, STATUS_FAILED_GUARDIAN}

# ── 节点类型别名表（2026-08-04 契约对齐）──
# 背景：NL→DAG 生成器（server_routes_canvas._handle_canvas_validate 的提示词）
# 产出的词表是 input/chat/intent_router/grok_build/openclaw/kb/react/condition/output，
# 而本执行器原本只认 node_catalog 的 4 个规范类型 agent/tool/memory/text。
# 结果：AI 自动生成的画布一执行就全部 "未知节点类型"。
# 这里做一层单向归一，把生成器词表映射到可执行语义，避免两套词表继续漂移。
NODE_TYPE_ALIASES: Dict[str, str] = {
    # 规范类型直通
    "agent": "agent", "tool": "tool", "memory": "memory", "text": "text",
    # 生成器词表 → 可执行语义
    "chat": "agent",
    "react": "agent",
    "intent_router": "agent",
    "condition": "agent",
    "input": "text",
    "output": "text",
    "note": "text",
    "kb": "tool:kb",
    "knowledge": "tool:kb",
    "grok_build": "tool:grok",
    "grok": "tool:grok",
    "openclaw": "tool:exec",
    "shell": "tool:exec",
    "search": "tool:search",
    "web_search": "tool:search",
}


def resolve_node_type(node: dict) -> tuple[str, str]:
    """归一节点类型，返回 (规范类型, 隐含工具名)。

    读取优先级：data.nodeType > node.type > node.kind > "text"。
    别名映射到 "tool:xxx" 时，规范类型为 tool、隐含工具名为 xxx。
    """
    data = node.get("data") or {}
    raw = (data.get("nodeType") or node.get("type") or node.get("kind") or "text")
    raw = str(raw).strip().lower()
    mapped = NODE_TYPE_ALIASES.get(raw, raw)
    if mapped.startswith("tool:"):
        return "tool", mapped.split(":", 1)[1]
    return mapped, ""


def sse_event(event_type: str, data: dict) -> str:
    """构建 SSE 行（不含尾空行，由路由层补）。"""
    return f"data: {json.dumps({**data, 'type': event_type}, ensure_ascii=False)}\n\n"


def status_event(node_id: str, status: str, **extra) -> str:
    return sse_event("status", {"nodeId": node_id, "status": status, **extra})


def log_event(node_id: str, message: str) -> str:
    return sse_event("log", {"nodeId": node_id, "message": message})


def done_event(node_id: str, result: Optional[dict] = None) -> str:
    return sse_event("done", {"nodeId": node_id, "result": result or {}})


def error_event(node_id: str, message: str) -> str:
    return sse_event("error", {"nodeId": node_id, "message": message})


def guardian_check(node: dict) -> Optional[str]:
    """检查节点是否需要 Guardian 审批。返回 blocked 的 SSE 事件串，或 None 表示放行。"""
    node_type = (node.get("data") or {}).get("nodeType") or node.get("type") or ""
    tool = (node.get("data") or {}).get("tool") or ""
    action_type = "canvas_execute"
    if node_type == "tool" and tool in ("exec", "openclaw"):
        action_type = "exec"
    elif node_type == "agent" or tool == "grok":
        action_type = "grok"
    try:
        result = classify(GuardianAction(
            kind=action_type,
            target=f"canvas:{node.get('id','')}",
            scope="local",
        ))
    except Exception as e:
        logger.warning(f"Guardian classify failed: {e}, allowing by default")
        return None
    if result.level in ("P0", "P1"):
        return status_event(
            node["id"], STATUS_FAILED_GUARDIAN,
            reason=f"Guardian {result.level}: {result.reason}",
            ticket=result.ticket_id if hasattr(result, "ticket_id") else None,
        )
    return None


def execute_node(engine, node: dict, session: str = "") -> List[str]:
    """执行单个节点，返回 SSE 事件列表（含 status/log/done/error）。"""
    node_id = node.get("id", "")
    data = node.get("data") or {}
    node_type, implied_tool = resolve_node_type(node)
    tool = data.get("tool") or implied_tool
    args = data.get("args") or {}
    prompt = (data.get("prompt") or data.get("label")
              or node.get("label") or "")
    content = data.get("content") or ""
    # kb / search 类工具节点：没显式给 args 时用节点文案当查询词
    if node_type == "tool" and tool in ("kb", "search") and not args:
        q = (data.get("query") or prompt or content or "").strip()
        if q:
            args = {"query": q}

    events: List[str] = []

    # 1) Guardian 门
    blocked = guardian_check(node)
    if blocked:
        events.append(blocked)
        return events

    # 2) status → running
    events.append(status_event(node_id, STATUS_RUNNING))
    start_ts = time.time()

    try:
        result: Any = None
        usage: Optional[dict] = None

        if node_type == "tool" and tool:
            # 工具节点 → ToolBus 分发
            dispatch_result = engine.tool_bus.dispatch(tool, **args)
            if dispatch_result.status == "ok":
                result = dispatch_result.data if hasattr(dispatch_result, "data") else str(dispatch_result)
            elif dispatch_result.status == "empty":
                # "查了但没结果" ≠ "工具坏了"。知识库/搜索无命中是合法业务结果，
                # 之前一律当 error 处理会让整张图红掉，也让下游节点拿不到上下文。
                # 现降级为 warn 日志 + 空结果继续，节点仍判 done。
                result = {"output": "", "empty": True,
                          "note": f"{tool} 无命中（查询: {args.get('query', '')[:60]}）"}
                events.append(sse_event("log", {
                    "nodeId": node_id, "level": "warn",
                    "message": f"工具 {tool} 无命中，按空结果继续",
                }))
            else:
                _err = dispatch_result.error or f"{tool} 返回状态 {dispatch_result.status}（无错误详情）"
                events.append(error_event(node_id, f"工具 {tool} 失败: {_err}"))
                events.append(status_event(node_id, STATUS_FAILED, error=str(_err)))
                return events

        elif node_type == "agent":
            # Agent 节点 → engine 推理链
            inference = engine._infer_with_fallback(prompt=prompt or content, max_tokens=800)
            if inference.ok:
                result = {"output": inference.output, "meta": inference.meta}
            else:
                events.append(error_event(node_id, f"Agent 推理失败: {inference.error}"))
                events.append(status_event(node_id, STATUS_FAILED, error=inference.error))
                return events

        elif node_type == "memory":
            # 记忆节点 → memory_core
            op = data.get("op") or "search"
            layer = data.get("layer") or "long_term"
            query = data.get("query") or content
            try:
                from ..memory_core import MemoryCore
                mc = getattr(engine, "memory_core", None)
                if mc is None:
                    mc = MemoryCore()  # fallback 独立实例
                if op == "add":
                    rid = mc.add(layer, query, query, importance=0.5)
                    result = {"rowid": rid, "layer": layer}
                elif op == "list":
                    result = {"items": mc.list_entries(layer or None, limit=20)}
                else:  # search
                    hits = mc.search(query or content, layers=[layer] if layer else None, top_k=8)
                    result = [{"key": h.key, "value": h.value, "score": h.score} for h in hits]
            except Exception as mem_err:
                events.append(error_event(node_id, f"记忆操作失败: {mem_err}"))
                events.append(status_event(node_id, STATUS_FAILED, error=str(mem_err)))
                return events

        elif node_type == "text":
            # 文本节点 → 无操作，直接标记完成
            result = {"content": content}
            events.append(log_event(node_id, "文本节点无需执行"))

        else:
            events.append(error_event(node_id, f"未知节点类型: {node_type}"))
            events.append(status_event(node_id, STATUS_FAILED, error=f"未知类型 {node_type}"))
            return events

        # 3) 提取 usage（从 backend 最后调用的记录）
        try:
            last_usage = getattr(engine._backend, "last_usage", None)
            if last_usage:
                usage = {
                    "prompt_tokens": last_usage.get("prompt_tokens", 0),
                    "completion_tokens": last_usage.get("completion_tokens", 0),
                    "total_tokens": last_usage.get("total_tokens", 0),
                }
        except Exception:
            pass

        # 4) Token 记账
        try:
            engine.record_backend_usage(source="canvas_execute", session=session)
        except Exception:
            pass

        elapsed = round(time.time() - start_ts, 2)
        events.append(log_event(node_id, f"执行完成 ({elapsed}s)"))

        # 5) status → done
        events.append(status_event(node_id, STATUS_DONE,
                                   result=result if isinstance(result, dict) else {"output": str(result)} if result else None,
                                   usage=usage,
                                   elapsed=elapsed))
        return events

    except Exception as e:
        logger.error(f"execute_node {node_id} failed: {e}")
        events.append(error_event(node_id, str(e)))
        events.append(status_event(node_id, STATUS_FAILED, error=str(e)))
        return events


def execute_dag(engine, nodes: List[dict], edges: List[dict], session: str = "") -> List[str]:
    """按 DAG 拓扑顺序依次执行所有节点，返回合并的 SSE 事件列表。"""
    events: List[str] = []
    events.append(sse_event("dag_start", {"total": len(nodes)}))
    try:
        from ..canvas_dsl import canvas_to_plan
        plan = canvas_to_plan(nodes, edges)
        levels = plan.get("execution_plan", {}).get("levels", [])
        all_ids = {n.get("id") for n in nodes}
        ordered_ids: List[str] = []
        for level in levels:
            for nid in level:
                if nid in all_ids:
                    ordered_ids.append(nid)
        # 补齐不在 plan 中的孤立节点
        for n in nodes:
            if n.get("id") not in ordered_ids:
                ordered_ids.append(n.get("id"))
    except Exception:
        ordered_ids = [n.get("id") for n in nodes]

    id_to_node = {n.get("id"): n for n in nodes}
    for nid in ordered_ids:
        node = id_to_node.get(nid)
        if not node:
            continue
        events.append(sse_event("dag_progress", {"nodeId": nid, "index": ordered_ids.index(nid), "total": len(ordered_ids)}))
        node_events = execute_node(engine, node, session)
        events.extend(node_events)
    events.append(sse_event("dag_done", {"total": len(ordered_ids)}))
    return events

# ── P3: Autopilot — 画布节点定时执行调度器 ──

import threading
import time as _time
from datetime import datetime

_autopilot_lock = threading.Lock()
_autopilot_running = False
_autopilot_thread: Optional[threading.Thread] = None
_last_run: Dict[str, float] = {}  # node_id → last_exec_ts


def _cron_matches(cron_expr: str, now: datetime) -> bool:
    """简易 cron 匹配（支持每分钟/每小时/每天/每周）。"""
    import re
    expr = cron_expr.strip()
    # 每 N 分钟: "*/5" or "every 5m"
    m = re.match(r'^\*/(\d+)$', expr)
    if m:
        return now.minute % int(m.group(1)) == 0
    m = re.match(r'^every\s+(\d+)m', expr.lower())
    if m:
        return now.minute % int(m.group(1)) == 0
    # 每小时: "@hourly" or "0 * * * *"
    if expr in ("@hourly", "0 * * * *"):
        return now.minute == 0
    # 每天: "@daily" or "0 0 * * *"
    if expr in ("@daily", "0 0 * * *"):
        return now.hour == 0 and now.minute == 0
    # 每 N 小时: "every Nh"
    m = re.match(r'^every\s+(\d+)h', expr.lower())
    if m:
        return now.hour % int(m.group(1)) == 0 and now.minute == 0
    return False


def autopilot_tick(engine, app_store, interval: float = 30.0):
    """单次轮询：检查所有画布节点的 schedule 字段，到期执行。"""
    try:
        canvases = app_store.list() if hasattr(app_store, "list") else {"main": {}}
        if isinstance(canvases, dict):
            for cid, store in canvases.items():
                nodes = store.get("nodes", []) if isinstance(store, dict) else []
                if hasattr(store, "get"):
                    nodes = store.get("nodes", [])
                elif isinstance(store, list):
                    nodes = store
                for node in nodes:
                    data = node.get("data") or {}
                    schedule = data.get("schedule") or ""
                    if not schedule:
                        continue
                    now = datetime.now()
                    if not _cron_matches(str(schedule), now):
                        continue
                    node_id = node.get("id", "")
                    last = _last_run.get(node_id, 0)
                    if _time.time() - last < interval * 2:
                        continue  # 防重复执行
                    _last_run[node_id] = _time.time()
                    logger.info(f"autopilot: executing node {node_id} (schedule={schedule})")
                    try:
                        execute_node(engine, node, session=f"autopilot_{cid}")
                    except Exception as e:
                        logger.error(f"autopilot: node {node_id} failed: {e}")
    except Exception as e:
        logger.error(f"autopilot_tick failed: {e}")


def start_autopilot(engine, app_store, interval: float = 30.0):
    """启动后台 Autopilot 轮询线程（每 interval 秒检查一次）。"""
    global _autopilot_running, _autopilot_thread
    if _autopilot_running:
        return
    _autopilot_running = True
    def _loop():
        while _autopilot_running:
            with _autopilot_lock:
                try:
                    autopilot_tick(engine, app_store, interval)
                except Exception:
                    pass
            _time.sleep(interval)
    _autopilot_thread = threading.Thread(target=_loop, daemon=True, name="canvas-autopilot")
    _autopilot_thread.start()
    logger.info("canvas autopilot started (interval={}s)".format(interval))


def stop_autopilot():
    global _autopilot_running
    _autopilot_running = False
    logger.info("canvas autopilot stopped")
