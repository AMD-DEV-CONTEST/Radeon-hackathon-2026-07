"""Records for IDE_PATCH_PLAN_FLOW_LOCK_001."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

IDE_PATCH_PLAN_FLOW_STATUS_TOKENS = (
    "IDE_PATCH_PLAN_QUARANTINED",
    "IDE_PATCH_PLAN_BLOCKED_NO_MODEL",
    "IDE_PATCH_PLAN_BLOCKED_NOT_OPTED_IN",
    "IDE_PATCH_PLAN_BLOCKED_SCHEMA_INVALID",
    "IDE_PATCH_PLAN_BLOCKED_PATH_ESCAPE",
    "IDE_PATCH_PLAN_SOURCE_UNCHANGED",
)


@dataclass(frozen=True)
class IDEPatchPlanFlowRecord:
    decision: str
    workspace: str
    entries_quarantined: int
    plan_decision: str
    trusted: bool = False
    applied_to_source: bool = False
    source_mutation_authorized: bool = False
    training_eligible: bool = False
    statuses_seen: tuple[str, ...] = field(default_factory=tuple)
    evidence_refs: tuple[str, ...] = field(default_factory=tuple)
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["statuses_seen"] = list(self.statuses_seen)
        d["evidence_refs"] = list(self.evidence_refs)
        d["notes"] = list(self.notes)
        return d

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)
