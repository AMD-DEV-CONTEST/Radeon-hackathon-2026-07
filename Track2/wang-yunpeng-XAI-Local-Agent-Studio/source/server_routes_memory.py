"""XAI 后端路由处理器（S5-1 自动迁移，按领域拆分）。
方法体原属 server_xai.XAIHandler，统一签名 fn(h)，h 即 XAIHandler 实例。
共享单例经 server_xai import *（惰性，bootstrap 在文件末尾，循环导入安全）+ server_runtime。
"""
from __future__ import annotations
from server_xai import *   # 共享单例 / 辅助（惰性导入，安全）
from server_runtime import get_engine, get_knowledge_adapter, _CAPABILITIES

def _handle_memory_context(h):
    """GET /api/memory/context?text=xxx[&mode=semantic] → 混合召回 / 语义向量召回。

    mode 默认 keyword（子串40% + 关键词40% + 时间衰减20%）；
    传 mode=semantic 走 TF-IDF char-bigram 余弦语义召回（同义/近义更鲁棒）。
    需鉴权 X-Auth-Token。
    返回 {"mode": ..., "results": [{"layer", "key", "value", "score"}, ...], "count": N}。
    """
    try:
        engine = get_engine()
        if not engine:
            h._json_response(503, {"error": "引擎未初始化"})
            return
        parsed = urllib.parse.urlparse(h.path)
        params = urllib.parse.parse_qs(parsed.query)
        text = (params.get("text", [""])[0] or "").strip()
        mode = (params.get("mode", ["keyword"])[0] or "keyword").strip().lower()
        if not text:
            h._json_response(400, {"error": "缺少 text 参数", "usage": "GET /api/memory/context?text=xxx[&mode=semantic]"})
            return
        if mode == "semantic":
            from core.kernel.memory_bridge import retrieve_ranked_memories_semantic
            results = retrieve_ranked_memories_semantic(engine, text, limit=10)
        else:
            from core.kernel.memory_bridge import retrieve_ranked_memories
            results = retrieve_ranked_memories(engine, text, limit=10)
        h._json_response(200, {"mode": mode, "results": results, "count": len(results)})
    except Exception as e:
        h._json_response(500, {"error": f"记忆上下文检索失败: {e}"})

def _handle_memory_context(h):
    """GET /api/memory/context?text=xxx[&mode=semantic] → 混合召回 / 语义向量召回。

    mode 默认 keyword（子串40% + 关键词40% + 时间衰减20%）；
    传 mode=semantic 走 TF-IDF char-bigram 余弦语义召回（同义/近义更鲁棒）。
    需鉴权 X-Auth-Token。
    返回 {"mode": ..., "results": [{"layer", "key", "value", "score"}, ...], "count": N}。
    """
    try:
        engine = get_engine()
        if not engine:
            h._json_response(503, {"error": "引擎未初始化"})
            return
        parsed = urllib.parse.urlparse(h.path)
        params = urllib.parse.parse_qs(parsed.query)
        text = (params.get("text", [""])[0] or "").strip()
        mode = (params.get("mode", ["keyword"])[0] or "keyword").strip().lower()
        if not text:
            h._json_response(400, {"error": "缺少 text 参数", "usage": "GET /api/memory/context?text=xxx[&mode=semantic]"})
            return
        if mode == "semantic":
            from core.kernel.memory_bridge import retrieve_ranked_memories_semantic
            results = retrieve_ranked_memories_semantic(engine, text, limit=10)
        else:
            from core.kernel.memory_bridge import retrieve_ranked_memories
            results = retrieve_ranked_memories(engine, text, limit=10)
        h._json_response(200, {"mode": mode, "results": results, "count": len(results)})
    except Exception as e:
        h._json_response(500, {"error": f"记忆上下文检索失败: {e}"})


def _handle_memory_list(h):
    """GET /api/memory/list?layer=&keyword=&limit=50&offset=0&order=recent → 分页列出记忆条目。

    order: recent（默认，最新在前）| importance（重要性优先）。
    需鉴权 X-Auth-Token。
    返回 {"entries": [...], "total": 本页条数, "count": 符合条件总数, "offset", "limit", "order"}。

    修复（2026-08-04）：此前恒按 importance 排序且无 offset。后果：记忆中心看不到
    刚写入的低重要性条目（像是没存进去）；排在前 N 名之外的记忆永远拿不到 id，
    而改/删接口按 id 操作 —— 等于这些记忆被永久锁死。现列表页默认 recent + 分页。
    """
    try:
        engine = get_engine()
        if not engine or not hasattr(engine, "memory_core") or not engine.memory_core:
            h._json_response(503, {"error": "记忆核心未初始化"})
            return
        mc = engine.memory_core
        parsed = urllib.parse.urlparse(h.path)
        params = urllib.parse.parse_qs(parsed.query)
        layer = (params.get("layer", [None])[0] or "").strip() or None
        keyword = (params.get("keyword", [""])[0] or "").strip() or None
        try:
            limit = min(int((params.get("limit", ["50"])[0] or "50")), 200)
        except ValueError:
            limit = 50
        try:
            offset = max(0, int((params.get("offset", ["0"])[0] or "0")))
        except ValueError:
            offset = 0
        order = (params.get("order", ["recent"])[0] or "recent").strip().lower()
        if order not in ("recent", "importance"):
            order = "recent"
        entries = mc.query(layer=layer, keyword=keyword, limit=limit,
                           offset=offset, order=order)
        total = mc.count(layer=layer, keyword=keyword) if hasattr(mc, "count") else len(entries)
        h._json_response(200, {
            "entries": [e.to_dict() for e in entries],
            "total": len(entries),      # 本页条数（兼容旧前端）
            "count": total,             # 符合条件的总条数
            "offset": offset,
            "limit": limit,
            "order": order,
        })
    except Exception as e:
        h._json_response(500, {"error": f"记忆列表查询失败: {e}"})


