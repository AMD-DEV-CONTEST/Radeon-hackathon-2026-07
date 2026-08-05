"""Approval packet + gate decision records.

The approval packet is what an operator (eventually, an IDE user) signs
to authorize applying a previously-verified temp patch onto the
original repo. The gate decision is the immutable record the apparatus
emits — either allowing or refusing the original-repo write.

This module defines records only. The gate logic lives in
``human_approval_gate.py``. Neither module ever writes to the original
repo — the IDE/CLI layer that *consumes* a SOURCE_MUTATION_APPROVAL_
ACCEPTED_FIXTURE decision still has to do that as a separate, audited
step.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field

HUMAN_APPROVAL_STATUS_TOKENS = (
    "SOURCE_MUTATION_APPROVAL_REQUIRED",
    "SOURCE_MUTATION_APPROVAL_ACCEPTED_FIXTURE",
    "SOURCE_MUTATION_BLOCKED_MISSING_APPROVAL",
    "SOURCE_MUTATION_BLOCKED_DIFF_MISMATCH",
    "SOURCE_MUTATION_BLOCKED_STALE_TRACE",
    "SOURCE_MUTATION_BLOCKED_VERIFIER_NOT_PASSED",
    "SOURCE_MUTATION_BLOCKED_REPO_MISMATCH",
    "SOURCE_MUTATION_BLOCKED_TRACE_ID_MISMATCH",
    "SOURCE_MUTATION_BLOCKED_OPERATOR_EMPTY",
)


def diff_hash(diff: str) -> str:
    return hashlib.sha256(diff.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ApprovalPacket:
    """Immutable approval packet.

    ``trace_id``, ``diff_sha256``, and ``workspace_identity`` must match
    the trace being approved bit-for-bit. ``verifier_status`` must
    indicate the verifier passed on the temp workspace.
    """

    trace_id: str
    workspace_identity: str
    diff_sha256: str
    verifier_status: str
    timestamp_utc: str
    operator: str
    approval_token: str
    fixture: bool = True  # tests always set True; real ops would set False (deferred)
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["notes"] = list(self.notes)
        return d

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)


@dataclass(frozen=True)
class ApprovalGateDecision:
    decision: str
    reason: str = ""
    trace_id: str = ""
    workspace_identity: str = ""
    diff_sha256: str = ""
    verifier_status: str = ""
    operator: str = ""
    fixture: bool = True
    source_mutation_authorized: bool = False
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["notes"] = list(self.notes)
        return d

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    @property
    def is_blocked(self) -> bool:
        return self.decision.startswith("SOURCE_MUTATION_BLOCKED_")

    @property
    def is_accepted(self) -> bool:
        return self.decision == "SOURCE_MUTATION_APPROVAL_ACCEPTED_FIXTURE"
