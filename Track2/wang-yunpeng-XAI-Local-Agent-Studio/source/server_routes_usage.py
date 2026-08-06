"""XAI 后端路由：Token 用量统计（usage_log）。

GET /api/usage/stats  — 聚合统计（总量/今日/按模型/按日/按 source，云端模型带 ¥ 预估）
GET /api/usage/recent — 最近 N 条明细（?limit=50）
"""
from __future__ import annotations
from server_xai import *   # 共享单例 / 辅助（惰性导入，安全）


def _handle_usage_stats(h):
    """GET /api/usage/stats — Token 用量聚合统计。"""
    try:
        from core.usage_tracker import get_stats
        h._json_response(200, get_stats())
    except Exception as e:
        h._json_response(500, {"error": f"获取用量统计失败: {e}"})


def _handle_usage_recent(h):
    """GET /api/usage/recent?limit=50 — 最近用量明细。"""
    try:
        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(h.path).query)
        limit = int((qs.get("limit") or ["50"])[0])
        from core.usage_tracker import get_recent
        h._json_response(200, {"items": get_recent(limit)})
    except Exception as e:
        h._json_response(500, {"error": f"获取用量明细失败: {e}"})


def register(router) -> None:
    router.add("GET", "/api/usage/stats", _handle_usage_stats)
    router.add("GET", "/api/usage/recent", _handle_usage_recent)
