"""Tool invocation and authorization schemas."""

from typing import Any, Literal

from pydantic import Field

from buildguard.schemas.common import RecordSchema, StrictSchema


class ToolCallRequest(RecordSchema):
    task_id: str
    tool_name: str = Field(min_length=1, max_length=128)
    arguments: dict[str, Any] = Field(default_factory=dict)
    requested_by: str = Field(min_length=1, max_length=128)


class ToolCallResult(StrictSchema):
    call_id: str
    success: bool
    output: dict[str, Any] | None = None
    error: str | None = Field(default=None, max_length=4000)
    duration_ms: float = Field(ge=0)


class PermissionDecision(RecordSchema):
    subject: str = Field(min_length=1, max_length=256)
    action: str = Field(min_length=1, max_length=256)
    resource: str = Field(min_length=1, max_length=2000)
    decision: Literal["allow", "deny"]
    reason: str = Field(min_length=1, max_length=2000)


class AuditRecord(RecordSchema):
    actor: str = Field(min_length=1, max_length=256)
    action: str = Field(min_length=1, max_length=256)
    resource: str = Field(min_length=1, max_length=2000)
    outcome: Literal["success", "failure", "denied"]
    details: dict[str, Any] = Field(default_factory=dict)
