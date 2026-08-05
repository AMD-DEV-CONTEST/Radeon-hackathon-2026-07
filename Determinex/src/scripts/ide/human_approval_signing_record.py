"""Records for IDE_HUMAN_APPROVAL_SIGNING_FLOW_LOCK_001."""

from __future__ import annotations

import enum
import json
from dataclasses import asdict, dataclass, field

IDE_HUMAN_APPROVAL_SIGNING_STATUS_TOKENS = (
    "IDE_APPROVAL_PACKET_READY",
    "IDE_APPROVAL_REQUIRED",
    "IDE_APPROVAL_REJECTED",
    "IDE_APPROVAL_BLOCKED_STALE_PACKET",
    "IDE_APPROVAL_BLOCKED_DIFF_MISMATCH",
    "IDE_APPROVAL_BLOCKED_VERIFIER_NOT_PASSED",
    "IDE_APPROVAL_FIXTURE_ONLY",
    "IDE_APPROVAL_BLOCKED_OPERATOR_EMPTY",
)


class ApprovalAction(str, enum.Enum):
    APPROVE = "approve"
    REJECT = "reject"
    DEFERRED = "deferred"


@dataclass(frozen=True)
class IDEHumanApprovalSigningRecord:
    decision: str
    action: str
    operator_identity: str
    operator_signature: str
    trace_id: str
    workspace_identity: str
    diff_hash: str
    verifier_status: str
    timestamp: str
    fixture_only: bool = True
    source_mutation_authorized: bool = False
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
