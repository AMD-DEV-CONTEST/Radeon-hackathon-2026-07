"""XAI 后端路由处理器（S5-1 自动迁移，按领域拆分）。
方法体原属 server_xai.XAIHandler，统一签名 fn(h)，h 即 XAIHandler 实例。
共享单例经 server_xai import *（惰性，bootstrap 在文件末尾，循环导入安全）+ server_runtime。
"""
from __future__ import annotations
from server_xai import *   # 共享单例 / 辅助（惰性导入，安全）
from server_xai import _hub_rooms  # import * 会跳过下划线名，需显式导入
from server_runtime import get_engine, get_knowledge_adapter, _CAPABILITIES

def _handle_hub_create(h):
    """POST /api/hub/rooms → 创建群聊房间"""
    try:
        length = int(h.headers.get("Content-Length", "0"))
        data = json.loads(h.rfile.read(length).decode("utf-8")) if length else {}
    except Exception:
        h._json_response(400, {"error": "需要 JSON body"})
        return
    name = (data.get("name") or "").strip()
    if not name:
        h._json_response(400, {"error": "name 不能为空"})
        return
    import uuid
    rid = f"room:{uuid.uuid4().hex[:12]}"
    room = {
        "id": rid,
        "name": name,
        "topic": data.get("topic", ""),
        "agents": data.get("agents", []),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "messages": [],
    }
    _hub_rooms[rid] = room
    h._json_response(200, {"ok": True, "room": {k: v for k, v in room.items() if k != "messages"}})

def _handle_team_invite(h):
    """POST /api/team/invite → 邀请成员加入团队"""
    try:
        length = int(h.headers.get("Content-Length", "0"))
        data = json.loads(h.rfile.read(length).decode("utf-8")) if length else {}
    except Exception:
        h._json_response(400, {"error": "需要 JSON body"})
        return
    name = (data.get("name") or data.get("email") or "").strip()
    role = (data.get("role") or "member").strip()
    if not name:
        h._json_response(400, {"error": "name 或 email 不能为空"})
        return
    import uuid
    member = {"id": f"member:{uuid.uuid4().hex[:8]}", "name": name, "role": role, "status": "invited"}
    h._json_response(200, {"ok": True, "member": member, "invited": name})

def register(router) -> None:
    router.add("POST", "/api/hub/rooms", _handle_hub_create)
    router.add("POST", "/api/team/invite", _handle_team_invite)
