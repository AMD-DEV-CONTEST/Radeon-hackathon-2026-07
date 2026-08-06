from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from agent_factory.scheduler_system.schema import SchedulerRunStatus, SchedulerTargetType


SchedulerEventType = Literal[
    "scheduler_job_created",
    "scheduler_job_updated",
    "scheduler_job_deleted",
    "scheduler_job_auto_paused",
    "scheduler_jobs_listed",
    "scheduler_options_listed",
    "scheduler_job_described",
    "scheduler_runs_listed",
    "scheduler_run_scheduled",
    "scheduler_run_started",
    "scheduler_run_completed",
    "scheduler_run_failed",
    "scheduler_run_skipped",
    "scheduler_run_cancelled",
    "scheduler_feedback_completed",
    "scheduler_feedback_failed",
    "scheduler_seed_detected",
    "scheduler_seed_applied",
    "scheduler_seed_unchanged",
    "scheduler_seed_failed",
]


class SchedulerEventPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_type: SchedulerEventType
    job_id: str | None = None
    run_id: str | None = None
    owner_type: str | None = None
    owner_id: str | None = None
    target_type: SchedulerTargetType | None = None
    status: SchedulerRunStatus | str | None = None
    scheduled_at: str | None = None
    duration_ms: int | None = None
    completed_at: str | None = None
    completed_count: int | None = None
    task_content: str | None = None
    summary: str | None = None
    error_summary: str | None = None
    report_path: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


def scheduler_custom_event(payload: SchedulerEventPayload | dict[str, Any]) -> dict[str, Any]:
    value = payload.model_dump(mode="json") if isinstance(payload, SchedulerEventPayload) else payload
    return {"type": "scheduler_event", "payload": value}
