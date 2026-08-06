"""XAI 后端路由处理器（S5-1 自动迁移，按领域拆分）。
方法体原属 server_xai.XAIHandler，统一签名 fn(h)，h 即 XAIHandler 实例。
共享单例经 server_xai import *（惰性，bootstrap 在文件末尾，循环导入安全）+ server_runtime。
"""
from __future__ import annotations
from server_xai import *   # 共享单例 / 辅助（惰性导入，安全）
from server_runtime import get_engine, get_knowledge_adapter, _CAPABILITIES

def _handle_sessions_list(h):
    """GET /api/sessions → 列出所有会话"""
    try:
        eng = get_engine()
        sessions = eng._sessions.list_sessions() if hasattr(eng, "_sessions") else []
        h._json_response(200, {"sessions": sessions})
    except Exception as e:
        h._json_response(500, {"error": f"读取会话列表失败: {e}"})

def register(router) -> None:
    router.add("GET", "/api/sessions", _handle_sessions_list)
