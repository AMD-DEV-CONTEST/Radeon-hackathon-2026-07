"""Records for IDE_SOURCE_APPLY_GATE_FLOW_LOCK_001."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

IDE_SOURCE_APPLY_GATE_STATUS_TOKENS = (
    "IDE_SOURCE_APPLY_BLOCKED_NO_APPROVAL",
    "IDE_SOURCE_APPLY_BLOCKED_STALE_SOURCE",
    "IDE_SOURCE_APPLY_BLOCKED_DIFF_MISMATCH",
    "IDE_SOURCE_APPLY_BLOCKED_VERIFIER_NOT_PASSED",
    "IDE_SOURCE_APPLY_DRY_RUN_READY",
    "IDE_SOURCE_APPLY_SOURCE_UNCHANGED",
    "IDE_SOURCE_APPLY_FIXTURE_ONLY",
    "IDE_SOURCE_APPLY_BLOCKED_NOT_SIGNED",
)


@dataclass(frozen=True)
class IDESourceApplyGateRecord:
    decision: str
    workspace: str
    files_would_change: tuple[str, ...] = field(default_factory=tuple)
    source_unchanged: bool = True
    fixture_only: bool = True
    source_mutation_authorized: bool = False
    training_eligible: bool = False
    statuses_seen: tuple[str, ...] = field(default_factory=tuple)
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["files_would_change"] = list(self.files_would_change)
        d["statuses_seen"] = list(self.statuses_seen)
        d["notes"] = list(self.notes)
        return d

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)
