from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from agent_factory.event_persistence import EventPersistence, event_persistence


class RuntimeObservationEvent(BaseModel):
    """Runtime-local observation event.

    This is not the durable trace fact schema. Runtime observations feed
    in-process state and UI events; durable causality is written by
    agent_factory.trace_system.
    """

    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(default_factory=lambda: uuid4().hex)
    trace_id: str
    run_id: str
    event_type: str
    persistence: EventPersistence = "durable"
    node_id: str | None = None
    subgraph_id: str | None = None
    message: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def model_post_init(self, __context: Any) -> None:
        self.persistence = event_persistence(self.event_type)
