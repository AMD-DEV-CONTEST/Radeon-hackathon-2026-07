"""Records for CLAUDE_OPERATOR_IDENTITY_BOUNDING_LOCK_001.

CLAUDE-AUTH-014 deferred risk: ``operator_identity`` on
``RealHumanApprovalAdmissionRecord`` is a free string. Any caller
that supplies ``operator_identity="ryan"`` and a valid HMAC over
a payload that happens to include that string passes the
admission gate.

This lock bounds the *runtime check* an approval-handling rung
must satisfy before treating an admission as a real-operator
admission. It does not relax or replace the HMAC gate. It adds:

  * A typed BoundedOperatorIdentity record (operator_id, display
    name, signing key/ref, timestamp, workspace identity hash,
    approval payload hash).
  * A check function that proves an admission is bound to that
    identity (signing kind == real_local_hmac, payload hash
    matches, workspace hash matches).
  * Refusal codes for the missing/free-string-only cases.

This rung does NOT mutate any existing source. It is a
boundary-validator a downstream rung (e.g. the apply gate) can
require.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

OPERATOR_IDENTITY_BOUNDING_STATUS_TOKENS = (
    "OPERATOR_IDENTITY_BOUNDING_PASSED",
    "OPERATOR_IDENTITY_BLOCKED_FREE_STRING_ONLY",
    "OPERATOR_IDENTITY_BLOCKED_MISSING_SIGNING_REF",
    "OPERATOR_IDENTITY_BLOCKED_PAYLOAD_MISMATCH",
    "OPERATOR_IDENTITY_BLOCKED_WORKSPACE_MISMATCH",
    "OPERATOR_IDENTITY_BLOCKED_STALE",
    "OPERATOR_IDENTITY_BLOCKED_MALFORMED_IDENTITY",
)


# Bounded length on operator_id and display_name to refuse pathological
# strings (NUL bytes, huge identities trying to attack the logs).
_MAX_OPERATOR_ID_LEN = 128
_MAX_DISPLAY_NAME_LEN = 256


@dataclass(frozen=True)
class BoundedOperatorIdentity:
    """The fields a Claude-source-mutation approval is bound to."""

    operator_id: str
    display_name: str
    signing_key_ref: str  # hex sha256 of the per-host secret file path
    timestamp: str
    workspace_identity_hash: str
    approval_payload_hash: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    @property
    def is_well_formed(self) -> bool:
        if not isinstance(self.operator_id, str) or not self.operator_id:
            return False
        if "\x00" in self.operator_id or len(self.operator_id) > _MAX_OPERATOR_ID_LEN:
            return False
        if not isinstance(self.display_name, str):
            return False
        if "\x00" in self.display_name or len(self.display_name) > _MAX_DISPLAY_NAME_LEN:
            return False
        if not isinstance(self.signing_key_ref, str) or len(self.signing_key_ref) != 64:
            return False
        try:
            int(self.signing_key_ref, 16)
        except ValueError:
            return False
        if not isinstance(self.timestamp, str) or not self.timestamp:
            return False
        if (
            not isinstance(self.workspace_identity_hash, str)
            or len(self.workspace_identity_hash) != 64
        ):
            return False
        try:
            int(self.workspace_identity_hash, 16)
        except ValueError:
            return False
        if not isinstance(self.approval_payload_hash, str) or len(self.approval_payload_hash) != 64:
            return False
        try:
            int(self.approval_payload_hash, 16)
        except ValueError:
            return False
        return True


@dataclass(frozen=True)
class OperatorIdentityBoundingRecord:
    decision: str
    operator_id: str
    workspace_identity_hash: str
    approval_payload_hash: str
    signing_key_ref: str
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
        return self.decision == "OPERATOR_IDENTITY_BOUNDING_PASSED"

    @property
    def is_blocked(self) -> bool:
        return self.decision.startswith("OPERATOR_IDENTITY_BLOCKED_")


__all__ = [
    "OPERATOR_IDENTITY_BOUNDING_STATUS_TOKENS",
    "BoundedOperatorIdentity",
    "OperatorIdentityBoundingRecord",
]
