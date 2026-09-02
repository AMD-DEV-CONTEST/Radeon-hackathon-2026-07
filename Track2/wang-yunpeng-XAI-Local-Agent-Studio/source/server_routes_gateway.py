"""XAI 执行网关状态路由（诚实标注模拟/真实执行能力）。

对应审计问题 ①：OpenClaw 执行网关（桌面/浏览器/Office/钉钉·飞书等）默认是 Stub 演示桩，
前端必须如实标注「模拟模式」，避免把演示误认为真实能力。
"""
from __future__ import annotations

from server_xai import *   # 共享单例 / 辅助（惰性导入，安全）
from server_runtime import get_engine
from core.openclaw_gateway import default_gateway


def _handle_gateway_status(h):
    """GET /api/gateway/status → 执行网关真实状态（按能力细分）。"""
    gw = default_gateway()
    eng = get_engine()
    oc = eng.openclaw if eng else None

    # 网关层能力状态
    cap_status = gw.cap_status()

    # 引擎层真实可用工具（OpenClawAdapter 本地工具，无需 openclaw CLI）
    real_tools: list[str] = []
    if oc and hasattr(oc, '_tools'):
        real_tools = sorted(oc._tools.keys())

    # shell/文件真实时映射为 desktop 能力（对应开源 Agent 的"本地执行"概念）
    if any(t in real_tools for t in ("exec", "file_read", "file_write", "list_dir")):
        cap_status["shell"] = "real"
    if "browser_open" in real_tools:
        cap_status["browser"] = "real"  # webbrowser.open 真实（非 headless 自动化）

    # 真实执行覆盖的能力清单
    real_caps = [k for k, v in cap_status.items() if v == "real"]
    simulated = len(real_caps) == 0

    h._json_response(200, {
        "ok": True,
        "simulated": simulated,
        "simulated_capabilities": gw.simulated_capabilities(),
        "capabilities": gw.capabilities() + (["shell"] if "shell" in cap_status else []),
        "real_tools": real_tools,
        "capability_status": cap_status,
        "note": (
            f"shell/文件读写/目录浏览已通过 OpenClawAdapter 本地工具真实接入（{len(real_tools)} 个工具），"
            "其余能力（浏览器自动化/文档处理/办公推送/MCP/调度）仍为模拟桩。"
        ),
    })


def register(router) -> None:
    router.add("GET", "/api/gateway/status", _handle_gateway_status)
