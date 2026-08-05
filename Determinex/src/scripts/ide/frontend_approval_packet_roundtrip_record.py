"""Records for FRONTEND_APPROVAL_PACKET_ROUNDTRIP_LOCK_001."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

FRONTEND_APPROVAL_PACKET_ROUNDTRIP_TOKENS = (
    "APPROVAL_PACKET_ROUNDTRIP_READY",
    "APPROVAL_REJECT_PATH_READY",
    "APPROVAL_FIXTURE_ONLY",
    "APPROVAL_SOURCE_MUTATION_BLOCKED",
    "APPROVAL_STALE_VISIBLE",
    "APPROVAL_DIFF_MISMATCH_VISIBLE",
    "APPROVAL_VERIFIER_FAILED_VISIBLE",
)


@dataclass(frozen=True)
class ApprovalRoundtripStage:
    name: str
    signing_decision: str
    apply_gate_decision: str
    fixture_only: bool
    source_mutation_authorized: bool


@dataclass(frozen=True)
class FrontendApprovalPacketRoundtripTrace:
    workspace: str
    approve_stage: ApprovalRoundtripStage
    reject_stage: ApprovalRoundtripStage
    stale_stage: ApprovalRoundtripStage
    diff_mismatch_stage: ApprovalRoundtripStage
    verifier_failed_stage: ApprovalRoundtripStage
    source_mutation_authorized_anywhere: bool
    training_eligible_anywhere: bool
    statuses_seen: tuple[str, ...] = field(default_factory=tuple)
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["statuses_seen"] = list(self.statuses_seen)
        d["notes"] = list(self.notes)
        return d

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)


__all__ = [
    "FRONTEND_APPROVAL_PACKET_ROUNDTRIP_TOKENS",
    "ApprovalRoundtripStage",
    "FrontendApprovalPacketRoundtripTrace",
]
