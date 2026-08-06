from __future__ import annotations

from typing import Literal, TypeAlias


EventPersistence: TypeAlias = Literal["durable", "transient"]


def event_persistence(event_type: str) -> EventPersistence:
    """Classify runtime events by their durable evidence value.

    Delta events are transport fragments. Their completed snapshot is the
    durable evidence, while the fragments remain available to live consumers.
    The suffix is part of the runtime event protocol, so future delta channels
    inherit the same policy without adding model- or tool-specific branches.
    """

    normalized = str(event_type or "").strip()
    return "transient" if normalized.endswith("_delta") else "durable"


def is_durable_event(event_type: str) -> bool:
    return event_persistence(event_type) == "durable"
