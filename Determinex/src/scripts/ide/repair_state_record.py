"""IDE-facing state record for the verified-repair apparatus.

Composes a flat, JSON-serializable view that a Tauri / web / CLI front-end
can consume directly. Carries enum-typed slots for every dimension the
operator needs to see, plus pointers to lock + evidence artifacts so the
front-end can deep-link audit trails without re-running anything.

This module defines records only. State assembly lives in
``repair_state_model.py``.
"""

from __future__ import annotations

import enum
import json
from dataclasses import asdict, dataclass, field

IDE_REPAIR_STATE_TOKENS = (
    "INTAKE_READY",
    "INTAKE_UNSUPPORTED",
    "VERIFIER_AVAILABLE",
    "VERIFIER_MISSING",
    "MODEL_ROUTE_SELECTED",
    "MODEL_ROUTE_BLOCKED",
    "MODEL_ROUTE_NO_MODEL",
    "PATCH_PLAN_AVAILABLE",
    "PATCH_PLAN_UNAVAILABLE",
    "PATCH_TEMP_APPLIED",
    "PATCH_TEMP_FAILED",
    "PATCH_VERIFIED_TEMP_ONLY",
    "PATCH_VERIFIER_FAILED",
    "SOURCE_APPROVAL_REQUIRED",
    "SOURCE_APPROVAL_ACCEPTED_FIXTURE",
    "SOURCE_MUTATION_BLOCKED",
    "CORPUS_ELIGIBILITY_FALSE",
    "EVIDENCE_AVAILABLE",
)


class IntakeStatus(str, enum.Enum):
    READY = "INTAKE_READY"
    UNSUPPORTED = "INTAKE_UNSUPPORTED"


class VerifierStatus(str, enum.Enum):
    AVAILABLE = "VERIFIER_AVAILABLE"
    MISSING = "VERIFIER_MISSING"


class ModelRouteStatus(str, enum.Enum):
    SELECTED = "MODEL_ROUTE_SELECTED"
    BLOCKED = "MODEL_ROUTE_BLOCKED"
    NO_MODEL = "MODEL_ROUTE_NO_MODEL"


class PatchPlanStatus(str, enum.Enum):
    AVAILABLE = "PATCH_PLAN_AVAILABLE"
    UNAVAILABLE = "PATCH_PLAN_UNAVAILABLE"


class PatchTempStatus(str, enum.Enum):
    APPLIED = "PATCH_TEMP_APPLIED"
    FAILED = "PATCH_TEMP_FAILED"


class PatchVerifierStatus(str, enum.Enum):
    PASSED_TEMP_ONLY = "PATCH_VERIFIED_TEMP_ONLY"
    FAILED = "PATCH_VERIFIER_FAILED"
    SKIPPED = "VERIFIER_MISSING"


class SourceApprovalStatus(str, enum.Enum):
    REQUIRED = "SOURCE_APPROVAL_REQUIRED"
    ACCEPTED_FIXTURE = "SOURCE_APPROVAL_ACCEPTED_FIXTURE"
    MUTATION_BLOCKED = "SOURCE_MUTATION_BLOCKED"


@dataclass(frozen=True)
class EvidencePointers:
    """Lock + evidence file paths the IDE can deep-link."""

    locks: tuple[str, ...] = field(default_factory=tuple)
    evidence_files: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        return {
            "locks": list(self.locks),
            "evidence_files": list(self.evidence_files),
        }


@dataclass(frozen=True)
class IDERepairState:
    """Flat JSON-serializable state record consumed by the IDE."""

    workspace: str
    trace_id: str
    intake: str  # IntakeStatus value
    adapter_name: str
    build_system_id: str
    verifier: str  # VerifierStatus value
    model_route: str  # ModelRouteStatus value
    selected_model_id: str
    patch_plan: str  # PatchPlanStatus value
    patch_temp: str  # PatchTempStatus value
    patch_verifier: str  # PatchVerifierStatus value
    source_approval: str  # SourceApprovalStatus value
    source_mutation_authorized: bool
    corpus_eligibility: str = "CORPUS_ELIGIBILITY_FALSE"
    training_eligible: bool = False
    evidence: EvidencePointers = field(default_factory=EvidencePointers)
    statuses_seen: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["evidence"] = self.evidence.to_dict()
        d["statuses_seen"] = list(self.statuses_seen)
        return d

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    @property
    def is_source_mutation_blocked(self) -> bool:
        return (
            self.source_approval == SourceApprovalStatus.MUTATION_BLOCKED.value
            or not self.source_mutation_authorized
        )
