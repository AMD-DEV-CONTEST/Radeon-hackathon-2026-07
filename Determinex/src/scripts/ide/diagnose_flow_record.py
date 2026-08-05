"""Records for IDE_DIAGNOSE_FLOW_LOCK_001."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

IDE_DIAGNOSE_FLOW_STATUS_TOKENS = (
    "IDE_DIAGNOSE_DRY_RUN_READY",
    "IDE_DIAGNOSE_LIVE_OPT_IN_READY",
    "IDE_DIAGNOSE_BLOCKED_NO_MODEL",
    "IDE_DIAGNOSE_BLOCKED_NOT_OPTED_IN",
    "IDE_DIAGNOSE_ADVISORY_AVAILABLE",
    "IDE_DIAGNOSE_SOURCE_UNCHANGED",
    "IDE_DIAGNOSE_BLOCKED_UNSUPPORTED_TASK",
)


@dataclass(frozen=True)
class IDEDiagnoseFlowRecord:
    decision: str
    workspace: str
    task_class: str
    mode: str  # "dry_run" | "live_opt_in"
    advisory_payload: dict[str, object] = field(default_factory=dict)
    advisory_only: bool = True
    patch_generated: bool = False
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
