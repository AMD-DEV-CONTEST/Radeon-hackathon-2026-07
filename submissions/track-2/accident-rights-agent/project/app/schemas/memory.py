"""Four-layer case-memory contracts and immutable fact transitions."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.legal import LegalCitation


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class MemoryFactStatus(str, Enum):
    UNVERIFIED = "unverified"
    CONFIRMED = "confirmed"
    DISPUTED = "disputed"
    REJECTED = "rejected"


ALLOWED_FACT_TRANSITIONS: dict[MemoryFactStatus, set[MemoryFactStatus]] = {
    MemoryFactStatus.UNVERIFIED: {
        MemoryFactStatus.CONFIRMED,
        MemoryFactStatus.DISPUTED,
        MemoryFactStatus.REJECTED,
    },
    MemoryFactStatus.CONFIRMED: {
        MemoryFactStatus.DISPUTED,
        MemoryFactStatus.REJECTED,
    },
    MemoryFactStatus.DISPUTED: {
        MemoryFactStatus.CONFIRMED,
        MemoryFactStatus.REJECTED,
    },
    MemoryFactStatus.REJECTED: set(),
}


class ProtectedFieldKind(str, Enum):
    DATE = "date"
    DEADLINE = "deadline"
    AMOUNT = "amount"
    LIABILITY_RATIO = "liability_ratio"
    VEHICLE_ID = "vehicle_id"
    PARTY_ROLE = "party_role"
    EVIDENCE_ID = "evidence_id"
    FACT_ID = "fact_id"
    LAW_ID = "law_id"
    DOCUMENT_VERSION = "document_version"
    APPROVAL_STATUS = "approval_status"


class ProtectedField(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: ProtectedFieldKind
    value: str = Field(min_length=1)
    source_path: str = Field(min_length=1)


class FactTransitionEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str
    case_id: str
    fact_id: str
    from_status: MemoryFactStatus
    to_status: MemoryFactStatus
    actor: str
    timestamp: str = Field(default_factory=utc_now)
    reason: str = Field(min_length=2)
    version: int = Field(ge=1)

    @model_validator(mode="after")
    def enforce_transition(self) -> "FactTransitionEvent":
        if self.to_status not in ALLOWED_FACT_TRANSITIONS[self.from_status]:
            raise ValueError(
                f"Illegal fact transition: {self.from_status} -> {self.to_status}"
            )
        return self


class CaseCapsule(BaseModel):
    """Strict, versioned summary passed between agents."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    confirmed_facts: list[dict[str, Any]] = Field(default_factory=list)
    disputed_facts: list[dict[str, Any]] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    vehicle_classification: dict[str, Any] = Field(default_factory=dict)
    liability_hypotheses: list[dict[str, Any]] = Field(default_factory=list)
    legal_issues: list[str] = Field(default_factory=list)
    rights_deadlines: list[dict[str, Any]] = Field(default_factory=list)
    next_actions: list[dict[str, Any]] = Field(default_factory=list)
    citations: list[LegalCitation] = Field(default_factory=list)
    last_updated_by: str
    version: int = Field(ge=1)


class MemoryEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str
    case_id: str
    event_type: str
    actor: str
    timestamp: str = Field(default_factory=utc_now)
    version: int = Field(ge=1)
    payload: dict[str, Any]


class ContextBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    task: str
    capsule: CaseCapsule
    facts: list[dict[str, Any]]
    citations: list[LegalCitation]
    evidence_ids: list[str] = Field(default_factory=list)
    workflow_state: dict[str, Any] = Field(default_factory=dict)
    protected_values: dict[str, list[str]] = Field(default_factory=dict)
    before_token_count: int = Field(ge=0)
    after_token_count: int = Field(ge=0)
    protected_fields: list[ProtectedField]
    protected_field_retention: float = Field(ge=0.0, le=1.0, default=1.0)
    full_history_items: int = Field(ge=0, default=0)

    def prompt_payload(self) -> dict[str, Any]:
        """Return only the task-scoped payload intended for an Agent prompt."""

        return {
            "case_id": self.case_id,
            "task": self.task,
            "capsule": self.capsule.model_dump(mode="json"),
            "facts": self.facts,
            "citations": [item.model_dump(mode="json") for item in self.citations],
            "evidence_ids": self.evidence_ids,
            "workflow_state": self.workflow_state,
            "protected_values": self.protected_values,
        }
