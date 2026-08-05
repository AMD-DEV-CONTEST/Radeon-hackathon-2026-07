"""Records for REAL_PATCH_PLAN_QUARANTINE_LOCK_001."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

REAL_PATCH_PLAN_QUARANTINE_STATUS_TOKENS = (
    "REAL_PATCH_PLAN_QUARANTINED",
    "REAL_PATCH_PLAN_BLOCKED_SCHEMA_INVALID",
    "REAL_PATCH_PLAN_BLOCKED_PATH_ESCAPE",
    "REAL_PATCH_PLAN_BLOCKED_UNSUPPORTED_OPERATION",
    "REAL_PATCH_PLAN_BLOCKED_NO_MODEL",
    "REAL_PATCH_PLAN_BLOCKED_NOT_OPTED_IN",
)


@dataclass(frozen=True)
class RealQuarantinedPatchEntry:
    operation: str
    path: str
    new_content_chars: int
    rejection_reason: str = ""


@dataclass(frozen=True)
class RealPatchPlanQuarantineRecord:
    decision: str
    workspace: str
    model_id: str
    provider: str
    accepted: tuple[RealQuarantinedPatchEntry, ...]
    rejected: tuple[RealQuarantinedPatchEntry, ...]
    quarantined: bool = True
    output_trusted: bool = False
    patch_applied: bool = False
    source_mutation_authorized: bool = False
    training_eligible: bool = False
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["accepted"] = [asdict(e) for e in self.accepted]
        d["rejected"] = [asdict(e) for e in self.rejected]
        d["notes"] = list(self.notes)
        return d

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    @property
    def is_quarantined(self) -> bool:
        return self.decision == "REAL_PATCH_PLAN_QUARANTINED"

    @property
    def is_blocked(self) -> bool:
        return self.decision.startswith("REAL_PATCH_PLAN_BLOCKED_")


__all__ = [
    "REAL_PATCH_PLAN_QUARANTINE_STATUS_TOKENS",
    "RealPatchPlanQuarantineRecord",
    "RealQuarantinedPatchEntry",
]
