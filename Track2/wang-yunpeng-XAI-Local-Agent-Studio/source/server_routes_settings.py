"""XAI 后端路由处理器（S5-1 自动迁移，按领域拆分）。
方法体原属 server_xai.XAIHandler，统一签名 fn(h)，h 即 XAIHandler 实例。
共享单例经 server_xai import *（惰性，bootstrap 在文件末尾，循环导入安全）+ server_runtime。
"""
from __future__ import annotations
from server_xai import *   # 共享单例 / 辅助（惰性导入，安全）
from server_runtime import get_engine, get_knowledge_adapter, _CAPABILITIES

def _handle_resource_run(h, kind: str):
    """手动运行 / 事件触发：自动化或定时任务。执行提示词并写回运行历史。"""
    try:
        length = int(h.headers.get("Content-Length", "0"))
        data = json.loads(h.rfile.read(length).decode("utf-8")) if length else {}
    except Exception:
        h._json_response(400, {"error": "无效 JSON 请求体"})
        return
    rid = data.get("id")
    if not rid:
        h._json_response(400, {"error": "缺少 id"})
        return
    if kind == "automation":
        item = app_store.automation_get(rid)
        mark = app_store.automation_mark_run
    else:
        item = app_store.schedule_get(rid)
        mark = app_store.schedule_mark_run
    if not item:
        h._json_response(404, {"error": "not found", "id": rid})
        return
    prompt = data.get("prompt") or item.get("prompt", "")
    if not prompt:
        h._json_response(400, {"error": "该条目没有可执行提示词"})
        return
    ok, detail = _execute_prompt(prompt, f"{kind}:{rid}")
    mark(rid, ok=ok, detail=detail)
    h._json_response(200, {"ok": ok, "detail": detail, "item": item.get("name", rid)})

def _handle_settings_update(h):
    """前端 Settings → 后端：批量写入设置项。"""
    try:
        length = int(h.headers.get("Content-Length", "0"))
        data = json.loads(h.rfile.read(length).decode("utf-8")) if length else {}
    except Exception:
        h._json_response(400, {"error": "无效 JSON 请求体"})
        return
    if not isinstance(data, dict):
        h._json_response(400, {"error": "需要 JSON 对象 {key: value}"})
        return
    h._json_response(200, app_store.settings_set(data))

def _handle_resource_run_route(h):
    _handle_resource_run(h, 'automation')

def _handle_resource_run_route(h):
    _handle_resource_run(h, 'schedule')

def register(router) -> None:
    router.add("POST", "/api/settings", _handle_settings_update)
    router.add("POST", "/api/automations/run", _handle_resource_run_route)
    router.add("POST", "/api/automations/trigger", _handle_resource_run_route)
    router.add("POST", "/api/schedules/run", _handle_resource_run_route)
