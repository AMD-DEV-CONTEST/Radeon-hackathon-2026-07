"""Records for OPT_IN_PATCH_PLAN_COMMAND_LOCK_001."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

OPT_IN_PATCH_PLAN_STATUS_TOKENS = (
    "OPT_IN_PATCH_PLAN_QUARANTINED",
    "OPT_IN_PATCH_PLAN_BLOCKED_NO_MODEL",
    "OPT_IN_PATCH_PLAN_BLOCKED_NOT_OPTED_IN",
    "OPT_IN_PATCH_PLAN_BLOCKED_SCHEMA_INVALID",
    "OPT_IN_PATCH_PLAN_BLOCKED_PATH_ESCAPE",
    "OPT_IN_PATCH_PLAN_BLOCKED_PROVIDER_UNAVAILABLE",
)


@dataclass(frozen=True)
class OptInPatchPlanRecord:
    decision: str
    workspace: str
    config_path: str
    provider: str
    model_id: str
    plan_decision: str  # reflects underlying quarantine status
    entries_quarantined: int = 0
    trusted: bool = False
    applied_to_source: bool = False
    source_mutation_authorized: bool = False
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
