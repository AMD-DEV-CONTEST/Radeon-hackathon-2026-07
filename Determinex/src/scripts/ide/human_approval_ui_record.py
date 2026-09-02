"""Records for HUMAN_APPROVAL_PACKET_UI_MODEL_LOCK_001."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

HUMAN_APPROVAL_PACKET_UI_STATUS_TOKENS = (
    "HUMAN_APPROVAL_PACKET_WRITTEN",
    "HUMAN_APPROVAL_REQUIRED",
    "HUMAN_APPROVAL_BLOCKED_MISSING_PACKET",
    "HUMAN_APPROVAL_BLOCKED_STALE_PACKET",
    "HUMAN_APPROVAL_BLOCKED_DIFF_MISMATCH",
    "HUMAN_APPROVAL_BLOCKED_VERIFIER_NOT_PASSED",
)


@dataclass(frozen=True)
class HumanApprovalPacket:
    trace_id: str
    workspace_identity: str
    diff_hash: str
    diff_summary: str
    files_changed: tuple[str, ...]
    verifier_result: str
    model_route_ref: str
    patch_plan_ref: str
    temp_patch_ref: str
    risk_summary: str
    approval_required: bool
    approval_status: str
    operator_identity: str
    operator_signature: str
    timestamp: str
    stale_after: str
    decision: str
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["files_changed"] = list(self.files_changed)
        d["notes"] = list(self.notes)
        return d

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)
