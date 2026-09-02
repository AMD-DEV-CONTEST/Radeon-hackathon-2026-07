"""Records for REAL_HUMAN_APPROVAL_ADMISSION_LOCK_001."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

REAL_HUMAN_APPROVAL_ADMISSION_STATUS_TOKENS = (
    "REAL_HUMAN_APPROVAL_ACCEPTED",
    "REAL_HUMAN_APPROVAL_REQUIRED",
    "REAL_HUMAN_APPROVAL_REJECTED",
    "REAL_HUMAN_APPROVAL_BLOCKED_STALE",
    "REAL_HUMAN_APPROVAL_BLOCKED_DIFF_MISMATCH",
    "REAL_HUMAN_APPROVAL_BLOCKED_VERIFIER_NOT_PASSED",
    "REAL_HUMAN_APPROVAL_BLOCKED_FIXTURE",
    "REAL_HUMAN_APPROVAL_BLOCKED_TRACE_MISMATCH",
    "REAL_HUMAN_APPROVAL_BLOCKED_OPERATOR_EMPTY",
    "REAL_HUMAN_APPROVAL_BLOCKED_SIGNATURE_INVALID",
)


@dataclass(frozen=True)
class RealHumanApprovalAdmissionRecord:
    decision: str
    trace_id: str
    workspace_identity: str
    diff_hash: str
    verifier_status: str
    operator_identity: str
    operator_signature: str
    signature_kind: str
    is_fixture: bool
    accepted_at: str
    stale_after: str
    source_mutation_authorized: bool = False
    training_eligible: bool = False
    canonical_patch_body_hash: str = ""
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["notes"] = list(self.notes)
        return d

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    @property
    def is_accepted(self) -> bool:
        return self.decision == "REAL_HUMAN_APPROVAL_ACCEPTED"

    @property
    def is_rejected(self) -> bool:
        return self.decision == "REAL_HUMAN_APPROVAL_REJECTED"

    @property
    def is_blocked(self) -> bool:
        return self.decision.startswith("REAL_HUMAN_APPROVAL_BLOCKED_")


__all__ = [
    "REAL_HUMAN_APPROVAL_ADMISSION_STATUS_TOKENS",
    "RealHumanApprovalAdmissionRecord",
]
