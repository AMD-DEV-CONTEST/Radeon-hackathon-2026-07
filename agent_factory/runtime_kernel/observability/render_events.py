from __future__ import annotations

from langgraph.config import get_stream_writer

from agent_factory.runtime_kernel.bindings import RuntimeServices
from agent_factory.runtime_kernel.observability.schema import RuntimeObservationEvent
from agent_factory.runtime_kernel.state import RuntimeState
from agent_factory.runtime_render import RuntimeRenderEvent


def runtime_render_event_to_observation_event(
    render_event: RuntimeRenderEvent,
    *,
    trace_id: str,
    run_id: str,
) -> RuntimeObservationEvent:
    payload = {
        "runtime_render": render_event.model_dump(mode="json"),
    }
    return RuntimeObservationEvent(
        trace_id=trace_id,
        run_id=run_id,
        event_type=render_event.event_type,
        node_id=render_event.node_id,
        message=render_event.message,
        payload=payload,
    )


def observation_event_to_runtime_render_event(event: RuntimeObservationEvent) -> RuntimeRenderEvent | None:
    raw_event = event.payload.get("runtime_render")
    if not isinstance(raw_event, dict):
        return None
    return RuntimeRenderEvent.model_validate(raw_event)


def emit_runtime_render_event(
    *,
    services: RuntimeServices,
    state: RuntimeState,
    render_event: RuntimeRenderEvent,
) -> None:
    observation_event = runtime_render_event_to_observation_event(
        render_event,
        trace_id=state.observability.trace_id,
        run_id=state.run.run_id,
    )
    services.observability_manager.emit(observation_event)
    state.observability.events.append(observation_event.model_dump(mode="json"))
    trace_recorder = getattr(services, "trace_recorder", None)
    if trace_recorder is not None:
        trace_recorder.record_event(
            trace_id=state.observability.trace_id,
            run_id=state.run.run_id,
            event_type=render_event.event_type,
            node_id=render_event.node_id,
            message=render_event.message,
            payload={"runtime_render": render_event.model_dump(mode="json")},
        )
    _emit_stream_event(render_event)


def _emit_stream_event(render_event: RuntimeRenderEvent) -> None:
    try:
        writer = get_stream_writer()
    except Exception:
        return
    try:
        writer(
            {
                "type": "runtime_render_event",
                "payload": render_event.model_dump(mode="json"),
            }
        )
    except Exception:
        return
