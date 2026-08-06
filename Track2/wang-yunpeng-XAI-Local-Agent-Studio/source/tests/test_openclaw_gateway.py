"""openclaw_gateway 模块测试（无网络）。"""

from core.openclaw_gateway import (
    Gateway,
    GatewayCapability,
    ActionResult,
    StubDesktopAdapter,
    StubBrowserAdapter,
    StubDocAdapter,
    StubScheduleAdapter,
    StubMCPAdapter,
    StubOfficeAdapter,
    default_gateway,
)


def test_stub_adapters_ok():
    assert StubDesktopAdapter().act("open").ok is True
    assert StubBrowserAdapter().browse("http://x").ok is True
    assert StubBrowserAdapter().screenshot().ok is True
    assert StubDocAdapter().process("a.pdf", "convert").ok is True
    assert StubScheduleAdapter().add_job("* * * * *", "t").ok is True
    assert StubScheduleAdapter().list_jobs().ok is True
    assert StubMCPAdapter().call_tool("s", "t", {}).ok is True
    assert StubOfficeAdapter().send("feishu", "u", "hi").ok is True


def test_route_dispatches_all():
    g = default_gateway()
    assert g.route(GatewayCapability.DESKTOP, "act", command="x").data["simulated"] is True
    assert g.route(GatewayCapability.BROWSER, "browse", url="u").data["url"] == "u"
    assert g.route(GatewayCapability.BROWSER, "screenshot").ok is True
    assert g.route(GatewayCapability.DOC, "process", path="p", op="summarize").data["op"] == "summarize"
    assert g.route(GatewayCapability.SCHEDULE, "add_job", cron="0 0 * * *", task="t").ok is True
    assert g.route(GatewayCapability.SCHEDULE, "list_jobs").ok is True
    assert g.route(GatewayCapability.MCP, "call_tool", server="s", tool="t", args={}).ok is True
    assert g.route(GatewayCapability.OFFICE, "send", platform="dingtalk", to="u", content="c").ok is True


def test_capabilities_all_six():
    g = default_gateway()
    caps = g.capabilities()
    assert caps == ["desktop", "browser", "doc", "schedule", "mcp", "office"]


def test_register_swaps_adapter():
    class TrackingDesktop(StubDesktopAdapter):
        def act(self, command, **kw):
            r = super().act(command, **kw)
            r.data["tracked"] = True
            return r

    g = default_gateway()
    g.register(GatewayCapability.DESKTOP, TrackingDesktop())
    res = g.route(GatewayCapability.DESKTOP, "act", command="y")
    assert res.data["tracked"] is True


def test_unknown_action_returns_false():
    g = default_gateway()
    res = g.route(GatewayCapability.DESKTOP, "no_such_action")
    assert res.ok is False
    assert "unknown action" in res.msg


def test_default_gateway_is_stubbed():
    g = default_gateway()
    assert isinstance(g.desktop, StubDesktopAdapter)
    assert isinstance(g.browser, StubBrowserAdapter)
    assert isinstance(g.doc, StubDocAdapter)
    assert isinstance(g.schedule, StubScheduleAdapter)
    assert isinstance(g.mcp, StubMCPAdapter)
    assert isinstance(g.office, StubOfficeAdapter)
