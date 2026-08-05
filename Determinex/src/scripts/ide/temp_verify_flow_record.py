"""Records for IDE_TEMP_VERIFY_FLOW_LOCK_001."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

IDE_TEMP_VERIFY_FLOW_STATUS_TOKENS = (
    "IDE_TEMP_VERIFY_RUNNING",
    "IDE_TEMP_VERIFY_FAILED",
    "IDE_TEMP_VERIFY_PASSED_TEMP_ONLY",
    "IDE_TEMP_VERIFY_SOURCE_UNCHANGED",
    "IDE_TEMP_VERIFY_HUMAN_APPROVAL_REQUIRED",
    "IDE_TEMP_VERIFY_BLOCKED_NO_PLAN",
)


@dataclass(frozen=True)
class IDETempVerifyFlowRecord:
    decision: str
    workspace: str
    temp_workspace: str
    verifier_status: str
    unified_diff: str
    source_unchanged: bool
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
