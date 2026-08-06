"""XAI 后端路由处理器（S5-1 自动迁移，按领域拆分）。
方法体原属 server_xai.XAIHandler，统一签名 fn(h)，h 即 XAIHandler 实例。
共享单例经 server_xai import *（惰性，bootstrap 在文件末尾，循环导入安全）+ server_runtime。
"""
from __future__ import annotations
from server_xai import *   # 共享单例 / 辅助（惰性导入，安全）
from server_runtime import get_engine, get_knowledge_adapter, _CAPABILITIES

def _handle_mcp_create(h):
    """POST /api/mcp/create — 创建新 MCP 配置"""
    try:
        length = int(h.headers.get("Content-Length", "0"))
        data = json.loads(h.rfile.read(length).decode("utf-8")) if length else {}
    except Exception:
        h._json_response(400, {"error": "需要 JSON: {name, command/url, args?, env?}"})
        return
    name = (data.get("name") or "").strip()
    if not name:
        h._json_response(400, {"error": "name 不能为空"})
        return
    configs = h._mcp_load()
    mcp_type = "url" if data.get("url") else "command"
    new_mcp = {
        "id": h._mcp_next_id(configs),
        "name": name,
        "type": data.get("type", mcp_type),
        "command": data.get("command", ""),
        "url": data.get("url", ""),
        "args": data.get("args", []) if isinstance(data.get("args"), list) else [],
        "env": data.get("env", {}) if isinstance(data.get("env"), dict) else {},
        "enabled": data.get("enabled", True),
    }
    configs.append(new_mcp)
    h._mcp_save(configs)
    h._json_response(200, {"ok": True, "mcp": new_mcp})

def _handle_mcp_import(h):
    """POST /api/mcp/import — 一键导入：批量导入 MCP 配置"""
    try:
        length = int(h.headers.get("Content-Length", "0"))
        data = json.loads(h.rfile.read(length).decode("utf-8")) if length else {}
    except Exception:
        h._json_response(400, {"error": "需要 JSON: {mcp_list: [...]}"})
        return
    mcp_list = data.get("mcp_list", [])
    if not isinstance(mcp_list, list) or not mcp_list:
        h._json_response(400, {"error": "mcp_list 必须为非空数组"})
        return
    configs = h._mcp_load()
    imported = []
    for item in mcp_list:
        name = (item.get("name") or "").strip()
        if not name:
            continue
        new_mcp = {
            "id": h._mcp_next_id(configs),
            "name": name,
            "type": item.get("type", "command"),
            "command": item.get("command", ""),
            "url": item.get("url", ""),
            "args": item.get("args", []) if isinstance(item.get("args"), list) else [],
            "env": item.get("env", {}) if isinstance(item.get("env"), dict) else {},
            "enabled": item.get("enabled", True),
        }
        configs.append(new_mcp)
        imported.append(new_mcp)
    h._mcp_save(configs)
    h._json_response(200, {"ok": True, "imported": len(imported), "mcps": imported})

