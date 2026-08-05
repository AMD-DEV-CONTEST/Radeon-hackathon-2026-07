"""Records for REAL_APPROVAL_APPLY_POST_VERIFY_TRACE_LOCK_001."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

REAL_APPROVAL_APPLY_POST_VERIFY_TRACE_STATUS_TOKENS = (
    "REAL_APPROVAL_REQUIRED",
    "REAL_APPROVAL_APPLY_POST_VERIFY_PASSED",
    "REAL_APPROVAL_APPLY_POST_VERIFY_FAILED_ROLLBACK_REQUIRED",
    "REAL_APPROVAL_APPLY_BLOCKED_NO_APPROVAL",
    "REAL_APPROVAL_APPLY_BLOCKED_MISMATCH",
    "REAL_APPROVAL_APPLY_BLOCKED_NO_TEMP_VERIFY",
    "REAL_APPROVAL_APPLY_BLOCKED_NO_VERIFIER",
)


@dataclass(frozen=True)
class RealApprovalApplyPostVerifyTraceRecord:
    decision: str
    workspace_identity: str
    approval_decision: str
    temp_verify_decision: str
    rollback_snapshot_decision: str
    apply_decision: str
    post_apply_decision: str
    rollback_execution_decision: str
    source_mutation_applied: bool
    rollback_executed: bool
    training_eligible: bool = False
    statuses_seen: tuple[str, ...] = field(default_factory=tuple)
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["statuses_seen"] = list(self.statuses_seen)
        d["notes"] = list(self.notes)
        return d

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    @property
    def is_passed(self) -> bool:
        return self.decision == "REAL_APPROVAL_APPLY_POST_VERIFY_PASSED"

    @property
    def needs_rollback(self) -> bool:
        return self.decision == "REAL_APPROVAL_APPLY_POST_VERIFY_FAILED_ROLLBACK_REQUIRED"

    @property
    def is_blocked(self) -> bool:
        return self.decision.startswith("REAL_APPROVAL_APPLY_BLOCKED_")


__all__ = [
    "REAL_APPROVAL_APPLY_POST_VERIFY_TRACE_STATUS_TOKENS",
    "RealApprovalApplyPostVerifyTraceRecord",
]
