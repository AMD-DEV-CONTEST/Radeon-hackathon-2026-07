from __future__ import annotations

from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


DEFAULT_TRACE_MANIFEST_FLUSH_RECORD_INTERVAL = 32


class TraceContractConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    root: str = ".agent_runtime/trace"
    max_inline_payload_chars: int = Field(default=12000, ge=1000)
    manifest_flush_record_interval: int = Field(
        default=DEFAULT_TRACE_MANIFEST_FLUSH_RECORD_INTERVAL,
        ge=1,
    )

    @field_validator("root")
    @classmethod
    def _root_is_safe(cls, value: str) -> str:
        raw = str(value).strip()
        if not raw:
            raise ValueError("trace root must not be empty")
        path = PurePosixPath(raw)
        if path == PurePosixPath("/"):
            raise ValueError("trace root must not point at the container root")
        if any(part in {"", ".", ".."} for part in path.parts):
            raise ValueError("trace root must not contain empty, current, or parent segments")
        return raw


class TraceManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["trace_manifest.v0"] = "trace_manifest.v0"
    trace_id: str
    run_id: str | None = None
    agent_id: str | None = None
    session_id: str | None = None
    package_id: str | None = None
    producer_type: str | None = None
    status: Literal["started", "running", "completed", "failed"] = "started"
    started_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)
    finished_at: str | None = None
    counters: dict[str, int] = Field(default_factory=dict)


class TraceFactRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["trace_fact.v0"] = "trace_fact.v0"
    record_id: str = Field(default_factory=lambda: uuid4().hex)
    trace_id: str
    run_id: str
    record_type: Literal["event", "span_started", "span_finished", "diagnostic"]
    event_type: str
    span_id: str | None = None
    parent_span_id: str | None = None
    span_kind: str | None = None
    node_id: str | None = None
    tool_call_id: str | None = None
    model_role: str | None = None
    status: str | None = None
    message: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=utc_now)


class TraceReferenceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["trace_reference.v0"] = "trace_reference.v0"
    reference_id: str = Field(default_factory=lambda: uuid4().hex)
    trace_id: str
    run_id: str
    span_id: str | None = None
    reference_type: str
    uri: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=utc_now)


class TraceRunFilter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: list[str] = Field(default_factory=list)
    agent_id: str | None = None
    session_id: str | None = None
    package_id: str | None = None
    producer_type: str | None = None
    limit: int = Field(default=100, ge=1)


class TraceFactQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record_types: list[str] = Field(default_factory=list)
    event_types: list[str] = Field(default_factory=list)
    node_id: str | None = None
    span_id: str | None = None
    status: str | None = None
    limit: int | None = Field(default=None, ge=1)


class TraceTimelineItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record_id: str
    timestamp: str
    item_type: str
    event_type: str
    node_id: str | None = None
    span_id: str | None = None
    parent_span_id: str | None = None
    span_kind: str | None = None
    status: str | None = None
    message: str | None = None
    summary: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class TraceSpanNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    span_id: str
    parent_span_id: str | None = None
    span_kind: str | None = None
    name: str | None = None
    node_id: str | None = None
    status: str = "started"
    started_at: str | None = None
    finished_at: str | None = None
    duration_ms: int | None = None
    start_payload: dict[str, Any] = Field(default_factory=dict)
    finish_payload: dict[str, Any] = Field(default_factory=dict)
    children: list["TraceSpanNode"] = Field(default_factory=list)


class TraceErrorItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record_id: str
    timestamp: str
    event_type: str
    node_id: str | None = None
    span_id: str | None = None
    span_kind: str | None = None
    status: str | None = None
    message: str | None = None
    error_summary: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class TraceReferenceIndexItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reference_id: str
    trace_id: str
    run_id: str
    span_id: str | None = None
    reference_type: str
    uri: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str


class TraceProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    manifest: TraceManifest
    timeline: list[TraceTimelineItem] = Field(default_factory=list)
    span_tree: list[TraceSpanNode] = Field(default_factory=list)
    errors: list[TraceErrorItem] = Field(default_factory=list)
    references: list[TraceReferenceIndexItem] = Field(default_factory=list)


class RepairTracePack(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trace_id: str
    run_id: str | None = None
    status: str
    failed_node: str | None = None
    failed_span_id: str | None = None
    failure_category: str | None = None
    error_chain: list[TraceErrorItem] = Field(default_factory=list)
    recent_events: list[TraceTimelineItem] = Field(default_factory=list)
    tool_events: list[TraceTimelineItem] = Field(default_factory=list)
    model_events: list[TraceTimelineItem] = Field(default_factory=list)
    context_events: list[TraceTimelineItem] = Field(default_factory=list)
    references: list[TraceReferenceIndexItem] = Field(default_factory=list)
    suspected_root_causes: list[str] = Field(default_factory=list)
    repair_targets: list[str] = Field(default_factory=list)
