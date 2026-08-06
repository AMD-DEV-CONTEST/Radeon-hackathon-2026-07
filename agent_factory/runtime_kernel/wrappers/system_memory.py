from __future__ import annotations

from typing import Any

from agent_factory.memory_system.injection import inject_runtime_cross_session_memory
from agent_factory.memory_system.reports import memory_event_payload
from agent_factory.runtime_kernel.nodes.base import NodeExecutionContext
from agent_factory.runtime_kernel.observability.schema import RuntimeObservationEvent
from agent_factory.runtime_kernel.state import RuntimeState


MEMORY_RETRIEVE_SYSTEM_WRAPPER_ID = "system.cross_session_memory_inject"


class MemoryRetrieveSystemWrapper:
    wrapper_id = MEMORY_RETRIEVE_SYSTEM_WRAPPER_ID
    before_stage = "pre_execute"

    def before(self, *, state: RuntimeState, context: NodeExecutionContext) -> tuple[RuntimeState, dict[str, Any]]:
        if not context.impl.startswith("cognitive."):
            return state, {}
        runtime = getattr(context.services, "memory_system", None)
        updated, report = inject_runtime_cross_session_memory(state=state, runtime=runtime)
        payload = memory_event_payload(report, node_id=context.node_id)
        _emit(context, updated, "memory_retrieval_completed", payload)
        _emit(context, updated, "memory_injection_completed", payload)
        if report.status != "injected":
            return updated, {}
        return updated, {"context": updated.context.model_dump(mode="json")}


SYSTEM_MEMORY_RETRIEVE_WRAPPER = MemoryRetrieveSystemWrapper()


def _emit(context: NodeExecutionContext, state: RuntimeState, event_type: str, payload: dict[str, Any]) -> None:
    event = RuntimeObservationEvent(
        trace_id=state.observability.trace_id,
        run_id=state.run.run_id,
        event_type=event_type,
        node_id=context.node_id,
        payload=payload,
    )
    context.services.observability_manager.emit(event)
    state.observability.events.append(event.model_dump(mode="json"))
    trace_recorder = getattr(context.services, "trace_recorder", None)
    if trace_recorder is not None:
        trace_recorder.record_event(
            trace_id=state.observability.trace_id,
            run_id=state.run.run_id,
            event_type=event_type,
            node_id=context.node_id,
            payload=payload,
        )
