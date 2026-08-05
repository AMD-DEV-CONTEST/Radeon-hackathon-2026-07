"""IDE-facing live-model repair flow state record."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

IDE_LIVE_MODEL_REPAIR_FLOW_STATE_TOKENS = (
    "LIVE_MODEL_NOT_ADMITTED",
    "LIVE_MODEL_ADMITTED",
    "DIAGNOSIS_ADVISORY_AVAILABLE",
    "PATCH_PLAN_QUARANTINED",
    "TEMP_PATCH_VERIFIER_FAILED",
    "TEMP_PATCH_VERIFIER_PASSED",
    "HUMAN_APPROVAL_REQUIRED",
    "SOURCE_MUTATION_BLOCKED",
    "TRAINING_ELIGIBLE_FALSE",
    "EVIDENCE_AVAILABLE",
)


@dataclass(frozen=True)
class IDELiveModelRepairFlowState:
    workspace: str
    live_admission: str
    diagnosis_advisory: str
    patch_plan: str
    temp_patch_verifier: str
    human_approval: str
    source_mutation: str
    training_eligibility: str
    statuses_seen: tuple[str, ...] = field(default_factory=tuple)
    evidence_locks: tuple[str, ...] = field(default_factory=tuple)
    evidence_files: tuple[str, ...] = field(default_factory=tuple)
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["statuses_seen"] = list(self.statuses_seen)
        d["evidence_locks"] = list(self.evidence_locks)
        d["evidence_files"] = list(self.evidence_files)
        d["notes"] = list(self.notes)
        return d

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)