def _handle_mcp_learn(h):
    """POST /api/mcp/learn — 一键学习：从 GitHub URL 或 JSON URL 解析 MCP 配置"""
    try:
        length = int(h.headers.get("Content-Length", "0"))
        data = json.loads(h.rfile.read(length).decode("utf-8")) if length else {}
    except Exception:
        h._json_response(400, {"error": "需要 JSON: {url}"})
        return
    url = (data.get("url") or "").strip()
    if not url:
        h._json_response(400, {"error": "url 不能为空"})
        return
    try:
        import urllib.request as _ur
        result = {"url": url, "parsed": None, "registered": False}
        mcp_info = None
        if "github.com" in url:
            # GitHub URL → 自动拼接 raw URL 读取 package.json / mcp.json
            raw_base = url.replace("https://github.com", "https://raw.githubusercontent.com").rstrip("/")
            # 尝试读取 mcp.json
            for cfg_name in ("mcp.json", "package.json"):
                try:
                    raw_url = f"{raw_base}/main/{cfg_name}"
                    req = _ur.Request(raw_url, headers={"User-Agent": "XAI-MCP-Learner/1.0"})
                    with _ur.urlopen(req, timeout=10) as resp:
                        cfg = json.loads(resp.read().decode("utf-8"))
                        if "mcpServers" in cfg:
                            servers = cfg["mcpServers"]
                            first_name = list(servers.keys())[0] if servers else ""
                            first_srv = servers[first_name] if first_name else {}
                            mcp_info = {
                                "name": first_name or "learned-mcp",
                                "type": "command" if "command" in first_srv else "url",
                                "command": first_srv.get("command", ""),
                                "url": first_srv.get("url", ""),
                                "args": first_srv.get("args", []),
                                "env": first_srv.get("env", {}),
                            }
                            break
                        elif "mcp" in cfg:
                            mc = cfg["mcp"]
                            mcp_info = {
                                "name": mc.get("name", cfg.get("name", "learned-mcp")),
                                "type": "command" if "command" in mc else "url",
                                "command": mc.get("command", ""),
                                "url": mc.get("url", ""),
                                "args": mc.get("args", []),
                                "env": mc.get("env", {}),
                            }
                            break
                        elif "name" in cfg:
                            mcp_info = {
                                "name": cfg.get("name", "learned-mcp"),
                                "type": "url" if "url" in cfg else "command",
                                "command": cfg.get("command", ""),
                                "url": cfg.get("url", url),
                                "args": cfg.get("args", []),
                                "env": cfg.get("env", {}),
                            }
                            break
                except Exception:
                    continue
        else:
            # 直接 JSON URL
            try:
                req = _ur.Request(url, headers={"User-Agent": "XAI-MCP-Learner/1.0"})
                with _ur.urlopen(req, timeout=10) as resp:
                    cfg = json.loads(resp.read().decode("utf-8"))
                    if "mcpServers" in cfg and cfg["mcpServers"]:
                        first_name = list(cfg["mcpServers"].keys())[0]
                        first_srv = cfg["mcpServers"][first_name]
                        mcp_info = {
                            "name": first_name,
                            "type": "command" if "command" in first_srv else "url",
                            "command": first_srv.get("command", ""),
                            "url": first_srv.get("url", ""),
                            "args": first_srv.get("args", []),
                            "env": first_srv.get("env", {}),
                        }
                    else:
                        mcp_info = {
                            "name": cfg.get("name", "learned-mcp"),
                            "type": "command" if "command" in cfg else "url",
                            "command": cfg.get("command", ""),
                            "url": cfg.get("url", url),
                            "args": cfg.get("args", []),
                            "env": cfg.get("env", {}),
                        }
            except Exception as je:
                h._json_response(400, {"ok": False, "error": f"无法解析 URL 返回的 JSON: {je}"})
                return
        if not mcp_info or not mcp_info.get("name"):
            h._json_response(400, {"ok": False, "error": "无法从 URL 解析出有效 MCP 配置"})
            return
        result["parsed"] = mcp_info
        # 自动注册
        configs = h._mcp_load()
        new_mcp = {
            "id": h._mcp_next_id(configs),
            "name": mcp_info["name"],
            "type": mcp_info["type"],
            "command": mcp_info.get("command", ""),
            "url": mcp_info.get("url", ""),
            "args": mcp_info.get("args", []),
            "env": mcp_info.get("env", {}),
            "enabled": True,
        }
        configs.append(new_mcp)
        h._mcp_save(configs)
        result["registered"] = True
        result["mcp"] = new_mcp
        h._json_response(200, result)
    except Exception as e:
        h._json_response(500, {"error": f"一键学习失败: {e}"})

def _handle_mcp_list(h):
    """GET /api/mcp/list — 返回所有 MCP 配置列表"""
    try:
        configs = h._mcp_load()
        h._json_response(200, {"mcps": configs})
    except Exception as e:
        h._json_response(500, {"error": f"读取 MCP 配置失败: {e}"})

def register(router) -> None:
    router.add("GET", "/api/mcp/list", _handle_mcp_list)
    router.add("POST", "/api/mcp/create", _handle_mcp_create)
    router.add("POST", "/api/mcp/learn", _handle_mcp_learn)
    router.add("POST", "/api/mcp/import", _handle_mcp_import)
