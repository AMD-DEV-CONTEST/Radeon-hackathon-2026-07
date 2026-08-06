"""XAI 后端路由：Grok Build 代码引擎能力面（v0.2.111 完整嵌入）。

方法体签名 fn(h)，h 即 XAIHandler 实例；经 server_xai import * 共享单例。
通过 engine.grok_build（GrokBuildBridge）调用真实本地 grok 二进制。

暴露能力：
- GET  /api/grok/health        引擎健康 + 版本
- GET  /api/grok/models        可用模型清单
- GET  /api/grok/inspect       当前目录配置发现（skills/权限/登录）
- GET  /api/grok/doctor        环境体检
- GET  /api/grok/sessions      历史会话
- GET  /api/grok/capabilities  结构化能力清单（前端展示用）
- POST /api/grok/run           headless 代码执行（真实调用，可能耗时）
- GET  /api/grok/history        XAI 自有运行历史列表（每次 run 后自动落盘）
- GET  /api/grok/history/<id>   历史详情（含完整 result_json，用于恢复）
- DELETE /api/grok/history/<id> 删除一条历史
"""
from __future__ import annotations
from server_xai import *   # 共享单例 / 辅助（惰性导入，安全）
from server_runtime import get_engine
from core.grok_build_engine import build_grok_context
from core.grok_history_store import get_grok_history_store


def _bridge():
    """获取 GrokBuildBridge 单例。"""
    eng = get_engine()
    return getattr(eng, "grok_build", None)


def _handle_grok_health(h):
    """GET /api/grok/health → grok 桥接健康 + 版本"""
    try:
        gb = _bridge()
        if gb is None:
            h._json_response(200, {"grok_build_bridge": "unavailable", "reason": "引擎未装配 grok_build"})
            return
        h._json_response(200, gb.health_check())
    except Exception as e:
        h._json_response(500, {"error": f"grok 健康检查失败: {e}"})


def _handle_grok_models(h):
    """GET /api/grok/models → 可用模型清单"""
    try:
        gb = _bridge()
        if gb is None or not gb.available:
            h._json_response(200, {"ok": False, "error": "grok 不可用", "models": [], "default": None})
            return
        h._json_response(200, gb.list_models())
    except Exception as e:
        h._json_response(500, {"error": f"读取 grok 模型失败: {e}"})


def _handle_grok_inspect(h):
    """GET /api/grok/inspect → 当前目录配置发现"""
    try:
        gb = _bridge()
        if gb is None or not gb.available:
            h._json_response(200, {"ok": False, "error": "grok 不可用"})
            return
        h._json_response(200, gb.inspect(cwd=os.getcwd()))
    except Exception as e:
        h._json_response(500, {"error": f"grok inspect 失败: {e}"})


def _handle_grok_doctor(h):
    """GET /api/grok/doctor → 环境体检"""
    try:
        gb = _bridge()
        if gb is None or not gb.available:
            h._json_response(200, {"ok": False, "error": "grok 不可用"})
            return
        h._json_response(200, gb.doctor())
    except Exception as e:
        h._json_response(500, {"error": f"grok doctor 失败: {e}"})


def _handle_grok_sessions(h):
    """GET /api/grok/sessions → 历史会话列表"""
    try:
        gb = _bridge()
        if gb is None or not gb.available:
            h._json_response(200, {"ok": False, "error": "grok 不可用", "sessions_sample": []})
            return
        h._json_response(200, gb.list_sessions())
    except Exception as e:
        h._json_response(500, {"error": f"grok sessions 失败: {e}"})


def _handle_grok_capabilities(h):
    """GET /api/grok/capabilities → 结构化能力清单"""
    try:
        gb = _bridge()
        if gb is None:
            h._json_response(200, {"available": False, "capabilities": []})
            return
        h._json_response(200, gb.capabilities())
    except Exception as e:
        h._json_response(500, {"error": f"读取 grok 能力失败: {e}"})


