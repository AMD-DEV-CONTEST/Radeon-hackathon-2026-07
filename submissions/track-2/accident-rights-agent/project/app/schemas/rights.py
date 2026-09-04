"""Strict contracts for deadlines, rights tasks, drafts, and human approval."""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.legal import LegalCitation


class StrictRightsModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class DeliveryDateStatus(str, Enum):
    CONFIRMED = "confirmed"
    DISPUTED = "disputed"
    WEAK_EVIDENCE = "weak_evidence"
    MISSING = "missing"


class DeliveryDateCandidate(StrictRightsModel):
    date_type: str
    extracted_date: date
    raw_text: str
    source_type: str
    source_id: str | None = None
    evidence_id: str | None = None
    extraction_method: str
    confidence: float = Field(ge=0.0, le=1.0)
    priority: int = Field(ge=0, le=100)
    is_delivery_evidence: bool


class DeliveryDateResult(StrictRightsModel):
    status: DeliveryDateStatus
    date_type: str
    extracted_date: date | None = None
    original_date_text: str | None = None
    source_type: str
    source_id: str | None = None
    evidence_id: str | None = None
    extraction_method: str
    confidence: float = Field(ge=0.0, le=1.0)
    timezone: str = "Asia/Shanghai"
    ambiguity: list[str] = Field(default_factory=list)
    alternatives: list[DeliveryDateCandidate] = Field(default_factory=list)
    requires_human_confirmation: bool

    @model_validator(mode="after")
    def disputed_dates_cannot_be_selected(self) -> "DeliveryDateResult":
        if self.status is DeliveryDateStatus.DISPUTED and self.extracted_date is not None:
            raise ValueError("A disputed delivery date cannot be auto-selected.")
        if self.status in {
            DeliveryDateStatus.MISSING,
            DeliveryDateStatus.WEAK_EVIDENCE,
        } and not self.requires_human_confirmation:
            raise ValueError("Missing or weak delivery dates require human confirmation.")
        return self


class DeadlineStatus(str, Enum):
    NOT_STARTED = "not_started"
    ACTIVE = "active"
    DUE_SOON = "due_soon"
    EXPIRED = "expired"
    DISPUTED = "disputed"


class LegalReviewStatus(str, Enum):
    NOT_NEEDED = "not_needed"
    NEEDS_LEGAL_REVIEW = "needs_legal_review"


class DeadlineResult(StrictRightsModel):
    deadline_id: str
    matter_type: str
    trigger_date: date | None = None
    original_trigger_text: str | None = None
    rule_id: str
    law_id: str
    calculation_method: dict[str, Any]
    due_at: datetime | None = None
    remaining_duration: str | None = None
    status: DeadlineStatus
    legal_citations: list[LegalCitation] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    requires_human_confirmation: bool
    legal_review_status: LegalReviewStatus = LegalReviewStatus.NOT_NEEDED
    timezone: str = "Asia/Shanghai"


class TaskPriority(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class RightsTaskStatus(str, Enum):
    DRAFT = "draft"
    PENDING = "pending"
    APPROVED = "approved"
    IN_PROGRESS = "in_progress"
    SUBMITTED = "submitted"
    SENT = "sent"
    COMPLETED = "completed"
    COMPLETED_BY_EXTERNAL_AUTHORITY = "completed_by_external_authority"
    REJECTED = "rejected"


class RightsTask(StrictRightsModel):
    task_id: str
    task_type: str
    title: str
    objective: str
    priority: TaskPriority
    status: RightsTaskStatus = RightsTaskStatus.DRAFT
    due_at: datetime | None = None
    blocking: bool
    related_fact_ids: list[str] = Field(default_factory=list)
    related_evidence_ids: list[str] = Field(default_factory=list)
    related_law_ids: list[str] = Field(default_factory=list)
    prerequisites: list[str] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
    responsible_role: str
    human_approval_required: bool = True


class CounterfactualImpact(StrictRightsModel):
    condition: str
    affected_conclusions: list[str]
    likely_direction: str
    caveat: str


class EvidenceCollectionItem(StrictRightsModel):
    gap_id: str
    missing_evidence: str
    why_important: str
    affected_conclusions: list[str]
    priority: TaskPriority
    due_at: datetime | None = None
    lawful_collection_methods: list[str]
    alternative_evidence: list[str]
    fallback_if_unavailable: str
    counterfactual_impacts: list[CounterfactualImpact] = Field(default_factory=list)
    related_fact_ids: list[str] = Field(default_factory=list)
    related_evidence_ids: list[str] = Field(default_factory=list)


class DraftFactSentence(StrictRightsModel):
    text: str
    fact_ids: list[str] = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)
    fact_status: str
    qualification: str | None = None


class ReviewApplicationDraft(StrictRightsModel):
    document_id: str
    document_type: str = "road_accident_determination_review_application"
    document_version: int = Field(ge=1)
    status: str = Field(default="draft", pattern=r"^draft$")
    applicant: dict[str, str | None]
    challenged_document: dict[str, str | None]
    requests: list[str]
    facts: list[DraftFactSentence]
    disputed_issues: list[str]
    review_reasons: list[str]
    evidence_catalog: list[dict[str, Any]]
    legal_basis: list[LegalCitation]
    attachments: list[str]
    signature_placeholder: str
    date_placeholder: str
    blocking_fields: list[str] = Field(default_factory=list)
    not_submittable_reasons: list[str] = Field(default_factory=list)
    risk_language_findings: list[str] = Field(default_factory=list)
    inputs_hash: str = Field(pattern=r"^[a-f0-9]{64}$")

    @property
    def submittable_after_approval(self) -> bool:
        return not self.blocking_fields and not self.not_submittable_reasons


class ApprovalDecision(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CHANGES_REQUESTED = "changes_requested"
    EXPIRED = "expired"


class ApprovalRecord(StrictRightsModel):
    approver: str
    timestamp: datetime
    decision: ApprovalDecision
    comments: str
    document_version: int = Field(ge=1)
    inputs_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    audit_event_id: str


class HumanApprovalState(StrictRightsModel):
    state: ApprovalDecision = ApprovalDecision.PENDING
    document_version: int = Field(ge=1)
    inputs_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    record: ApprovalRecord | None = None
    invalidation_reason: str | None = None

    @model_validator(mode="after")
    def record_matches_state(self) -> "HumanApprovalState":
        if self.state is ApprovalDecision.PENDING and self.record is not None:
            raise ValueError("Pending approval cannot carry a completed decision record.")
        if self.state is not ApprovalDecision.PENDING and self.record is None:
            raise ValueError("A completed approval decision requires an audit record.")
        return self


EXTERNAL_TASK_STATES = {
    RightsTaskStatus.SUBMITTED,
    RightsTaskStatus.SENT,
    RightsTaskStatus.COMPLETED_BY_EXTERNAL_AUTHORITY,
}
