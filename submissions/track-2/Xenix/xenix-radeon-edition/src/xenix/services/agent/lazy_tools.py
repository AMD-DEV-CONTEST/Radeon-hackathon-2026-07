from __future__ import annotations

import threading
from typing import Any

from .tool_presentations import tool_presentation_for_name


class LazyAgentToolRegistry:
    def __init__(self, **registry_kwargs: Any) -> None:
        self._registry_kwargs = registry_kwargs
        self._registry = None
        self._lock = threading.Lock()

    def list_specs(self):
        return self._resolve().list_specs()

    def tool_presentation(self, tool_name: str):
        registry = self._registry
        if registry is None:
            return tool_presentation_for_name(tool_name)
        return registry.tool_presentation(tool_name)

    def execute(self, tool_name: str, arguments: dict[str, Any], context):
        return self._resolve().execute(tool_name, arguments, context)

    def register_with_llm(self, registry) -> None:
        self._resolve().register_with_llm(registry)

    def _resolve(self):
        registry = self._registry
        if registry is not None:
            return registry
        with self._lock:
            registry = self._registry
            if registry is None:
                from .tools import AgentToolRegistry

                registry = AgentToolRegistry(**self._registry_kwargs)
                self._registry = registry
            return registry
