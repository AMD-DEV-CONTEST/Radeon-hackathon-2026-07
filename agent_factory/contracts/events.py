"""Persisted event envelope with a database-assigned global cursor."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class EventEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seq: int = Field(ge=1)
    event_id: str
    event_type: str
    created_at: str
    request_id: str | None = None
    task_id: str | None = None
    session_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
