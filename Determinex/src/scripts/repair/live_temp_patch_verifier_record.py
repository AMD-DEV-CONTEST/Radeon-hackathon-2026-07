"""Records for LIVE_MODEL_TEMP_PATCH_VERIFIER_GATE_LOCK_001."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

LIVE_TEMP_PATCH_VERIFIER_STATUS_TOKENS = (
    "LIVE_PATCH_TEMP_APPLIED",
    "LIVE_PATCH_VERIFIER_FAILED",
    "LIVE_PATCH_VERIFIER_PASSED_TEMP_ONLY",
    "LIVE_PATCH_BLOCKED_NO_QUARANTINED_PLAN",
    "LIVE_PATCH_BLOCKED_SOURCE_MUTATION",
    "LIVE_PATCH_BLOCKED_SAFE_PATCH_REJECTED",
    "LIVE_PATCH_ROLLED_BACK",
    "LIVE_PATCH_SOURCE_UNCHANGED_CONFIRMED",
    "LIVE_PATCH_HUMAN_APPROVAL_REQUIRED",
    "LIVE_PATCH_TRAINING_ELIGIBLE_FALSE",
)


@dataclass(frozen=True)
class LiveTempPatchVerifierResult:
    decision: str
    workspace: str
    temp_workspace: str
    safe_patch_status: str
    verifier_status: str
    unified_diff: str
    rolled_back: bool
    source_unchanged_confirmed: bool
    human_approval_required: bool
    statuses_seen: tuple[str, ...] = field(default_factory=tuple)
    plan_admission_ref: str = ""
    training_eligible: bool = False
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["statuses_seen"] = list(self.statuses_seen)
        d["notes"] = list(self.notes)
        return d

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    @property
    def is_passed_temp_only(self) -> bool:
        return self.decision == "LIVE_PATCH_VERIFIER_PASSED_TEMP_ONLY"

    @property
    def is_blocked(self) -> bool:
        return self.decision.startswith("LIVE_PATCH_BLOCKED_")
