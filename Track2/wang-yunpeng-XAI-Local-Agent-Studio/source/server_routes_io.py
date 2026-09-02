"""XAI 后端路由处理器（S5-1 自动迁移，按领域拆分）。
方法体原属 server_xai.XAIHandler，统一签名 fn(h)，h 即 XAIHandler 实例。
共享单例经 server_xai import *（惰性，bootstrap 在文件末尾，循环导入安全）+ server_runtime。
"""
from __future__ import annotations
from server_xai import *   # 共享单例 / 辅助（惰性导入，安全）
from server_runtime import get_engine, get_knowledge_adapter, _CAPABILITIES

def _handle_coordination_chat(h):
    """多 Agent 群聊：发布消息到指定 Room。"""
    try:
        length = int(h.headers.get("Content-Length", "0"))
        body = h.rfile.read(length).decode("utf-8")
        data = json.loads(body)
        agent = data.get("agent", "Coordinator")
        text = data.get("text", "")
        room = data.get("room", "")
    except Exception:
        h._json_response(400, {"error": "需要 JSON: {agent, text, room}"})
        return
    if not text:
        h._json_response(400, {"error": "text 不能为空"})
        return
    eng = get_engine()
    if not room:
        room = eng.coordination.list_rooms()[0] if eng.coordination.list_rooms() else eng.coordination.create_room("default")
    msg = eng.coordination.publish(room, agent, text)
    h._json_response(200, {
        "ok": True, "msg_id": msg.id, "room": room,
        "history": [{"sender": m.sender, "text": m.text, "ts": m.ts}
                     for m in eng.coordination.history(room)[-10:]]
    })

def _handle_save(h):
    """保存生成内容为文件：JSON {name, content, ext} → 落盘 workspace/artifacts/。"""
    try:
        length = int(h.headers.get("Content-Length", "0"))
        data = json.loads(h.rfile.read(length).decode("utf-8"))
        name = data.get("name", "artifact") or "artifact"
        content = data.get("content", "")
        ext = "".join(c for c in (data.get("ext") or "md") if c.isalnum())[:10] or "md"
        safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in str(name))
        if not safe:
            safe = "artifact"
        stored = f"artifacts/{safe}.{ext}"
        engine = get_engine()
        abs_path = engine.openclaw.workspace_path(stored)
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(content)
    except Exception as e:
        h._json_response(400, {"ok": False, "error": f"保存失败: {e}"})
        return
    h._json_response(200, {"ok": True, "stored": stored, "path": abs_path})

def _handle_upload(h):
    """上传本地文件：base64 JSON {name, mime, data_base64} → 落盘 workspace/uploads/。"""
    try:
        length = int(h.headers.get("Content-Length", "0"))
        data = json.loads(h.rfile.read(length).decode("utf-8"))
        raw_name = data.get("name", "file") or "file"
        data_b64 = data.get("data_base64", "")
        if not data_b64:
            h._json_response(400, {"ok": False, "error": "缺少 data_base64"})
            return
        safe = os.path.basename(raw_name)
        if not safe or safe in (".", ".."):
            safe = "file"
        stamp = time.strftime("%Y%m%d%H%M%S") + f"{int((time.time() % 1) * 1000):03d}"
        stored = f"{stamp}_{safe}"
        engine = get_engine()
        abs_path = engine.openclaw.workspace_path("uploads/" + stored)
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        with open(abs_path, "wb") as f:
            f.write(base64.b64decode(data_b64))
    except Exception as e:
        h._json_response(400, {"ok": False, "error": f"上传失败: {e}"})
        return
    h._json_response(200, {"ok": True, "name": raw_name, "stored": stored, "path": abs_path})

def register(router) -> None:
    router.add("POST", "/api/upload", _handle_upload)
    router.add("POST", "/api/save", _handle_save)
    router.add("POST", "/api/coordination/chat", _handle_coordination_chat)
