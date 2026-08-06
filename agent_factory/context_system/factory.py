from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent_factory.context_system.events import ContextEventSink
from agent_factory.context_system.runtime import ContextSystemRuntime
from agent_factory.memory_system.factory import factory_memory_runtime


_FACTORY_CONTEXT_RUNTIME: ContextSystemRuntime | None = None


@dataclass(slots=True)
class FactoryContextServices:
    memory_system: Any | None = None
    tool_registry: Any | None = None
    scheduler_runtime: Any | None = None
    context_event_sink: ContextEventSink | None = None


def inject_factory_prompt_context(
    *,
    stage_id: str,
    values: dict[str, Any],
    context_event_sink: ContextEventSink | None = None,
) -> dict[str, Any]:
    runtime = _factory_context_runtime()
    try:
        memory_runtime = factory_memory_runtime()
    except Exception:
        memory_runtime = None
    return runtime.prepare_factory_values(
        stage_id=stage_id,
        values=values,
        services=FactoryContextServices(memory_system=memory_runtime, context_event_sink=context_event_sink),
    )


def _factory_context_runtime() -> ContextSystemRuntime:
    global _FACTORY_CONTEXT_RUNTIME
    if _FACTORY_CONTEXT_RUNTIME is None:
        _FACTORY_CONTEXT_RUNTIME = ContextSystemRuntime()
    return _FACTORY_CONTEXT_RUNTIME
