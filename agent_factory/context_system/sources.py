from __future__ import annotations

from typing import Any, Protocol

from agent_factory.context_system.token_estimation import estimate_text_tokens
from agent_factory.context_system.schema import ContextCandidate, ContextQuery


class ContextSource(Protocol):
    source_id: str

    def retrieve(self, *, query: ContextQuery, runtime_context: "ContextSourceRuntime") -> list[ContextCandidate]:
        ...


class ContextSourceRuntime:
    def __init__(
        self,
        *,
        state: Any = None,
        messages: list[Any] | None = None,
        services: Any = None,
        resources: dict[str, Any] | None = None,
        factory_values: dict[str, Any] | None = None,
    ) -> None:
        self.state = state
        self.messages = list(messages or [])
        self.services = services
        self.resources = dict(resources or {})
        self.factory_values = dict(factory_values or {})


class CrossSessionMemorySource:
    source_id = "cross_session_memory"

    def retrieve(self, *, query: ContextQuery, runtime_context: ContextSourceRuntime) -> list[ContextCandidate]:
        memory_system = getattr(runtime_context.services, "memory_system", None) if runtime_context.services else None
        if memory_system is None or not getattr(getattr(memory_system, "config", None), "enabled", False):
            return []
        workspace_id = str(
            getattr(getattr(runtime_context.state, "run", None), "workspace_id", None) or ""
        ).strip()
        retrieve_scoped = getattr(memory_system, "retrieve_scoped_context", None)
        pack = (
            retrieve_scoped(query=query.text, workspace_id=workspace_id or None)
            if callable(retrieve_scoped)
            else memory_system.retrieve_context(query=query.text)
        )
        candidates: list[ContextCandidate] = []
        for item in pack.items:
            candidates.append(
                ContextCandidate(
                    candidate_id=f"memory:{':'.join(item.namespace)}:{item.memory_id}",
                    source_id=self.source_id,
                    kind="memory",
                    content=item.content,
                    score=item.score,
                    token_estimate=estimate_text_tokens(item.content),
                    metadata={
                        "memory_id": item.memory_id,
                        "memory_type": item.memory_type,
                        "kind": item.kind,
                        "source_scope": item.source_scope,
                        "namespace": list(item.namespace),
                    },
                )
            )
        return candidates


def default_context_sources() -> dict[str, ContextSource]:
    return {
        "cross_session_memory": CrossSessionMemorySource(),
    }