def _handle_memory_store(h):
    """POST /api/memory/store → 手动创建一条记忆。
    需鉴权 X-Auth-Token。
    请求 JSON: {layer, key, value[, engine='xai'][, importance=0.5]}
    返回 {"ok": true, "id": entry_id}。
    """
    try:
        length = int(h.headers.get("Content-Length", "0"))
        data = json.loads(h.rfile.read(length).decode("utf-8")) if length else {}
    except Exception:
        h._json_response(400, {"error": "需要 JSON: {layer, key, value}"})
        return
    layer = (data.get("layer") or "").strip()
    key = (data.get("key") or "").strip()
    value = (data.get("value") or "").strip()
    if not layer or not key or not value:
        h._json_response(400, {"error": "layer / key / value 都不能为空"})
        return
    engine_name = str(data.get("engine", "xai")).strip() or "xai"
    importance = float(data.get("importance", 0.5))
    try:
        engine = get_engine()
        if not engine or not hasattr(engine, "memory_core") or not engine.memory_core:
            h._json_response(503, {"error": "记忆核心未初始化"})
            return
        entry_id = engine.memory_core.store(layer=layer, key=key, value=value, engine=engine_name,
                                            importance=importance, project_id=data.get("project_id"))
        h._json_response(200, {"ok": True, "id": entry_id})
    except ValueError as e:
        h._json_response(400, {"error": str(e)})
    except Exception as e:
        h._json_response(500, {"error": f"记忆存储失败: {e}"})


def _handle_memory_update(h):
    """PUT /api/memory/<id> → 更新一条记忆的内容和重要性。
    需鉴权 X-Auth-Token。
    请求 JSON: {value?, importance?}
    返回 {"ok": true}。
    """
    # 从路径中提取 id：/api/memory/<id>
    prefix = "/api/memory/"
    path = h.path
    if not path.startswith(prefix):
        h._json_response(400, {"error": "无效路径"})
        return
    id_str = path[len(prefix):].split("?")[0].split("/")[0]
    try:
        entry_id = int(id_str)
    except ValueError:
        h._json_response(400, {"error": "id 必须为整数"})
        return
    try:
        length = int(h.headers.get("Content-Length", "0"))
        data = json.loads(h.rfile.read(length).decode("utf-8")) if length else {}
    except Exception:
        h._json_response(400, {"error": "需要 JSON: {value?, importance?}"})
        return
    value = data.get("value")
    importance = data.get("importance")
    if value is None and importance is None:
        h._json_response(400, {"error": "至少需要 value 或 importance"})
        return
    try:
        engine = get_engine()
        if not engine or not hasattr(engine, "memory_core") or not engine.memory_core:
            h._json_response(503, {"error": "记忆核心未初始化"})
            return
        engine.memory_core.update(entry_id, value=value, importance=importance)
        h._json_response(200, {"ok": True})
    except Exception as e:
        h._json_response(500, {"error": f"记忆更新失败: {e}"})


def _handle_memory_delete(h):
    """DELETE /api/memory/<id> → 删除一条记忆。
    需鉴权 X-Auth-Token。
    返回 {"ok": true, "deleted": true|false}。
    """
    prefix = "/api/memory/"
    path = h.path
    if not path.startswith(prefix):
        h._json_response(400, {"error": "无效路径"})
        return
    id_str = path[len(prefix):].split("?")[0].split("/")[0]
    try:
        entry_id = int(id_str)
    except ValueError:
        h._json_response(400, {"error": "id 必须为整数"})
        return
    try:
        engine = get_engine()
        if not engine or not hasattr(engine, "memory_core") or not engine.memory_core:
            h._json_response(503, {"error": "记忆核心未初始化"})
            return
        deleted = engine.memory_core.delete(entry_id)
        h._json_response(200, {"ok": True, "deleted": deleted})
    except Exception as e:
        h._json_response(500, {"error": f"记忆删除失败: {e}"})


def register(router) -> None:
    router.add("GET", "/api/memory/context", _handle_memory_context)
    router.add("GET", "/api/memory/list", _handle_memory_list)
    router.add("POST", "/api/memory/store", _handle_memory_store)
    router.add_prefix("PUT", "/api/memory", _handle_memory_update)
    router.add_prefix("DELETE", "/api/memory", _handle_memory_delete)
