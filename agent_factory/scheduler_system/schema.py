from __future__ import annotations

from datetime import UTC, datetime, timedelta
import importlib
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agent_factory.builtin_packages import DEFAULT_AGENT_PACKAGE_ID
from agent_factory.tooling.builtins.aliases import canonical_builtin_tool_id

SchedulerOwnerType = Literal["factory", "agent"]
SchedulerStoreBackend = Literal["sqlite"]
SchedulerScheduleType = Literal["cron", "interval", "date"]
SchedulerTargetType = Literal["graph_run", "script_run", "tool_call"]
SchedulerConcurrencyPolicy = Literal["skip", "queue", "replace"]
SchedulerUnattendedPolicy = Literal["deny_if_approval_required", "pause_and_wait_for_user", "allow_preapproved_only"]
SchedulerRunStatus = Literal["pending", "running", "completed", "failed", "skipped", "cancelled"]
SchedulerFeedbackMode = Literal["llm_summary"]
SchedulerFailureAction = Literal["pause"]
SchedulerSeedSourceType = Literal["package_seed"]


class SchedulerFailurePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    max_consecutive_failures: int = Field(default=3, ge=1)
    action: SchedulerFailureAction = "pause"


class SchedulerContractConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    store_backend: SchedulerStoreBackend = "sqlite"
    store_path: str = ".agent_runtime/scheduler/scheduler.sqlite"
    timezone: str = "Asia/Shanghai"
    default_concurrency_policy: SchedulerConcurrencyPolicy = "skip"
    default_timeout_seconds: int = Field(default=900, ge=1)
    unattended_policy: SchedulerUnattendedPolicy = "deny_if_approval_required"
    default_failure_policy: SchedulerFailurePolicy = Field(default_factory=SchedulerFailurePolicy)


class SchedulerTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_type: SchedulerTargetType
    payload: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_payload(self) -> "SchedulerTarget":
        if self.target_type == "graph_run":
            message = str(self.payload.get("message") or "").strip()
            if not message:
                raise ValueError("graph_run target payload requires message")
            target_scope = str(self.payload.get("target_scope") or "agent_package").strip()
            if target_scope == "chat":
                target_scope = "agent_package"
                self.payload.setdefault("package_id", DEFAULT_AGENT_PACKAGE_ID)
            if target_scope != "agent_package":
                raise ValueError("graph_run target payload has invalid target_scope")
            self.payload["target_scope"] = target_scope
        elif self.target_type == "script_run":
            command = self.payload.get("command")
            if not isinstance(command, str) or not command.strip():
                raise ValueError("script_run target payload requires command as non-empty string")
        elif self.target_type == "tool_call":
            tool_id = str(self.payload.get("tool_id") or "").strip()
            arguments = self.payload.get("arguments")
            if not tool_id:
                raise ValueError("tool_call target payload requires tool_id")
            self.payload["tool_id"] = canonical_builtin_tool_id(tool_id)
            if arguments is not None and not isinstance(arguments, dict):
                raise ValueError("tool_call target payload arguments must be an object")
        return self


class SchedulerFeedbackConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    mode: SchedulerFeedbackMode = "llm_summary"


class SchedulerExecutionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_config: dict[str, Any] = Field(default_factory=dict)
    runtime_request: dict[str, Any] = Field(default_factory=dict)


