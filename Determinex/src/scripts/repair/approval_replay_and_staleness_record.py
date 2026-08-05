"""Records for CLAUDE_APPROVAL_REPLAY_AND_STALENESS_LOCK_001.

CLAUDE-AUTH-016 deferred risk: approval admissions have no
replay-protection / nonce — the same valid signature could be
re-used across patches. CLAUDE-AUTH-013 deferred risk:
``stale_after`` is whatever the packet builder chose, with no
minimum freshness floor enforced at the gate.

This rung defines a typed ApprovalPacket with mandatory
identifiers and a verifier that refuses replayed or stale packets
across:

  * reused approval nonce / monotonic id
  * stale-beyond-policy-window timestamps
  * workspace mismatch
  * canonical patch body mismatch
  * verifier/snapshot ref mismatch
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

APPROVAL_REPLAY_AND_STALENESS_STATUS_TOKENS = (
    "APPROVAL_REPLAY_STALENESS_PASSED",
    "APPROVAL_REPLAY_BLOCKED_REUSED_NONCE",
    "APPROVAL_REPLAY_BLOCKED_STALE_APPROVAL",
    "APPROVAL_REPLAY_BLOCKED_WORKSPACE_MISMATCH",
    "APPROVAL_REPLAY_BLOCKED_PATCH_BODY_MISMATCH",
    "APPROVAL_REPLAY_BLOCKED_VERIFIER_REF_MISMATCH",
    "APPROVAL_REPLAY_BLOCKED_SNAPSHOT_REF_MISMATCH",
    "APPROVAL_REPLAY_BLOCKED_MALFORMED_PACKET",
)


@dataclass(frozen=True)
class ApprovalPacket:
    """The fields an apply gate binds to when accepting an approval.

    A packet's ``approval_id`` is the monotonic nonce. The
    accompanying ``timestamp`` (epoch seconds) is the moment the
    packet was issued; it is compared against the verifier's
    ``now_epoch_s`` against a policy window.
    """

    approval_id: str
    timestamp_epoch_s: int
    trace_id: str
    workspace_identity_hash: str
    canonical_patch_body_hash: str
    verifier_ref: str
    rollback_snapshot_ref: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    @property
    def is_well_formed(self) -> bool:
        if not isinstance(self.approval_id, str) or not self.approval_id:
            return False
        if "\x00" in self.approval_id or len(self.approval_id) > 128:
            return False
        if not isinstance(self.timestamp_epoch_s, int) or self.timestamp_epoch_s <= 0:
            return False
        for f in (
            self.trace_id,
            self.workspace_identity_hash,
            self.canonical_patch_body_hash,
            self.verifier_ref,
        ):
            if not isinstance(f, str) or not f:
                return False
        # rollback_snapshot_ref MAY be empty pre-snapshot (the apply
        # gate sees a snapshot ref; the admission may not).
        if not isinstance(self.rollback_snapshot_ref, str):
            return False
        return True


@dataclass(frozen=True)
class ApprovalReplayAndStalenessRecord:
    decision: str
    approval_id: str
    workspace_identity_hash: str
    canonical_patch_body_hash: str
    verifier_ref: str
    rollback_snapshot_ref: str
    age_seconds: int
    max_age_seconds: int
    source_mutation_authorized: bool = False
    training_eligible: bool = False
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["notes"] = list(self.notes)
        return d

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    @property
    def is_passed(self) -> bool:
        return self.decision == "APPROVAL_REPLAY_STALENESS_PASSED"

    @property
    def is_blocked(self) -> bool:
        return self.decision.startswith("APPROVAL_REPLAY_BLOCKED_")


__all__ = [
    "APPROVAL_REPLAY_AND_STALENESS_STATUS_TOKENS",
    "ApprovalPacket",
    "ApprovalReplayAndStalenessRecord",
]
