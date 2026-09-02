"""XAI 后端路由处理器（S5-1 自动迁移，按领域拆分）。
方法体原属 server_xai.XAIHandler，统一签名 fn(h)，h 即 XAIHandler 实例。
共享单例经 server_xai import *（惰性，bootstrap 在文件末尾，循环导入安全）+ server_runtime。
"""
from __future__ import annotations
from server_xai import *   # 共享单例 / 辅助（惰性导入，安全）
from server_xai import _classify_intent  # 下划线开头，import * 不会带入，需显式导入
from server_runtime import get_engine, get_knowledge_adapter, _CAPABILITIES

def _handle_approval_confirm(h):
    try:
        length = int(h.headers.get("Content-Length", "0"))
        data = json.loads(h.rfile.read(length).decode("utf-8")) if length else {}
    except Exception:
        h._json_response(400, {"error": "无效 JSON 请求体"})
        return
    eng = get_engine()
    aid = data.get("id")
    # 修复历史死端点：调用 guardian_bridge.resolve_approval 真处置
    from core.kernel.guardian_bridge import resolve_approval
    res = resolve_approval(eng, aid, human_ok=True, reason=data.get("reason", ""))
    h._json_response(200, res)

def _handle_guardian_approve(h):
    """HITL 画布内嵌：前端提交批准/拒绝。

    请求体：{"ticket_id": "APR-0001", "human_ok": true, "reason": "已确认"}
    返回：resolve_approval 结果。
    """
    try:
        length = int(h.headers.get("Content-Length", "0"))
        data = json.loads(h.rfile.read(length).decode("utf-8")) if length else {}
    except Exception:
        h._json_response(400, {"error": "无效 JSON 请求体"})
        return
    eng = get_engine()
    aid = data.get("ticket_id") or data.get("id")
    if not aid:
        h._json_response(400, {"error": "缺少 ticket_id"})
        return
    human_ok = bool(data.get("human_ok", data.get("approved", False)))
    reason = data.get("reason", "")
    from core.kernel.guardian_bridge import resolve_approval
    res = resolve_approval(eng, aid, human_ok=human_ok, reason=reason)
    h._json_response(200, res)

def _handle_intent(h):
    try:
        length = int(h.headers.get("Content-Length", "0"))
        data = json.loads(h.rfile.read(length).decode("utf-8")) if length else {}
    except Exception:
        h._json_response(400, {"error": "无效 JSON 请求体"})
        return
    h._json_response(200, _classify_intent(data.get("text", "")))

def register(router) -> None:
    router.add("POST", "/api/intent", _handle_intent)
    router.add("POST", "/api/approvals/confirm", _handle_approval_confirm)
    router.add("POST", "/api/guardian/approve", _handle_guardian_approve)
