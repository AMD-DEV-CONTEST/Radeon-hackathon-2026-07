"""XAI 运行监控看板路由（T4 · 六维验收·维度五 运维就绪）

暴露只读 /api/metrics：真实观测数据（tracer span 聚合 + 最近 span）+ 工作流历史
计数 + 服务 uptime。鉴权由 server_xai.do_* 集中 _check_auth 保证（无 token → 401）。

不引入新依赖、不写状态，纯只读，零风险接入。
"""
from __future__ import annotations
import time as _time
from server_xai import global_tracer, _WORKFLOW_HISTORY
from server_runtime import get_engine

_BOOT_TS = _time.time()


def _handle_metrics(h):
    stats = global_tracer.stats()
    spans = global_tracer.get_spans(limit=20)
    uptime_s = int(_time.time() - _BOOT_TS)
    wf_total = len(_WORKFLOW_HISTORY)
    wf_errors = sum(1 for w in _WORKFLOW_HISTORY if w.get("status") == "error")
    payload = {
        "service": "xai-backend",
        "uptime_seconds": uptime_s,
        "uptime_human": f"{uptime_s // 3600}h{(uptime_s % 3600) // 60}m{uptime_s % 60}s",
        "tracer": stats,
        "workflow_history": {"total": wf_total, "errors": wf_errors},
        "recent_spans": spans,
        "auth": "required",
    }
    h._json_response(200, payload)


def register(router) -> None:
    router.add("GET", "/api/metrics", _handle_metrics)
