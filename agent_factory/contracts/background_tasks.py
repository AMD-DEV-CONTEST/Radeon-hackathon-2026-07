"""Canonical background-task protocol without runtime or storage dependencies."""

from __future__ import annotations

from hashlib import sha256
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


BackgroundTaskType = Literal["sub_agent", "manufacture", "evolve"]
BackgroundTaskStatus = Literal[
    "queued",
    "claimed",
    "running",
    "waiting_approval",
    "waiting_external",
    "cancelling",
    "succeeded",
    "failed",
    "cancelled",
]

BACKGROUND_TASK_TYPES: frozenset[str] = frozenset({"sub_agent", "manufacture", "evolve"})
BACKGROUND_TASK_STATUSES: frozenset[str] = frozenset(
    {
        "queued",
        "claimed",
        "running",
        "waiting_approval",
        "waiting_external",
        "cancelling",
        "succeeded",
        "failed",
        "cancelled",
    }
)
TERMINAL_TASK_STATUSES: frozenset[str] = frozenset({"succeeded", "failed", "cancelled"})
LEASE_TASK_STATUSES: frozenset[str] = frozenset(
    {"claimed", "running", "cancelling"}
)
ACTIVE_TASK_STATUSES: frozenset[str] = frozenset(
    {"queued", "claimed", "running", "waiting_approval", "waiting_external", "cancelling"}
)

TASK_STATUS_TRANSITIONS: dict[str, frozenset[str]] = {
    "queued": frozenset({"claimed", "cancelled"}),
    "claimed": frozenset({"queued", "running", "cancelling", "failed", "cancelled"}),
    "running": frozenset(
        {"queued", "waiting_approval", "waiting_external", "cancelling", "succeeded", "failed", "cancelled"}
    ),
    "waiting_approval": frozenset({"queued", "cancelling", "cancelled", "failed"}),
    "waiting_external": frozenset({"queued", "cancelling", "cancelled", "failed"}),
    "cancelling": frozenset({"cancelled", "failed"}),
    "succeeded": frozenset(),
    "failed": frozenset(),
    "cancelled": frozenset(),
}


class BackgroundTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str
    session_id: str
    type: BackgroundTaskType
    status: BackgroundTaskStatus
    request_id: str
    request_fingerprint: str
    task_text: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    parent_task_id: str | None = None
    parent_package_id: str | None = None
    assignee_package_id: str | None = None
    assignee_session_id: str | None = None
    delivery_standard: dict[str, Any] = Field(default_factory=dict)
    visible_context: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)
    input_artifacts: list[dict[str, Any]] = Field(default_factory=list)
    artifact_refs: list[dict[str, Any]] = Field(default_factory=list)
    result_summary: str = ""
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    pending_approval: dict[str, Any] | None = None
    pending_external: dict[str, Any] | None = None
    resume_payload: dict[str, Any] | None = None
    lease_owner: str | None = None
    lease_token: str | None = None
    lease_expires_at: str | None = None
    heartbeat_at: str | None = None
    lease_requeue_count: int = 0
    cancel_requested_at: str | None = None
    cancel_reason: str | None = None
    resources_released_at: str | None = None
    created_at: str
    updated_at: str
    started_at: str | None = None
    completed_at: str | None = None
    revision: int = 0


class BackgroundTaskResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["succeeded", "failed", "cancelled"]
    summary: str = ""
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    result: dict[str, Any] = Field(default_factory=dict)
    error: dict[str, Any] | None = None


def can_transition_task(source: str, target: str) -> bool:
    return target in TASK_STATUS_TRANSITIONS.get(source, frozenset())


def task_request_fingerprint(
    *,
    session_id: str,
    type: BackgroundTaskType,
    task_text: str = "",
    payload: dict[str, Any] | None = None,
    parent_task_id: str | None = None,
    parent_package_id: str | None = None,
    assignee_package_id: str | None = None,
    assignee_session_id: str | None = None,
    delivery_standard: dict[str, Any] | None = None,
    visible_context: dict[str, Any] | None = None,
    depends_on: list[str] | None = None,
    input_artifacts: list[dict[str, Any]] | None = None,
) -> str:
    """Hash every material request field so a request ID is safely idempotent."""

    material = {
        "session_id": _required_text(session_id),
        "type": type,
        "task_text": str(task_text or "").strip(),
        "payload": payload or {},
        "parent_task_id": _optional_text(parent_task_id),
        "parent_package_id": _optional_text(parent_package_id),
        "assignee_package_id": _optional_text(assignee_package_id),
        "assignee_session_id": _optional_text(assignee_session_id),
        "delivery_standard": delivery_standard or {},
        "visible_context": visible_context or {},
        "depends_on": sorted({str(item).strip() for item in depends_on or [] if str(item).strip()}),
        "input_artifacts": input_artifacts or [],
    }
    encoded = json.dumps(
        material,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _required_text(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError("session_id is required")
    return text


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None
