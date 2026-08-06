from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


MemoryScope = Literal["factory", "agent", "user", "workspace"]
MemoryTargetScope = Literal["factory", "workspace", "agent", "user", "none"]
MemoryKind = Literal["fact", "preference", "decision", "constraint", "artifact"]
MemoryType = Literal["semantic", "episodic", "procedural"]
MemoryExtractionActionType = Literal["add", "update", "delete", "noop"]
MemoryWriteStatus = Literal["queued", "queued_failed", "completed", "failed", "noop"]


class MemoryConversationMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"]
    content: str
    turn_index: int | None = None
    message_index: int = Field(ge=0)


class MemoryConversationSegment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    segment_id: str = Field(default_factory=lambda: uuid4().hex)
    scope: MemoryScope
    namespace: tuple[str, ...]
    start_turn: int = Field(ge=1)
    end_turn: int = Field(ge=1)
    messages: list[MemoryConversationMessage] = Field(default_factory=list, max_length=64)
    source: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class MemoryExtractionAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: MemoryExtractionActionType
    target_scope: MemoryTargetScope
    memory_type: MemoryType | None = None
    kind: MemoryKind | None = None
    content: str = ""
    reason: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    merge_target_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class MemoryExtractionDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["complete", "noop", "failed"]
    actions: list[MemoryExtractionAction] = Field(default_factory=list, max_length=8)
    notes: list[str] = Field(default_factory=list, max_length=8)


class MemoryContextItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    memory_id: str
    source_scope: MemoryTargetScope = "none"
    memory_type: MemoryType = "semantic"
    kind: MemoryKind
    content: str
    score: float = Field(ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)
    namespace: tuple[str, ...] = Field(default_factory=tuple)
    updated_at: str | None = None


class MemoryContextPack(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["memory_context.v0"] = "memory_context.v0"
    namespace: tuple[str, ...]
    query: str
    items: list[MemoryContextItem] = Field(default_factory=list)
    token_estimate: int = 0
    report: dict[str, Any] = Field(default_factory=dict)


class MemoryRetrievalSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: MemoryTargetScope
    namespace: tuple[str, ...]
    priority: int = 0

    @model_validator(mode="after")
    def _writable_scope(self) -> "MemoryRetrievalSource":
        if self.scope == "none":
            raise ValueError("none is not a retrievable memory scope")
        return self


class MemoryWriteJob(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str = Field(default_factory=lambda: uuid4().hex)
    scope: MemoryScope
    namespace: tuple[str, ...]
    available_namespaces: dict[MemoryTargetScope, tuple[str, ...]] = Field(default_factory=dict)
    source: dict[str, Any] = Field(default_factory=dict)
    segment: MemoryConversationSegment
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())

    @model_validator(mode="after")
    def _segment_matches_job(self) -> "MemoryWriteJob":
        if self.segment.scope != self.scope:
            raise ValueError("segment scope must match job scope")
        if tuple(self.segment.namespace) != tuple(self.namespace):
            raise ValueError("segment namespace must match job namespace")
        if not self.available_namespaces:
            self.available_namespaces = {self.scope: self.namespace}
        if "none" in self.available_namespaces:
            raise ValueError("none is not a writable memory namespace")
        return self

    def journal_payload(self) -> dict[str, Any]:
        payload = self.model_dump(mode="json")
        segment = dict(payload.get("segment") or {})
        segment["messages"] = []
        payload["segment"] = segment
        return payload


class MemoryWriteReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    status: MemoryWriteStatus
    namespace: tuple[str, ...]
    namespaces: list[tuple[str, ...]] = Field(default_factory=list)
    action_counts: dict[str, int] = Field(default_factory=dict)
    scope_action_counts: dict[str, dict[str, int]] = Field(default_factory=dict)
    error: str | None = None
    duration_ms: int = 0
    updated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class MemoryInjectionReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["injected", "skipped", "failed"]
    namespace: tuple[str, ...] = Field(default_factory=tuple)
    namespaces: list[tuple[str, ...]] = Field(default_factory=list)
    item_count: int = 0
    token_estimate: int = 0
    min_score: float = 0.0
    error: str | None = None
    duration_ms: int = 0
