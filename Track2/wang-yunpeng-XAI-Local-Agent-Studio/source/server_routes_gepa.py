"""XAI 后端路由处理器（S5-1 自动迁移，按领域拆分）。
方法体原属 server_xai.XAIHandler，统一签名 fn(h)，h 即 XAIHandler 实例。
共享单例经 server_xai import *（惰性，bootstrap 在文件末尾，循环导入安全）+ server_runtime。
"""
from __future__ import annotations
from server_xai import *   # 共享单例 / 辅助（惰性导入，安全）
from server_runtime import get_engine, get_knowledge_adapter, _CAPABILITIES

def _handle_gepa_schedule(h):
    """POST /api/gepa/schedule — 设置定时进化。

    Body JSON: {"interval_hours": 12}
    """
    try:
        content_length = int(h.headers["Content-Length"])
        body = h.rfile.read(content_length)
        data = json.loads(body)
        interval = float(data.get("interval_hours", 24.0))
    except Exception:
        h._json_response(400, {"error": "请求体无效，需要 JSON: {\"interval_hours\": <float>}"})
        return

    try:
        eng = get_engine()
        eng.gepa_scheduler.set_interval(interval)
        # 若调度尚未启动则自动启动
        status = eng.gepa_scheduler.status()
        if not status.running:
            eng.gepa_scheduler.start()
        h._json_response(200, {
            "ok": True,
            "message": f"GEPA 定时进化已设置为每 {interval} 小时",
            "interval_hours": interval,
            "running": True,
        })
    except Exception as e:
        h._json_response(500, {"error": f"设置 GEPA 定时进化失败: {e}"})

def _handle_gepa_status(h):
    """GET /api/gepa/status — 查看 GEPA 进化状态。"""
    try:
        eng = get_engine()
        status = eng.gepa_scheduler.status()
        h._json_response(200, {
            "running": status.running,
            "last_run": status.last_run,
            "last_trigger": status.last_trigger,
            "generation": status.generation,
            "pareto_frontier_size": status.pareto_frontier_size,
            "interval_hours": status.interval_hours,
            "last_error": status.last_error,
        })
    except Exception as e:
        h._json_response(500, {"error": f"获取 GEPA 状态失败: {e}"})

def _handle_gepa_trigger(h):
    """POST /api/gepa/trigger — 手动触发一次 GEPA 进化。"""
    try:
        eng = get_engine()
        status = eng.gepa_scheduler.trigger_evolution(reason="manual: API")
        h._json_response(200, {
            "ok": True,
            "message": "GEPA 进化已触发",
            "generation": status.generation,
            "last_run": status.last_run,
            "last_error": status.last_error,
        })
    except Exception as e:
        h._json_response(500, {"error": f"GEPA 进化触发失败: {e}"})

def register(router) -> None:
    router.add("GET", "/api/gepa/status", _handle_gepa_status)
    router.add("POST", "/api/gepa/trigger", _handle_gepa_trigger)
    router.add("POST", "/api/gepa/schedule", _handle_gepa_schedule)
