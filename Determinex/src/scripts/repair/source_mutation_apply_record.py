"""Records for SOURCE_MUTATION_APPLY_DRY_RUN_LOCK_001."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

SOURCE_APPLY_DRY_RUN_STATUS_TOKENS = (
    "SOURCE_APPLY_DRY_RUN_READY",
    "SOURCE_APPLY_DRY_RUN_BLOCKED_NO_APPROVAL",
    "SOURCE_APPLY_DRY_RUN_BLOCKED_STALE_SOURCE",
    "SOURCE_APPLY_DRY_RUN_BLOCKED_DIFF_MISMATCH",
    "SOURCE_APPLY_DRY_RUN_BLOCKED_VERIFIER_NOT_PASSED",
    "SOURCE_APPLY_DRY_RUN_SOURCE_UNCHANGED",
)


@dataclass(frozen=True)
class SourceApplyDryRunRecord:
    decision: str
    workspace: str
    files_would_change: tuple[str, ...] = field(default_factory=tuple)
    conflicts: tuple[str, ...] = field(default_factory=tuple)
    source_unchanged: bool = True
    training_eligible: bool = False
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["files_would_change"] = list(self.files_would_change)
        d["conflicts"] = list(self.conflicts)
        d["notes"] = list(self.notes)
        return d

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)
