"""XAI 后端路由处理器（S5-1 自动迁移，按领域拆分）。
方法体原属 server_xai.XAIHandler，统一签名 fn(h)，h 即 XAIHandler 实例。
共享单例经 server_xai import *（惰性，bootstrap 在文件末尾，循环导入安全）+ server_runtime。
"""
from __future__ import annotations
from server_xai import *   # 共享单例 / 辅助（惰性导入，安全）
from server_runtime import get_engine, get_knowledge_adapter, _CAPABILITIES

def _handle_loop_safety_update(h):
    try:
        length = int(h.headers.get("Content-Length", "0"))
        data = json.loads(h.rfile.read(length).decode())
    except Exception:
        h._json_response(400, {"error": "无效请求"})
        return
    eng = get_engine()
    preset = data.get("preset")
    # 兼容两种格式：嵌套 {key, value} 与扁平 {token_budget: N, ...}
    if "key" in data and "value" in data:
        kwargs = {data["key"]: data["value"]}
    else:
        kwargs = {k: v for k, v in data.items() if k != "preset"}
    cfg = eng.loop_safety.save(preset=preset, **kwargs)
    h._json_response(200, {"ok": True, "config": cfg.to_dict()})

def _handle_model_add(h):
    """添加新模型到注册表。"""
    try:
        length = int(h.headers.get("Content-Length", "0"))
        data = json.loads(h.rfile.read(length).decode())
        name = data.get("name", "")
        provider = data.get("provider", "custom")
        model = data.get("model", "")
        base_url = data.get("base_url", "")
        api_key = data.get("api_key", "")
    except Exception:
        h._json_response(400, {"error": "需要 JSON: {name, provider, model, base_url, api_key}"})
        return
    if not model or not base_url:
        h._json_response(400, {"error": "model 和 base_url 必填"})
        return
    reg = get_engine().model_registry
    entry = reg.add(name=name, provider=provider, model=model, base_url=base_url, api_key=api_key)
    h._json_response(200, {"ok": True, "model": entry.to_dict(mask=True)})

def _handle_model_delete(h):
    """从注册表删除模型。"""
    try:
        length = int(h.headers.get("Content-Length", "0"))
        data = json.loads(h.rfile.read(length).decode())
        model_id = data.get("id", "")
    except Exception:
        h._json_response(400, {"error": "需要 JSON: {id}"})
        return
    ok = get_engine().model_registry.delete(model_id)
    h._json_response(200 if ok else 404, {"ok": ok})

def _handle_model_activate(h):
    """激活指定模型。路径形如 /api/models/activate/<id>（id 可能含 :）。"""
    path = h.path.split("?")[0]
    mid = path[len("/api/models/activate/"):]
    if not mid:
        h._json_response(400, {"ok": False, "error": "缺少模型 id"})
        return
    result = get_engine().model_registry.activate(mid)
    if result:
        get_engine()._rebuild_backend()
        # 模型切换同步 Grok：将新激活引擎模型映射为 Grok 模型并持久化
        # 这样"自动路由→Grok Build"的代码任务会使用与引擎一致的模型偏好
        try:
            from core.grok_build_engine import map_engine_to_grok, save_grok_pref
            gm = map_engine_to_grok(result)
            if gm:
                save_grok_pref(gm)
        except Exception:
            pass
        h._json_response(200, {"ok": True, "active": result.to_dict(mask=True)})
    else:
        h._json_response(404, {"ok": False, "error": "模型不存在"})

def register(router) -> None:
    router.add("POST", "/api/models/add", _handle_model_add)
    router.add("POST", "/api/models/delete", _handle_model_delete)
    router.add_prefix("POST", "/api/models/activate/", _handle_model_activate)
    router.add("POST", "/api/loop-safety-update", _handle_loop_safety_update)
