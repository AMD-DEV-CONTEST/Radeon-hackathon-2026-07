"""AlphaNoah's persisted core objects.

The models intentionally use only Python's standard library.  They describe the
current bounded demo rather than a general-purpose agent framework.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Self

from .skill import SkillDefinition


def utc_now() -> str:
    """Return an ISO-8601 UTC timestamp suitable for audit records."""

    return datetime.now(timezone.utc).isoformat()


class EventStatus(StrEnum):
    NEW = "NEW"
    ANALYZED = "ANALYZED"
    PENDING_HUMAN_REVIEW = "PENDING_HUMAN_REVIEW"
    APPROVED = "APPROVED"
    TASK_CREATED = "TASK_CREATED"
    IN_PROGRESS = "IN_PROGRESS"
    EVIDENCE_SUBMITTED = "EVIDENCE_SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    CLOSED = "CLOSED"
    REJECTED = "REJECTED"
    NEEDS_MORE_EVIDENCE = "NEEDS_MORE_EVIDENCE"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    ESCALATED = "ESCALATED"


class DecisionStatus(StrEnum):
    PROPOSED = "PROPOSED"
    PENDING_HUMAN_REVIEW = "PENDING_HUMAN_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    REVISED = "REVISED"
    NEEDS_MORE_EVIDENCE = "NEEDS_MORE_EVIDENCE"
    ESCALATED = "ESCALATED"


class HumanReviewOutcome(StrEnum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    REVISED = "REVISED"


class TaskStatus(StrEnum):
    CREATED = "CREATED"
    IN_PROGRESS = "IN_PROGRESS"
    EVIDENCE_SUBMITTED = "EVIDENCE_SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    CLOSED = "CLOSED"
    NEEDS_MORE_EVIDENCE = "NEEDS_MORE_EVIDENCE"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class EvidenceValidationStatus(StrEnum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class PostReviewResult(StrEnum):
    PASSED = "PASSED"
    NEEDS_MORE_EVIDENCE = "NEEDS_MORE_EVIDENCE"
    FAILED = "FAILED"


class HookAction(StrEnum):
    AUTO_APPROVE = "AUTO_APPROVE"
    REQUEST_HUMAN_REVIEW = "REQUEST_HUMAN_REVIEW"
    REJECT = "REJECT"
    REQUEST_MORE_EVIDENCE = "REQUEST_MORE_EVIDENCE"
    ESCALATE = "ESCALATE"
    CREATE_TASK = "CREATE_TASK"


class Serializable:
    """Small serialization mixin for JSON-backed SQLite records."""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Event(Serializable):
    event_id: str
    source: str
    timestamp: str
    raw_input_ref: str
    normalized_input: dict[str, Any]
    detected_issue: str
    confidence: float
    severity: str
    status: EventStatus
    trace_id: str
    event_type: str = "legacy_observation"
    location: str = ""
    asset_id: str = ""
    reporter: str = ""
    description: str = ""
    attachments: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        payload = dict(data)
        normalized_input = payload.get("normalized_input")
        legacy_input = (
            normalized_input if isinstance(normalized_input, dict) else {}
        )
        payload.setdefault("event_type", "legacy_observation")
        payload.setdefault("location", legacy_input.get("location", ""))
        payload.setdefault("asset_id", "")
        payload.setdefault("reporter", "")
        payload.setdefault(
            "description",
            legacy_input.get("description")
            or legacy_input.get("observation")
            or "",
        )
        payload["attachments"] = list(payload.get("attachments") or [])
        payload["metadata"] = dict(payload.get("metadata") or {})
        payload["status"] = EventStatus(payload["status"])
        return cls(**payload)


@dataclass(slots=True)
class Decision(Serializable):
    decision_id: str
    event_id: str
    decision_type: str
    reasoning_summary: str
    evidence: list[str]
    model_or_rule: str
    confidence: float
    requires_human_review: bool
    status: DecisionStatus
    risk_level: str = "UNKNOWN"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        return cls(**{**data, "status": DecisionStatus(data["status"])})


@dataclass(slots=True)
class HumanReview(Serializable):
    human_review_id: str
    reviewer: str
    decision_id: str
    outcome: HumanReviewOutcome
    comment: str
    timestamp: str
    revision_request: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        return cls(**{**data, "outcome": HumanReviewOutcome(data["outcome"])})


@dataclass(slots=True)
class Task(Serializable):
    task_id: str
    source_decision_id: str
    task_type: str
    assignee: str
    description: str
    expected_result: str
    deadline: str
    status: TaskStatus

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        return cls(**{**data, "status": TaskStatus(data["status"])})


@dataclass(slots=True)
class Evidence(Serializable):
    evidence_id: str
    task_id: str
    type: str
    file_or_data_ref: str
    submitted_by: str
    timestamp: str
    validation_status: EvidenceValidationStatus
    description: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        return cls(
            **{
                **data,
                "validation_status": EvidenceValidationStatus(
                    data["validation_status"]
                ),
            }
        )


@dataclass(slots=True)
class Review(Serializable):
    review_id: str
    event_id: str
    task_id: str
    evidence: list[str]
    result: PostReviewResult
    reviewer_or_model: str
    closed: bool
    follow_up_required: bool
    timestamp: str
    comment: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        return cls(**{**data, "result": PostReviewResult(data["result"])})


@dataclass(slots=True)
class AuditRecord(Serializable):
    audit_id: str
    actor: str
    action: str
    object_type: str
    object_id: str
    previous_state: str | None
    new_state: str | None
    timestamp: str
    trace_id: str
    details: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        return cls(**data)


@dataclass(slots=True)
class AnalysisResult(Serializable):
    detected_issue: str
    decision_type: str
    reasoning_summary: str
    evidence: list[str]
    model_or_rule: str
    confidence: float
    requires_human_review: bool
    severity: str


@dataclass(slots=True)
class HookResult(Serializable):
    action: HookAction
    target_status: EventStatus
    reason: str
