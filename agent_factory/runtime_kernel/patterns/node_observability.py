from __future__ import annotations

from typing import Any

from agent_factory.runtime_kernel.bindings import RuntimeServices
from agent_factory.runtime_kernel.nodes.base import NodeExecutionContext
from agent_factory.runtime_kernel.observability.schema import RuntimeObservationEvent
from agent_factory.runtime_kernel.state import RuntimeState


def emit_state_event(
    services: RuntimeServices,
    state: RuntimeState,
    event_type: str,
    *,
    node_id: str | None = None,
    message: str | None = None,
    payload: dict[str, Any] | None = None,
    subgraph_id: str | None = None,
) -> None:
    event = RuntimeObservationEvent(
        trace_id=state.observability.trace_id,
        run_id=state.run.run_id,
        event_type=event_type,
        node_id=node_id,
        subgraph_id=subgraph_id,
        message=message,
        payload=payload or {},
    )
    services.observability_manager.emit(event)
    state.observability.events.append(event.model_dump(mode="json"))
    trace_recorder = getattr(services, "trace_recorder", None)
    if trace_recorder is not None:
        trace_recorder.record_event(
            trace_id=state.observability.trace_id,
            run_id=state.run.run_id,
            event_type=event_type,
            node_id=node_id,
            message=message,
            payload=payload or {},
        )


def record_bookmark(
    services: RuntimeServices,
    state: RuntimeState,
    context: NodeExecutionContext,
    position: str,
) -> None:
    bookmark_store = getattr(services, "bookmark_store", None)
    if bookmark_store is None:
        return
    thread_id = thread_id_from_config(context.graph_config) or state.runtime_config.session_config.get("thread_id") or ""
    if not thread_id:
        return
    bookmark_store.record(
        thread_id=str(thread_id),
        node_id=context.node_id,
        position=position,
        checkpoint_id=None,
        metadata={"run_id": state.run.run_id, "impl": context.impl},
    )


def thread_id_from_config(config: Any) -> str | None:
    if not isinstance(config, dict):
        return None
    configurable = config.get("configurable")
    if not isinstance(configurable, dict):
        return None
    value = configurable.get("thread_id")
    return str(value) if value else None


def apply_node_metrics(state: RuntimeState, duration_seconds: float) -> None:
    duration_ms = int(duration_seconds * 1000)
    metrics = dict(state.observability.metrics)
    metrics["turn_count"] = state.execution.turn_count
    metrics["total_latency_ms"] = int(metrics.get("total_latency_ms", 0)) + duration_ms
    metrics["max_node_latency_ms"] = max(int(metrics.get("max_node_latency_ms", 0)), duration_ms)
    state.observability.metrics = metrics
