from __future__ import annotations

from typing import Any

from agent_factory.memory_system.schema import MemoryInjectionReport, MemoryWriteReport


def memory_event_payload(report: MemoryWriteReport | MemoryInjectionReport, **extra: Any) -> dict[str, Any]:
    payload = report.model_dump(mode="json")
    payload.update(extra)
    payload.pop("content", None)
    return payload
