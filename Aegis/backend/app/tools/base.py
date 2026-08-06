"""
Tool framework base classes.

Every tool an agent can call implements this interface. The registry pattern
means agents don't import concrete tools directly — they ask the registry for
"the tools this agent is permitted to use", which is also the RBAC enforcement
point for remediation-class tools (Phase 8 -> ties into Phase 4 RBAC).
"""
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, Optional

from app.core.exceptions import ToolExecutionError
from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class ToolResult:
    tool_name: str
    success: bool
    output: Any
    duration_ms: float
    error: Optional[str] = None


class BaseTool(ABC):
    name: str = "base_tool"
    description: str = "Base tool — override in subclasses."
    requires_approval: bool = False  # remediation-class tools set this True

    @abstractmethod
    async def _execute(self, **kwargs) -> Any:
        ...

    async def run(self, **kwargs) -> ToolResult:
        start = time.perf_counter()
        try:
            output = await self._execute(**kwargs)
            duration_ms = (time.perf_counter() - start) * 1000
            logger.info("tool.executed", tool=self.name, duration_ms=round(duration_ms, 2))
            return ToolResult(tool_name=self.name, success=True, output=output, duration_ms=duration_ms)
        except Exception as exc:  # noqa: BLE001 — tool failures are data, not crashes
            duration_ms = (time.perf_counter() - start) * 1000
            logger.warning("tool.failed", tool=self.name, error=str(exc))
            return ToolResult(
                tool_name=self.name, success=False, output=None, duration_ms=duration_ms, error=str(exc)
            )


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: Dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> BaseTool:
        if name not in self._tools:
            raise ToolExecutionError(f"Unknown tool: {name}")
        return self._tools[name]

    def for_agent(self, tool_names: list[str]) -> list[BaseTool]:
        return [self.get(name) for name in tool_names]

    def all_tools(self) -> list[BaseTool]:
        return list(self._tools.values())
