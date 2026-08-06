from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from agent_factory.runtime_kernel.wrappers.system_memory import (
    MEMORY_RETRIEVE_SYSTEM_WRAPPER_ID,
    SYSTEM_MEMORY_RETRIEVE_WRAPPER,
)
from agent_factory.runtime_kernel.wrappers.system_context import (
    CONTEXT_PREPARE_SYSTEM_WRAPPER_ID,
    SYSTEM_CONTEXT_PREPARE_WRAPPER,
)
from agent_factory.runtime_kernel.wrappers.system_knowledge import (
    SYSTEM_KNOWLEDGE_GUIDANCE_WRAPPER,
)
from agent_factory.runtime_kernel.wrappers.system_render import (
    RENDER_NODE_SYSTEM_WRAPPER_ID,
    SYSTEM_RENDER_NODE_WRAPPER,
)


DEFAULT_RUNTIME_SYSTEM_WRAPPER_IDS = (
    RENDER_NODE_SYSTEM_WRAPPER_ID,
    CONTEXT_PREPARE_SYSTEM_WRAPPER_ID,
)


class SystemWrapperRegistryError(ValueError):
    pass


class SystemWrapperRegistry:
    def __init__(self, wrappers: Iterable[Any]) -> None:
        self._wrappers = {}
        for wrapper in wrappers:
            wrapper_id = str(getattr(wrapper, "wrapper_id", "")).strip()
            if not wrapper_id:
                raise SystemWrapperRegistryError("system wrapper must define wrapper_id")
            if wrapper_id in self._wrappers:
                raise SystemWrapperRegistryError(f"duplicate system wrapper id: {wrapper_id}")
            self._wrappers[wrapper_id] = wrapper

    def resolve_many(self, wrapper_ids: Iterable[str]) -> list[Any]:
        wrappers = []
        seen: set[str] = set()
        for wrapper_id in wrapper_ids:
            if wrapper_id in seen:
                raise SystemWrapperRegistryError(f"duplicate system wrapper id: {wrapper_id}")
            seen.add(wrapper_id)
            try:
                wrappers.append(self._wrappers[wrapper_id])
            except KeyError as exc:
                raise SystemWrapperRegistryError(f"unknown system wrapper id: {wrapper_id}") from exc
        return wrappers


DEFAULT_SYSTEM_WRAPPER_REGISTRY = SystemWrapperRegistry(
    [
        SYSTEM_RENDER_NODE_WRAPPER,
        SYSTEM_MEMORY_RETRIEVE_WRAPPER,
        SYSTEM_CONTEXT_PREPARE_WRAPPER,
        SYSTEM_KNOWLEDGE_GUIDANCE_WRAPPER,
    ]
)
