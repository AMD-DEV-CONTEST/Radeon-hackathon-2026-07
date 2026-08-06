"""XAI 执行网关抽象层（参考 OpenClaw / 龙虾）。

设计要点（环境无关）：所有对外部世界的能力都通过 `Gateway` 统一路由，上层逻辑
只依赖抽象适配器接口，不绑定任何真实桌面 / 浏览器 / 办公生态。真实落地时替换为
对应实现即可；测试时用 `Stub*` 适配器注入确定性输出，无需联网或真实桌面控制即可
验证整张蓝图的路由与编排逻辑。

这是"执行能力可替换 / 热插拔"的工程落点 —— 与模型可替换的设计一致。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
import os


class GatewayCapability(Enum):
    DESKTOP = "desktop"
    BROWSER = "browser"
    DOC = "doc"
    SCHEDULE = "schedule"
    MCP = "mcp"
    OFFICE = "office"


@dataclass
class ActionResult:
    ok: bool
    capability: str
    data: dict
    msg: str


# --------------------------------------------------------------------------- #
# 抽象适配器：每个外部能力一个接口
# --------------------------------------------------------------------------- #
class DesktopAdapter(ABC):
    """桌面控制能力。"""

    @abstractmethod
    def act(self, command: str, **kw) -> ActionResult:
        raise NotImplementedError


class BrowserAdapter(ABC):
    """浏览器自动化能力。"""

    @abstractmethod
    def browse(self, url: str, **kw) -> ActionResult:
        raise NotImplementedError

    @abstractmethod
    def screenshot(self, **kw) -> ActionResult:
        raise NotImplementedError


class DocAdapter(ABC):
    """批量文档处理能力。"""

    @abstractmethod
    def process(self, path: str, op: str, **kw) -> ActionResult:
        raise NotImplementedError


class ScheduleAdapter(ABC):
    """定时任务能力。"""

    @abstractmethod
    def add_job(self, cron: str, task: str) -> ActionResult:
        raise NotImplementedError

    @abstractmethod
    def list_jobs(self) -> ActionResult:
        raise NotImplementedError


class MCPAdapter(ABC):
    """MCP 跨工具通信能力。"""

    @abstractmethod
    def call_tool(self, server: str, tool: str, args: dict) -> ActionResult:
        raise NotImplementedError


class OfficeAdapter(ABC):
    """办公生态兼容（企业微信 / 钉钉 / 飞书）。"""

    @abstractmethod
    def send(self, platform: str, to: str, content: str) -> ActionResult:
        raise NotImplementedError


# --------------------------------------------------------------------------- #
# STUB 适配器：确定性、无网络、无真实桌面控制
# --------------------------------------------------------------------------- #
class StubDesktopAdapter(DesktopAdapter):
    def act(self, command: str, **kw) -> ActionResult:
        return ActionResult(
            ok=True,
            capability=GatewayCapability.DESKTOP.value,
            data={"command": command, "simulated": True},
            msg=f"simulated desktop act: {command}",
        )


class StubBrowserAdapter(BrowserAdapter):
    def browse(self, url: str, **kw) -> ActionResult:
        return ActionResult(
            ok=True,
            capability=GatewayCapability.BROWSER.value,
            data={"url": url, "simulated": True},
            msg=f"simulated browse: {url}",
        )

    def screenshot(self, **kw) -> ActionResult:
        return ActionResult(
            ok=True,
            capability=GatewayCapability.BROWSER.value,
            data={"path": kw.get("path", "<memory>"), "simulated": True},
            msg="simulated screenshot",
        )


class StubDocAdapter(DocAdapter):
    def process(self, path: str, op: str, **kw) -> ActionResult:
        return ActionResult(
            ok=True,
            capability=GatewayCapability.DOC.value,
            data={"path": path, "op": op, "simulated": True},
            msg=f"simulated doc {op}: {path}",
        )


class StubScheduleAdapter(ScheduleAdapter):
    def add_job(self, cron: str, task: str) -> ActionResult:
        return ActionResult(
            ok=True,
            capability=GatewayCapability.SCHEDULE.value,
            data={"cron": cron, "task": task, "simulated": True},
            msg=f"simulated add_job: {cron} -> {task}",
        )

    def list_jobs(self) -> ActionResult:
        return ActionResult(
            ok=True,
            capability=GatewayCapability.SCHEDULE.value,
            data={"jobs": [], "simulated": True},
            msg="simulated list_jobs",
        )


class StubMCPAdapter(MCPAdapter):
    def call_tool(self, server: str, tool: str, args: dict) -> ActionResult:
        return ActionResult(
            ok=True,
            capability=GatewayCapability.MCP.value,
            data={"server": server, "tool": tool, "args": args, "simulated": True},
            msg=f"simulated mcp call_tool: {server}/{tool}",
        )


class StubOfficeAdapter(OfficeAdapter):
    def send(self, platform: str, to: str, content: str) -> ActionResult:
        return ActionResult(
            ok=True,
            capability=GatewayCapability.OFFICE.value,
            data={"platform": platform, "to": to, "simulated": True},
            msg=f"simulated office send to {platform}/{to}",
        )


# --------------------------------------------------------------------------- #
# 统一执行网关
# --------------------------------------------------------------------------- #
class Gateway:
    """统一执行网关：按能力路由到对应适配器。"""

    def __init__(
        self,
        desktop: DesktopAdapter | None = None,
        browser: BrowserAdapter | None = None,
        doc: DocAdapter | None = None,
        schedule: ScheduleAdapter | None = None,
        mcp: MCPAdapter | None = None,
        office: OfficeAdapter | None = None,
    ):
        self.desktop = desktop or StubDesktopAdapter()
        self.browser = browser or StubBrowserAdapter()
        self.doc = doc or StubDocAdapter()
        self.schedule = schedule or StubScheduleAdapter()
        self.mcp = mcp or StubMCPAdapter()
        self.office = office or StubOfficeAdapter()

    def route(self, capability: GatewayCapability, action: str, **kwargs) -> ActionResult:
        adapter = {
            GatewayCapability.DESKTOP: self.desktop,
            GatewayCapability.BROWSER: self.browser,
            GatewayCapability.DOC: self.doc,
            GatewayCapability.SCHEDULE: self.schedule,
            GatewayCapability.MCP: self.mcp,
            GatewayCapability.OFFICE: self.office,
        }[capability]

        method = getattr(adapter, action, None)
        if method is None or not callable(method):
            return ActionResult(
                ok=False,
                capability=capability.value,
                data={},
                msg=f"unknown action '{action}' for capability '{capability.value}'",
            )
        return method(**kwargs)

    def capabilities(self) -> list[str]:
        return [c.value for c in GatewayCapability]

    _STUB_TYPES = (StubDesktopAdapter, StubBrowserAdapter, StubDocAdapter,
                   StubScheduleAdapter, StubMCPAdapter, StubOfficeAdapter)

    _CAP_ATTR: dict[GatewayCapability, str] = {
        GatewayCapability.DESKTOP: "desktop",
        GatewayCapability.BROWSER: "browser",
        GatewayCapability.DOC: "doc",
        GatewayCapability.SCHEDULE: "schedule",
        GatewayCapability.MCP: "mcp",
        GatewayCapability.OFFICE: "office",
    }

    def is_simulated(self) -> bool:
        """返回 True 表示全部能力仍为 Stub（无真实适配器接入）。"""
        return len(self.simulated_capabilities()) == len(GatewayCapability)

    def simulated_capabilities(self) -> list[str]:
        """列出当前仍处于模拟（Stub）状态的执行能力（按能力细分）。

        真实接入后对应能力从列表移除；前端据此如实标注，不把演示桩当真实能力。
        """
        return [c.value for c in GatewayCapability
                if isinstance(getattr(self, self._CAP_ATTR[c]), self._STUB_TYPES)]

    def cap_status(self) -> dict[str, str]:
        """按能力细分的真实/模拟状态 dict（供 /api/gateway/status 诚实返回）。"""
        return {
            c.value: (
                "real" if not isinstance(getattr(self, self._CAP_ATTR[c]), self._STUB_TYPES)
                else "simulated"
            )
            for c in GatewayCapability
        }

    def register(self, capability: GatewayCapability, adapter) -> None:
        mapping = {
            GatewayCapability.DESKTOP: "desktop",
            GatewayCapability.BROWSER: "browser",
            GatewayCapability.DOC: "doc",
            GatewayCapability.SCHEDULE: "schedule",
            GatewayCapability.MCP: "mcp",
            GatewayCapability.OFFICE: "office",
        }
        setattr(self, mapping[capability], adapter)


def default_gateway() -> Gateway:
    """构建全部使用 Stub 的默认网关（无网络、无真实控制）。"""
    return Gateway()
