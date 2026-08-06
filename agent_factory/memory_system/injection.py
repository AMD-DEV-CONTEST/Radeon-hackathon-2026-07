from __future__ import annotations

from time import perf_counter
from typing import Any

from pydantic import BaseModel, ConfigDict

from agent_factory.memory_system.config import MemorySystemConfig
from agent_factory.memory_system.namespace import (
    agent_memory_namespace,
    factory_memory_namespace,
)
from agent_factory.memory_system.retrieval import retrieve_memory_context, retrieve_scoped_memory_context
from agent_factory.memory_system.schema import MemoryContextPack, MemoryInjectionReport
from agent_factory.memory_system.scopes import MemoryScopeContext, local_memory_user_id


class MemorySystemRuntime(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    config: MemorySystemConfig
    store: object | None = None
    scope: str = "agent"
    namespace: tuple[str, ...] = ()
    agent_id: str | None = None
    user_id: str | None = None
    writer: object | None = None

    def retrieve_context(
        self,
        *,
        query: str,
        namespace: tuple[str, ...] | None = None,
    ) -> MemoryContextPack:
        return retrieve_memory_context(
            store=self.store,
            namespace=namespace or self.namespace,
            query=query,
            config=self.config,
        )

    def retrieve_scoped_context(
        self,
        *,
        query: str,
        workspace_id: str | None = None,
    ) -> MemoryContextPack:
        if not self.agent_id or not self.user_id:
            return self.retrieve_context(query=query)
        context = MemoryScopeContext(
            agent_id=self.agent_id,
            user_id=self.user_id,
            workspace_id=workspace_id,
        )
        return retrieve_scoped_memory_context(
            store=self.store,
            sources=context.retrieval_sources(),
            query=query,
            config=self.config,
        )


def inject_runtime_cross_session_memory(
    *,
    state: Any,
    runtime: MemorySystemRuntime | None,
) -> tuple[Any, MemoryInjectionReport]:
    started = perf_counter()
    if runtime is None or not runtime.config.enabled or not runtime.config.injection_enabled:
        return (
            state,
            MemoryInjectionReport(status="skipped", error="memory injection disabled"),
        )
    query = _runtime_memory_query(state)
    try:
        workspace_id = str(getattr(getattr(state, "run", None), "workspace_id", None) or "").strip()
        pack = runtime.retrieve_scoped_context(query=query, workspace_id=workspace_id or None)
        updated = state.model_copy(deep=True)
        updated.context.model_context = {
            **updated.context.model_context,
            "cross_session_memory": pack.model_dump(mode="json"),
        }
        updated.context.assembly_log.append("system_cross_session_memory_inject")
        return (
            updated,
            MemoryInjectionReport(
                status="injected",
                namespace=pack.namespace,
                namespaces=[tuple(item) for item in pack.report.get("namespaces", [])],
                item_count=len(pack.items),
                token_estimate=pack.token_estimate,
                min_score=runtime.config.ranking.min_score,
                duration_ms=int((perf_counter() - started) * 1000),
            ),
        )
    except Exception as exc:
        return (
            state,
            MemoryInjectionReport(
                status="failed",
                namespace=runtime.namespace,
                error=f"{type(exc).__name__}: {exc}",
                duration_ms=int((perf_counter() - started) * 1000),
            ),
        )


def inject_factory_cross_session_memory(
    *,
    values: dict[str, Any],
    runtime: MemorySystemRuntime | None,
    stage_id: str,
) -> tuple[dict[str, Any], MemoryInjectionReport]:
    if runtime is None or not runtime.config.enabled or not runtime.config.injection_enabled:
        return values, MemoryInjectionReport(status="skipped", error="memory injection disabled")
    query = _factory_memory_query(values=values, stage_id=stage_id)
    started = perf_counter()
    try:
        pack = runtime.retrieve_context(query=query)
        updated = {**values, "cross_session_memory": pack.model_dump(mode="json")}
        return (
            updated,
            MemoryInjectionReport(
                status="injected",
                namespace=pack.namespace,
                item_count=len(pack.items),
                token_estimate=pack.token_estimate,
                min_score=runtime.config.ranking.min_score,
                duration_ms=int((perf_counter() - started) * 1000),
            ),
        )
    except Exception as exc:
        return (
            values,
            MemoryInjectionReport(
                status="failed",
                namespace=runtime.namespace,
                error=f"{type(exc).__name__}: {exc}",
                duration_ms=int((perf_counter() - started) * 1000),
            ),
        )


def default_agent_runtime(
    *,
    agent_id: str,
    config: MemorySystemConfig,
    store: object | None,
    user_id: str | None = None,
) -> MemorySystemRuntime:
    return MemorySystemRuntime(
        config=config,
        store=store,
        scope="agent",
        namespace=agent_memory_namespace(agent_id),
        agent_id=agent_id,
        user_id=user_id or local_memory_user_id(),
    )


def default_factory_runtime(*, project_id: str, config: MemorySystemConfig, store: object | None) -> MemorySystemRuntime:
    return MemorySystemRuntime(config=config, store=store, scope="factory", namespace=factory_memory_namespace(project_id))


def _runtime_memory_query(state: RuntimeState) -> str:
    parts = [
        state.conversation.current_user_input or "",
        state.conversation.assistant_draft or "",
        state.conversation.final_answer or "",
    ]
    return "\n".join(part for part in parts if part.strip())


def _factory_memory_query(*, values: dict[str, Any], stage_id: str) -> str:
    chunks = [stage_id]
    for key in ("user_input", "requirement", "requirement_brief", "refined_requirement", "messages"):
        value = values.get(key)
        if value:
            chunks.append(str(value))
    return "\n".join(chunks)