def _handle_grok_run(h):
    """POST /api/grok/run → headless 代码执行（真实调用 grok，可能耗时）

    请求 body（JSON）：
      task            (必填) 任务描述
      model           模型 key（如 deepseek-flash / grok-4.5），空则默认
      check           bool，追加 --check 自验证
      best_of_n       int，>1 时并行多路
      max_turns       int，轮数上限
      sandbox         沙箱 profile
      permission_mode 权限模式
      disable_web     bool，关闭联网
      timeout         超时秒（默认 300）
    """
    try:
        try:
            length = int(h.headers.get("Content-Length", "0"))
            body = h.rfile.read(length).decode("utf-8") if length else "{}"
            data = json.loads(body or "{}")
        except Exception:
            h._json_response(400, {"ok": False, "error": "无效请求体，需要 JSON: {\"task\": \"...\"}"})
            return
        task = (data.get("task") or "").strip()
        if not task:
            h._json_response(400, {"ok": False, "error": "task 不能为空"})
            return

        gb = _bridge()
        if gb is None or not gb.available:
            h._json_response(200, {"ok": False, "error": "grok 不可用，请检查二进制"})
            return

        # 记忆注入：从 XAI 8层检索相关上下文增强 prompt（可通过 inject_memory:false 关闭）
        if data.get("inject_memory", True):
            try:
                eng = get_engine()
                ctx = build_grok_context(task, eng.memory_core)
                if ctx:
                    task = task + ctx
            except Exception:
                pass  # 注入失败不阻断主流程

        # 组装 extra_flags（check / best-of-n）
        flags: list[str] = []
        if data.get("check"):
            flags.append("--check")
        bon = int(data.get("best_of_n") or 0)
        if bon and bon > 1:
            flags.extend(["--best-of-n", str(bon)])

        result = gb.run(
            task,
            cwd=os.getcwd(),
            extra_flags=" ".join(flags),
            model=(data.get("model") or ""),
            timeout=int(data.get("timeout") or 300),
            sandbox=(data.get("sandbox") or ""),
            max_turns=int(data.get("max_turns") or 0),
            permission_mode=(data.get("permission_mode") or ""),
            disable_web_search=bool(data.get("disable_web")),
        )

        # 事后记忆反思（复用引擎逻辑，不阻断）
        try:
            eng = get_engine()
            if hasattr(eng, "_reflect_grok_result"):
                eng._reflect_grok_result(task, result)
        except Exception:
            pass

        # 自动落盘运行历史（XAI 自有，区别于 grok sessions list；
        # 失败/成功都记，ok 标志区分；落盘失败不阻断主流程）
        try:
            _ok = bool(result.get("ok", True)) if isinstance(result, dict) else True
            _summary = ((result.get("text") if isinstance(result, dict) else "") or "").strip() \
                       or (result.get("error") if isinstance(result, dict) else "") or "" \
                       or task
            get_grok_history_store().add_run(
                task=task,
                model=(data.get("model") or "") or None,
                ok=_ok,
                summary=_summary[:140],
                result_json=result if isinstance(result, dict) else {"raw": str(result)},
                grok_session_id=((result.get("sessionId") or result.get("session_id")) if isinstance(result, dict) else None),
            )
        except Exception:
            pass

        h._json_response(200, result)
    except Exception as e:
        h._json_response(500, {"ok": False, "error": f"grok run 失败: {e}"})


def _handle_grok_history_list(h):
    """GET /api/grok/history → XAI 自有运行历史列表（不含完整 result_json）"""
    try:
        store = get_grok_history_store()
        runs = store.list_runs(limit=100)
        h._json_response(200, {"ok": True, "count": len(runs), "runs": runs})
    except Exception as e:
        h._json_response(500, {"ok": False, "error": f"读取 grok 历史失败: {e}"})


def _handle_grok_history_item(h):
    """GET /api/grok/history/<id> → 完整记录（含 result_json，用于历史恢复）"""
    rid = h.path.split("?")[0].rsplit("/", 1)[-1]
    try:
        store = get_grok_history_store()
        rec = store.get_run(rid)
        if rec is None:
            h._json_response(404, {"ok": False, "error": "历史记录不存在"})
            return
        h._json_response(200, {"ok": True, **rec})
    except Exception as e:
        h._json_response(500, {"ok": False, "error": f"读取 grok 历史详情失败: {e}"})


def _handle_grok_history_delete(h):
    """DELETE /api/grok/history/<id> → 删除一条记录"""
    rid = h.path.split("?")[0].rsplit("/", 1)[-1]
    try:
        store = get_grok_history_store()
        deleted = store.delete_run(rid)
        h._json_response(200, {"ok": True, "deleted": deleted, "id": rid})
    except Exception as e:
        h._json_response(500, {"ok": False, "error": f"删除 grok 历史失败: {e}"})


def _handle_grok_model_get(h):
    """GET /api/grok/model → 当前同步的 Grok 模型 key（优先用户偏好，否则由引擎激活模型推导）"""
    try:
        from core.grok_build_engine import resolve_grok_model, load_grok_pref, map_engine_to_grok
        eng = get_engine()
        pref = load_grok_pref()
        model = pref or resolve_grok_model(eng)
        engine_derived = map_engine_to_grok(eng.model_registry.active()) if eng and eng.model_registry else ""
        h._json_response(200, {"ok": True, "model": model, "overridden": bool(pref), "engine_derived": engine_derived})
    except Exception as e:
        h._json_response(500, {"error": f"读取 grok 模型失败: {e}"})


def _handle_grok_model_set(h):
    """POST /api/grok/model/set → 显式设置 Grok 模型偏好（空串=清除，回到引擎推导）"""
    try:
        length = int(h.headers.get("Content-Length", "0"))
        data = json.loads(h.rfile.read(length).decode("utf-8")) if length else {}
    except Exception:
        h._json_response(400, {"error": "无效请求体，需要 JSON: {\"model\": \"...\"}"})
        return
    model = (data.get("model") or "").strip()
    try:
        from core.grok_build_engine import save_grok_pref
        save_grok_pref(model)
        h._json_response(200, {"ok": True, "model": model})
    except Exception as e:
        h._json_response(500, {"error": f"设置 grok 模型失败: {e}"})


def register(router) -> None:
    router.add("GET", "/api/grok/health", _handle_grok_health)
    router.add("GET", "/api/grok/models", _handle_grok_models)
    router.add("GET", "/api/grok/inspect", _handle_grok_inspect)
    router.add("GET", "/api/grok/doctor", _handle_grok_doctor)
    router.add("GET", "/api/grok/sessions", _handle_grok_sessions)
    router.add("GET", "/api/grok/capabilities", _handle_grok_capabilities)
    router.add("POST", "/api/grok/run", _handle_grok_run)
    router.add("GET", "/api/grok/history", _handle_grok_history_list)
    router.add_prefix("GET", "/api/grok/history/", _handle_grok_history_item)
    router.add_prefix("DELETE", "/api/grok/history/", _handle_grok_history_delete)
    router.add("GET", "/api/grok/model", _handle_grok_model_get)
    router.add("POST", "/api/grok/model/set", _handle_grok_model_set)
