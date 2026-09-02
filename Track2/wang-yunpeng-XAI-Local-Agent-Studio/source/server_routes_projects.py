"""XAI 后端路由处理器（S5-1 自动迁移，按领域拆分）。
方法体原属 server_xai.XAIHandler，统一签名 fn(h)，h 即 XAIHandler 实例。
共享单例经 server_xai import *（惰性，bootstrap 在文件末尾，循环导入安全）+ server_runtime。
"""
from __future__ import annotations
from server_xai import *   # 共享单例 / 辅助（惰性导入，安全）
from server_runtime import get_engine, get_knowledge_adapter, _CAPABILITIES

def _handle_project_create(h):
    """POST /api/projects — 创建新项目（返回信息并自动激活，记忆立即按新项目隔离）。"""
    try:
        length = int(h.headers.get("Content-Length", 0))
        body = json.loads(h.rfile.read(length) or b"{}") if length else {}
        name = (body.get("name") or "").strip()
        if not name:
            h._json_response(400, {"error": "项目名不能为空"})
            return
        pm = get_engine().project_manager
        proj = pm.create(
            name,
            description=body.get("description", ""),
            workspace=body.get("workspace", ""),
            instructions=body.get("instructions", ""),
            budget=int(body.get("budget", 0) or 0),
        )
        pm.activate(proj.id)
        h._json_response(200, {
            "ok": True,
            "project": {"id": proj.id, "name": proj.name, "description": proj.description, "workspace": proj.workspace},
        })
    except Exception as e:
        h._json_response(500, {"error": f"创建项目失败: {e}"})

def register(router) -> None:
    router.add("POST", "/api/projects", _handle_project_create)
