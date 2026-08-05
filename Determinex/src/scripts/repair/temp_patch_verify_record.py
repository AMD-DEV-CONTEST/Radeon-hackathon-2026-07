"""Records for TEMP_PATCH_VERIFY_COMMAND_LOCK_001."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

TEMP_PATCH_VERIFY_STATUS_TOKENS = (
    "TEMP_PATCH_VERIFY_PASSED_TEMP_ONLY",
    "TEMP_PATCH_VERIFY_FAILED",
    "TEMP_PATCH_VERIFY_BLOCKED_NO_PLAN",
    "TEMP_PATCH_VERIFY_BLOCKED_PATH_ESCAPE",
    "TEMP_PATCH_VERIFY_SOURCE_UNCHANGED",
    "TEMP_PATCH_VERIFY_HUMAN_APPROVAL_REQUIRED",
)


@dataclass(frozen=True)
class TempPatchVerifyRecord:
    decision: str
    workspace: str
    temp_workspace: str
    verifier_status: str
    unified_diff: str
    source_unchanged_confirmed: bool
    human_approval_required: bool
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
