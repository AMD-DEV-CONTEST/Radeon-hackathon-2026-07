from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from langchain_core.tools import BaseTool

from agent_factory.runtime_kernel.types import ToolExecutionResult


class ToolRegistryAdapter(Protocol):
    def list_tool_ids(self) -> list[str]:
        ...

    def system_tool_ids(self) -> list[str]:
        ...

    def model_tools(self, tool_ids: list[str] | set[str] | None = None) -> list[BaseTool]:
        ...

    def execute(self, tool_id: str, arguments: dict[str, Any], *, state: Any) -> ToolExecutionResult:
        ...


class InMemoryToolRegistry:
    def __init__(
        self,
        tools: dict[str, Callable[[dict[str, Any], Any], ToolExecutionResult | dict[str, Any]]] | None = None,
        model_tools: dict[str, BaseTool] | None = None,
        system_tool_ids: list[str] | set[str] | None = None,
    ) -> None:
        self._tools = dict(tools or {})
        self._model_tools = dict(model_tools or {})
        self._system_tool_ids = {
            tool_id
            for tool_id in (system_tool_ids or [])
            if tool_id in self._model_tools
        }

    def list_tool_ids(self) -> list[str]:
        return sorted(self._tools)

    def system_tool_ids(self) -> list[str]:
        return sorted(self._system_tool_ids)

    def model_tools(self, tool_ids: list[str] | set[str] | None = None) -> list[BaseTool]:
        if tool_ids is None:
            return [tool for _tool_id, tool in sorted(self._model_tools.items())]
        selected = set(tool_ids)
        if not selected:
            return []
        return [
            tool
            for tool_id, tool in sorted(self._model_tools.items())
            if tool_id in selected
        ]

    def execute(self, tool_id: str, arguments: dict[str, Any], *, state: Any) -> ToolExecutionResult:
        if tool_id not in self._tools:
            return ToolExecutionResult(
                status="failed",
                error=f"Unknown tool: {tool_id}",
                observation_summary=f"Unknown tool: {tool_id}",
            )
        result = self._tools[tool_id](arguments, state)
        if isinstance(result, ToolExecutionResult):
            return result
        if not isinstance(result, dict):
            return ToolExecutionResult(
                status="failed",
                error="Tool output must be a mapping.",
                observation_summary="Tool output must be a mapping.",
            )
        status = str(result.get("status") or "completed")
        if status not in {"completed", "failed", "interrupted"}:
            status = "completed"
        return ToolExecutionResult(
            status=status,  # type: ignore[arg-type]
            output=result,
            error=result.get("error"),
            interrupt_type=result.get("interrupt_type"),
            observation_summary=result.get("observation_summary"),
        )
