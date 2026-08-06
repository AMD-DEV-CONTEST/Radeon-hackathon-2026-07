"""XAI 后端路由处理器（S5-1 自动迁移，按领域拆分）。
方法体原属 server_xai.XAIHandler，统一签名 fn(h)，h 即 XAIHandler 实例。
共享单例经 server_xai import *（惰性，bootstrap 在文件末尾，循环导入安全）+ server_runtime。
"""
from __future__ import annotations
from server_xai import *   # 共享单例 / 辅助（惰性导入，安全）
from server_runtime import get_engine, get_knowledge_adapter, _CAPABILITIES

def _handle_plans(h):
    seg = h.path.split("/")
    sub = seg[-1] if len(seg) > 2 else ""
    try:
        length = int(h.headers.get("Content-Length", "0"))
        data = json.loads(h.rfile.read(length).decode("utf-8")) if length else {}
    except Exception:
        h._json_response(400, {"error": "无效 JSON 请求体"})
        return
    store = _plans_load()
    if sub == "update":
        pid = data.get("id")
        if pid in store:
            store[pid] = {**store[pid], **data}
            _plans_save(store)
            h._json_response(200, store[pid])
        else:
            h._json_response(404, {"error": "plan not found"})
        return
    if sub == "delete":
        pid = data.get("id")
        if pid in store:
            del store[pid]
            _plans_save(store)
            h._json_response(200, {"ok": True})
        else:
            h._json_response(404, {"error": "plan not found"})
        return
    # create / replace
    pid = data.get("id") or f"plan_{int(time.time()*1000)}"
    data["id"] = pid
    data.setdefault("created_at", time.strftime("%Y-%m-%d %H:%M:%S"))
    store[pid] = data
    _plans_save(store)
    h._json_response(200, data)

def register(router) -> None:
    router.add_prefix("POST", "/api/plans", _handle_plans)