class SchedulerJobOrigin(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_type: SchedulerSeedSourceType
    package_id: str
    seed_id: str
    seed_hash: str

    @field_validator("package_id", "seed_id", "seed_hash")
    @classmethod
    def _origin_text_is_not_empty(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("scheduler job origin fields must not be empty")
        return text


class SchedulerSeedPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seed_id: str
    title: str
    human_schedule: str
    schedule_type: SchedulerScheduleType
    schedule_expr: str
    timezone: str = "Asia/Shanghai"
    target: SchedulerTarget
    task_content: str
    enabled_on_apply: bool = True
    failure_policy: SchedulerFailurePolicy = Field(default_factory=SchedulerFailurePolicy)
    feedback: SchedulerFeedbackConfig = Field(default_factory=SchedulerFeedbackConfig)
    source_slot_id: str
    concurrency_policy: SchedulerConcurrencyPolicy = "skip"
    max_concurrent_runs: int = Field(default=1, ge=1)
    timeout_seconds: int = Field(default=900, ge=1)
    unattended_policy: SchedulerUnattendedPolicy = "deny_if_approval_required"

    @field_validator("seed_id", "title", "human_schedule", "schedule_expr", "timezone", "task_content", "source_slot_id")
    @classmethod
    def _seed_text_is_not_empty(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("scheduler seed fields must not be empty")
        return text

    @field_validator("seed_id")
    @classmethod
    def _seed_id_is_safe(cls, value: str) -> str:
        text = value.strip()
        if any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789_-" for ch in text):
            raise ValueError("seed_id must use lowercase letters, numbers, underscore, or dash")
        return text

    @model_validator(mode="after")
    def _validate_seed_schedule(self) -> "SchedulerSeedPlan":
        _validate_schedule_expression(
            schedule_type=self.schedule_type,
            schedule_expr=self.schedule_expr,
            timezone=self.timezone,
        )
        return self


class SchedulerSeedContractConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seeds: list[SchedulerSeedPlan] = Field(default_factory=list)

    @field_validator("seeds")
    @classmethod
    def _seed_ids_are_unique(cls, values: list[SchedulerSeedPlan]) -> list[SchedulerSeedPlan]:
        seen: set[str] = set()
        for item in values:
            if item.seed_id in seen:
                raise ValueError(f"duplicate scheduler seed_id: {item.seed_id}")
            seen.add(item.seed_id)
        return values


class SchedulerJob(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str = Field(default_factory=lambda: uuid4().hex)
    owner_type: SchedulerOwnerType
    owner_id: str
    enabled: bool = True
    schedule_type: SchedulerScheduleType
    schedule_expr: str
    timezone: str = "Asia/Shanghai"
    task_content: str = ""
    target: SchedulerTarget
    feedback: SchedulerFeedbackConfig = Field(default_factory=SchedulerFeedbackConfig)
    concurrency_policy: SchedulerConcurrencyPolicy = "skip"
    max_concurrent_runs: int = Field(default=1, ge=1)
    timeout_seconds: int = Field(default=900, ge=1)
    retry_policy: dict[str, Any] = Field(default_factory=dict)
    runtime_config: SchedulerExecutionConfig = Field(default_factory=SchedulerExecutionConfig)
    failure_policy: SchedulerFailurePolicy = Field(default_factory=SchedulerFailurePolicy)
    unattended_policy: SchedulerUnattendedPolicy = "deny_if_approval_required"
    origin: SchedulerJobOrigin | None = None
    created_at: str = Field(default_factory=lambda: utc_now().isoformat())
    updated_at: str = Field(default_factory=lambda: utc_now().isoformat())

    @field_validator("owner_id", "schedule_expr", "timezone")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("value must not be empty")
        return value.strip()

    @field_validator("task_content")
    @classmethod
    def _strip_optional_text(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def _validate_schedule(self) -> "SchedulerJob":
        _validate_schedule_expression(
            schedule_type=self.schedule_type,
            schedule_expr=self.schedule_expr,
            timezone=self.timezone,
        )
        return self


def _validate_schedule_expression(*, schedule_type: SchedulerScheduleType, schedule_expr: str, timezone: str) -> None:
    triggers = importlib.import_module("agent_factory.scheduler_system.triggers")
    triggers.validate_schedule_expression(
        schedule_type=schedule_type,
        schedule_expr=schedule_expr,
        timezone=timezone,
    )


class SchedulerRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(default_factory=lambda: uuid4().hex)
    job_id: str
    owner_type: SchedulerOwnerType
    owner_id: str
    target_type: SchedulerTargetType
    status: SchedulerRunStatus = "pending"
    scheduled_at: str
    started_at: str | None = None
    completed_at: str | None = None
    trigger_reason: str = "scheduled"
    output_summary: str | None = None
    error_summary: str | None = None
    event_trace_id: str | None = None
    report_path: str | None = None


class SchedulerLease(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lease_id: str = Field(default_factory=lambda: uuid4().hex)
    job_id: str
    run_id: str
    holder_id: str
    expires_at: str


class SchedulerExecutionReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["scheduler_execution_report.v0"] = "scheduler_execution_report.v0"
    run_id: str
    job_id: str
    owner_type: SchedulerOwnerType
    owner_id: str
    target_type: SchedulerTargetType
    status: Literal["completed", "failed", "skipped", "cancelled"]
    started_at: str
    completed_at: str
    duration_ms: int
    output_summary: str | None = None
    error_summary: str | None = None
    stdout_preview: str | None = None
    stderr_preview: str | None = None
    exit_code: int | None = None
    evidence: dict[str, Any] = Field(default_factory=dict)


class SchedulerFeedbackSummaryDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1)


def utc_now() -> datetime:
    return datetime.now(UTC)


def utc_after(seconds: int) -> datetime:
    return utc_now() + timedelta(seconds=seconds)
