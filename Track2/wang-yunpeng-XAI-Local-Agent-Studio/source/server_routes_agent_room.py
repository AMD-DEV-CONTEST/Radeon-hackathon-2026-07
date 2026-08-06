"""Agent 协作室 REST 路由（Buzz 多 Agent 同室协作理念的本地化实现）。

端点：
  GET    /api/agent_rooms                 列出所有协作室
  POST   /api/agent_rooms                 创建协作室 {name, agents:[{name,role,system_prompt,color,model}], canvas_id?}
  GET    /api/agent_rooms/<id>            获取协作室详情（含 agents + transcript）
  DELETE /api/agent_rooms/<id>            删除协作室
  POST   /api/agent_rooms/<id>/message    发起一轮多 Agent 协作 {text} → 返回 transcript
  POST   /api/agent_rooms/<id>/reset      清空 transcript
"""

from server_runtime import get_engine
from core.agent_room import default_manager as _mgr, run_agent_room, AgentRoom


def _read_json(h):
    try:
        length = int(h.headers.get("Content-Length", "0"))
        return (h.rfile.read(length).decode("utf-8") if length else "{}")
    except Exception:
        return "{}"


def _clean_path(h) -> str:
    p = h.path.split("?")[0]
    if "%" in p:
        import urllib.parse
        p = urllib.parse.unquote(p)
    return p.rstrip("/") or "/"


def _room_id_from_path(h) -> str:
    """从 /api/agent_rooms/<id>[/sub] 解析房间 id。"""
    parts = [x for x in _clean_path(h).split("/") if x]
    # parts: ['api', 'agent_rooms', '<id>', ...]
    return parts[2] if len(parts) >= 3 else ""


def _handle_rooms_list(h):
    rooms = _mgr.list_rooms()
    h._json_response(200, {"rooms": [
        {"id": r.id, "name": r.name, "agent_count": len(r.agents),
         "canvas_id": r.canvas_id, "messages": len(r.transcript)}
        for r in rooms
    ]})


def _handle_room_create(h):
    raw = _read_json(h)
    try:
        data = __import__("json").loads(raw) if raw else {}
    except Exception:
        h._json_response(400, {"error": "JSON 解析失败"})
        return
    name = (data.get("name") or "").strip()
    agents = data.get("agents") or []
    if not name:
        h._json_response(400, {"error": "需要 name"})
        return
    if not isinstance(agents, list) or not agents:
        h._json_response(400, {"error": "agents 必须为非空列表"})
        return
    room = _mgr.create_room(name, agents, canvas_id=(data.get("canvas_id") or ""))
    h._json_response(200, {"id": room.id, "name": room.name, "agents": len(room.agents)})


def _handle_room_get(h):
    rid = _room_id_from_path(h)
    room = _mgr.get_room(rid)
    if not room:
        h._json_response(404, {"error": "协作室不存在"})
        return
    h._json_response(200, {
        "id": room.id, "name": room.name, "canvas_id": room.canvas_id,
        "agents": [{"id": a.id, "name": a.name, "role": a.role,
                    "system_prompt": a.system_prompt, "color": a.color, "model": a.model}
                   for a in room.agents],
        "transcript": room.transcript,
    })


def _handle_room_delete(h):
    rid = _room_id_from_path(h)
    ok = _mgr.delete_room(rid)
    h._json_response(200, {"deleted": rid, "ok": ok})


def _handle_room_message(h):
    rid = _room_id_from_path(h)
    room = _mgr.get_room(rid)
    if not room:
        h._json_response(404, {"error": "协作室不存在"})
        return
    if not room.agents:
        h._json_response(400, {"error": "协作室没有任何 Agent 成员"})
        return
    raw = _read_json(h)
    try:
        data = __import__("json").loads(raw) if raw else {}
    except Exception:
        h._json_response(400, {"error": "JSON 解析失败"})
        return
    text = (data.get("text") or "").strip()
    if not text:
        h._json_response(400, {"error": "需要 text"})
        return
    engine = get_engine()
    # 依次运行各 Agent，累积 transcript（已在 run_agent_room 内持久化）
    for _ev in run_agent_room(engine, room, text, manager=_mgr):
        pass
    h._json_response(200, {"id": room.id, "transcript": room.transcript})


def _handle_room_reset(h):
    rid = _room_id_from_path(h)
    ok = _mgr.clear_transcript(rid)
    h._json_response(200, {"reset": rid, "ok": ok})


def _handle_room_post(h):
    """POST 子路径分发器。

    路由注册表只支持精确/前缀匹配，同 (method, prefix) 只会命中第一条，
    因此 /message 与 /reset 必须由单一分发器按子路径区分，不能各注册一条前缀。
    """
    p = _clean_path(h)
    if p.endswith("/message"):
        _handle_room_message(h)
    elif p.endswith("/reset"):
        _handle_room_reset(h)
    else:
        h._json_response(404, {"error": "未知的协作室子路径", "path": p})


def register(router) -> None:
    router.add("GET", "/api/agent_rooms", _handle_rooms_list)
    router.add("POST", "/api/agent_rooms", _handle_room_create)
    # 动态房间子路径用前缀匹配（路由注册表仅支持精确/前缀匹配，无 <id> 占位）
    router.add_prefix("GET", "/api/agent_rooms/", _handle_room_get)
    router.add_prefix("DELETE", "/api/agent_rooms/", _handle_room_delete)
    router.add_prefix("POST", "/api/agent_rooms/", _handle_room_post)
