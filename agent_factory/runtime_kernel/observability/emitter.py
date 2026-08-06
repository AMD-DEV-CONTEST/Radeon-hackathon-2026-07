from __future__ import annotations

from agent_factory.runtime_kernel.observability.schema import RuntimeObservationEvent


class ObservabilityManager:
    """In-process runtime observation buffer.

    The manager no longer owns trace spans or trace summaries. Durable trace
    facts are written by trace_system.TraceRecorder.
    """

    def __init__(self) -> None:
        self.events: list[RuntimeObservationEvent] = []

    def emit(self, event: RuntimeObservationEvent) -> None:
        self.events.append(event)

    def emit_dict(self, data: dict[str, Any]) -> None:
        self.emit(RuntimeObservationEvent.model_validate(data))

    def list_events(self) -> list[RuntimeObservationEvent]:
        return list(self.events)
