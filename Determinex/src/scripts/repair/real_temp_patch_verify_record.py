"""Records for REAL_TEMP_PATCH_VERIFY_LOCK_001."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

REAL_TEMP_PATCH_VERIFY_STATUS_TOKENS = (
    "REAL_TEMP_PATCH_VERIFIER_PASSED",
    "REAL_TEMP_PATCH_VERIFIER_FAILED",
    "REAL_TEMP_PATCH_SOURCE_UNCHANGED",
    "REAL_TEMP_PATCH_HUMAN_APPROVAL_REQUIRED",
    "REAL_TEMP_PATCH_BLOCKED_NOT_QUARANTINED",
    "REAL_TEMP_PATCH_BLOCKED_APPLY_REJECTED",
)


@dataclass(frozen=True)
class RealTempPatchVerifyRecord:
    decision: str
    workspace: str
    temp_workspace: str
    verifier_status: str
    unified_diff: str
    applied_paths: tuple[str, ...]
    original_unchanged: bool
    original_sha256_before: str
    original_sha256_after: str
    human_approval_required: bool
    source_mutation_authorized: bool = False
    training_eligible: bool = False
    statuses_seen: tuple[str, ...] = field(default_factory=tuple)
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["applied_paths"] = list(self.applied_paths)
        d["statuses_seen"] = list(self.statuses_seen)
        d["notes"] = list(self.notes)
        return d

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    @property
    def is_passed(self) -> bool:
        return self.decision == "REAL_TEMP_PATCH_VERIFIER_PASSED"

    @property
    def is_failed(self) -> bool:
        return self.decision == "REAL_TEMP_PATCH_VERIFIER_FAILED"

    @property
    def is_blocked(self) -> bool:
        return self.decision.startswith("REAL_TEMP_PATCH_BLOCKED_")


__all__ = [
    "REAL_TEMP_PATCH_VERIFY_STATUS_TOKENS",
    "RealTempPatchVerifyRecord",
]
