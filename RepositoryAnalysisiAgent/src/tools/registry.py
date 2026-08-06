"""Tool registry: schemas, dispatch, and OpenAI-compatible tool definitions.

The registry holds all available tools with their parameter schemas,
and dispatches incoming tool calls to the appropriate handler functions.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Awaitable

from ..backend import ToolDef

logger = logging.getLogger(__name__)

ToolHandler = Callable[..., Awaitable[str]]


@dataclass
class RegisteredTool:
    definition: ToolDef
    handler: ToolHandler


class ToolRegistry:
    """Central registry for all Agent tools."""

    def __init__(self) -> None:
        self._tools: dict[str, RegisteredTool] = {}

    def register(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
        handler: ToolHandler,
    ) -> None:
        """Register a tool with its schema and handler."""
        tool_def = ToolDef(
            name=name,
            description=description,
            parameters=parameters,
        )
        self._tools[name] = RegisteredTool(definition=tool_def, handler=handler)
        logger.debug("Registered tool: %s", name)

    def get_definitions(self) -> list[ToolDef]:
        """Return all tool definitions for the LLM API."""
        return [rt.definition for rt in self._tools.values()]

    def get_definition(self, name: str) -> ToolDef | None:
        rt = self._tools.get(name)
        return rt.definition if rt else None

    async def execute(self, name: str, arguments: dict[str, Any]) -> str:
        """Execute a tool by name with the given arguments."""
        rt = self._tools.get(name)
        if rt is None:
            available = ", ".join(self._tools.keys())
            return f"Error: unknown tool '{name}'. Available: {available}"
        try:
            result = await rt.handler(**arguments)
            return result
        except Exception as e:
            logger.error("Tool '%s' failed: %s", name, e, exc_info=True)
            return f"Error executing {name}: {e}"

    def list_tools(self) -> list[str]:
        return list(self._tools.keys())

    def has_tool(self, name: str) -> bool:
        return name in self._tools
