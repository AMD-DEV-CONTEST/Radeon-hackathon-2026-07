"""XAI 后端路由处理器（S5-1 自动迁移，按领域拆分）。
方法体原属 server_xai.XAIHandler，统一签名 fn(h)，h 即 XAIHandler 实例。
共享单例经 server_xai import *（惰性，bootstrap 在文件末尾，循环导入安全）+ server_runtime。
"""
from __future__ import annotations
from server_xai import *   # 共享单例 / 辅助（惰性导入，安全）
from server_runtime import get_engine, get_knowledge_adapter, _CAPABILITIES

def _handle_connectors_create(h):
    """POST /api/connectors/create → 创建 MCP 连接器"""
    try:
        length = int(h.headers.get("Content-Length", "0"))
        data = json.loads(h.rfile.read(length).decode("utf-8")) if length else {}
    except Exception:
        h._json_response(400, {"error": "需要 JSON: {name, type, command, args, url, env}"})
        return
    name = (data.get("name") or "").strip()
    if not name:
        h._json_response(400, {"error": "name 不能为空"})
        return
    connector = {
        "name": name,
        "type": data.get("type", "stdio"),
        "command": data.get("command", ""),
        "args": data.get("args", []),
        "url": data.get("url", ""),
        "env": data.get("env", {}),
    }
    try:
        connectors = h._connectors_load()
        # 同名覆盖
        existing = next((i for i, c in enumerate(connectors) if c.get("name") == name), None)
        if existing is not None:
            connectors[existing] = connector
        else:
            connectors.append(connector)
        h._connectors_save(connectors)
        h._json_response(200, {"ok": True, "connector": connector, "total": len(connectors)})
    except Exception as e:
        h._json_response(500, {"error": f"创建连接器失败: {e}"})

def _handle_connectors_delete(h):
    """POST /api/connectors/delete → 删除 MCP 连接器"""
    try:
        length = int(h.headers.get("Content-Length", "0"))
        data = json.loads(h.rfile.read(length).decode("utf-8")) if length else {}
    except Exception:
        h._json_response(400, {"error": "需要 JSON: {name}"})
        return
    name = (data.get("name") or data.get("id") or "").strip()
    if not name:
        h._json_response(400, {"error": "name 不能为空"})
        return
    try:
        connectors = h._connectors_load()
        before = len(connectors)
        connectors = [c for c in connectors if c.get("name") != name and c.get("id") != name]
        if len(connectors) == before:
            h._json_response(404, {"ok": False, "error": f"连接器 '{name}' 不存在"})
            return
        h._connectors_save(connectors)
        h._json_response(200, {"ok": True, "deleted": name, "total": len(connectors)})
    except Exception as e:
        h._json_response(500, {"error": f"删除连接器失败: {e}"})

def _handle_connectors_list(h):
    """GET /api/connectors → 列出所有 MCP 连接器"""
    try:
        h._json_response(200, {"connectors": h._connectors_load()})
    except Exception as e:
        h._json_response(500, {"error": f"读取连接器列表失败: {e}"})

def _handle_connectors_test(h):
    """POST /api/connectors/test → 测试连接器健康状态"""
    try:
        length = int(h.headers.get("Content-Length", "0"))
        data = json.loads(h.rfile.read(length).decode("utf-8")) if length else {}
    except Exception:
        h._json_response(400, {"error": "需要 JSON: {name}"})
        return
    name = (data.get("name") or data.get("id") or "").strip()
    if not name:
        h._json_response(400, {"error": "name 不能为空"})
        return
    try:
        connectors = h._connectors_load()
        connector = next((c for c in connectors if c.get("name") == name or c.get("id") == name), None)
        if not connector:
            h._json_response(404, {"ok": False, "error": f"连接器 '{name}' 不存在"})
            return
        ctype = connector.get("type", "stdio")
        if ctype == "sse" or ctype == "http":
            url = connector.get("url", "")
            if url:
                import urllib.request
                try:
                    req = urllib.request.Request(url, method="HEAD")
                    with urllib.request.urlopen(req, timeout=5) as resp:
                        h._json_response(200, {"ok": True, "connector": name, "type": ctype, "status": "reachable", "http_code": resp.status})
                except Exception as ue:
                    h._json_response(200, {"ok": False, "connector": name, "type": ctype, "status": "unreachable", "error": str(ue)})
            else:
                h._json_response(200, {"ok": False, "connector": name, "type": ctype, "status": "no_url", "error": "未配置 URL"})
        else:
            # stdio: 仅检查 command 是否存在
            import shutil
            cmd = connector.get("command", "")
            if not cmd:
                h._json_response(200, {"ok": False, "connector": name, "type": ctype, "status": "no_command", "error": "未配置 command"})
            elif shutil.which(cmd.split()[0] if " " in cmd else cmd):
                h._json_response(200, {"ok": True, "connector": name, "type": ctype, "status": "command_found", "command": cmd})
            else:
                h._json_response(200, {"ok": False, "connector": name, "type": ctype, "status": "command_not_found", "command": cmd})
    except Exception as e:
        h._json_response(500, {"error": f"测试连接器失败: {e}"})

def register(router) -> None:
    router.add("GET", "/api/connectors", _handle_connectors_list)
    router.add("POST", "/api/connectors/create", _handle_connectors_create)
    router.add("POST", "/api/connectors/delete", _handle_connectors_delete)
    router.add("POST", "/api/connectors/test", _handle_connectors_test)
