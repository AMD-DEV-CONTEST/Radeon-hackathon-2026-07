"""Tool-system request and result schemas."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from buildguard.schemas.common import RecordSchema, StrictSchema


class ToolExecutionRequest(RecordSchema):
    session_id: str = Field(min_length=1, max_length=128)
    task_id: str = Field(min_length=1, max_length=128)
    actor: str = Field(min_length=1, max_length=256)
    tool_name: str = Field(min_length=1, max_length=128)
    arguments: dict[str, Any] = Field(default_factory=dict)
    confirmation_id: str | None = None
    capability_id: str | None = None
    resource_ids: list[str] = Field(default_factory=list)


class ConfirmationRequest(RecordSchema):
    tool_name: str = Field(min_length=1, max_length=128)
    parameter_summary: dict[str, Any]
    access_paths: list[Path] = Field(default_factory=list)
    risk_description: str = Field(min_length=1, max_length=2000)
    expires_at: datetime
    status: Literal["pending", "approved", "denied", "expired"] = "pending"


class PermissionCheck(StrictSchema):
    decision: Literal["allow", "confirm", "deny"]
    reason: str = Field(min_length=1, max_length=2000)
    confirmation: ConfirmationRequest | None = None


class ToolAuditEntry(RecordSchema):
    actor: str
    task_id: str
    session_id: str
    tool_name: str
    parameter_summary: dict[str, Any]
    permission_decision: Literal["allow", "confirm", "deny"]
    confirmation_result: Literal["not_required", "pending", "approved", "denied", "expired"]
    started_at: datetime
    ended_at: datetime
    execution_status: Literal["success", "failure", "denied", "pending_confirmation"]
    error: str | None = None


class ListInspectionImagesInput(StrictSchema):
    directory: Path = Field(default_factory=lambda: Path("."))
    recursive: bool = False
    max_items: int | None = Field(default=None, ge=1, le=10_000)


class ListInspectionImagesOutput(StrictSchema):
    images: list[Path]
    skipped: int = Field(ge=0)


class QueryTaskHistoryInput(StrictSchema):
    session_id: str | None = None
    limit: int = Field(default=20, ge=1, le=500)


class QueryTaskHistoryOutput(StrictSchema):
    tasks: list[dict[str, Any]]


class RuntimeStatusInput(StrictSchema):
    include_process: bool = True


class RuntimeStatusOutput(StrictSchema):
    operating_system: str
    python_version: str
    cpu_percent: float | None = None
    process_memory_mb: float | None = None
