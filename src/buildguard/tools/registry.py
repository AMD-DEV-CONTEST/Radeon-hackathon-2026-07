"""Static tool registration and selective discovery."""

from __future__ import annotations

from typing import Any

from buildguard.tools.base import RegisteredTool, ToolDefinition, ToolHandler


class ToolRegistry:
    """Registry does not accept import paths, source code, or dynamic evaluation."""

    def __init__(self) -> None:
        self._tools: dict[str, RegisteredTool] = {}
        self._enabled: set[str] = set()

    def register(self, definition: ToolDefinition, handler: ToolHandler) -> None:
        if definition.name in self._tools:
            raise ValueError(f"Tool name already registered: {definition.name}")
        self._tools[definition.name] = RegisteredTool(definition, handler)
        self._enabled.add(definition.name)

    def get(self, name: str) -> RegisteredTool:
        if name not in self._tools:
            raise KeyError(f"Unknown tool: {name}")
        if name not in self._enabled:
            raise PermissionError(f"Tool is disabled: {name}")
        return self._tools[name]

    def enable(self, name: str) -> None:
        if name not in self._tools:
            raise KeyError(f"Unknown tool: {name}")
        self._enabled.add(name)

    def disable(self, name: str) -> None:
        if name not in self._tools:
            raise KeyError(f"Unknown tool: {name}")
        self._enabled.discard(name)

    def candidates(self, intent: str) -> list[ToolDefinition]:
        normalized = intent.lower()
        return [
            tool.definition
            for name, tool in self._tools.items()
            if name in self._enabled
            and (
                tool.definition.category.lower() == normalized
                or normalized in tool.definition.category.lower()
            )
        ]

    def export_metadata(self, intent: str | None = None) -> list[dict[str, Any]]:
        definitions = (
            self.candidates(intent)
            if intent is not None
            else [
                tool.definition
                for name, tool in self._tools.items()
                if name in self._enabled
            ]
        )
        return [definition.metadata() for definition in definitions]

