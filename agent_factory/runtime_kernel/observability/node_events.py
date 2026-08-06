from __future__ import annotations

from langgraph.config import get_stream_writer

from agent_factory.runtime_kernel.observability.schema import RuntimeObservationEvent


def emit_runtime_node_event(event: RuntimeObservationEvent) -> None:
    try:
        writer = get_stream_writer()
    except Exception:
        return
    try:
        writer({"type": "node_event", "payload": event.model_dump(mode="json")})
    except Exception:
        return
