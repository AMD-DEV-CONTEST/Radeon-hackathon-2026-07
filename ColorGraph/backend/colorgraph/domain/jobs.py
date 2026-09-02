from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class JobRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: str
    project_id: str
    status: JobStatus = JobStatus.QUEUED
    stage: str = "queued"
    progress: int = Field(default=0, ge=0, le=100)
    message: str = ""
    device: str = "cpu"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    result: dict[str, Any] | None = None
    error: str | None = None
