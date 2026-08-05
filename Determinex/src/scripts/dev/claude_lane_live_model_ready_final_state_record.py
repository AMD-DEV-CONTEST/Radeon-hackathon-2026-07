"""Records for CLAUDE_LANE_LIVE_MODEL_READY_FINAL_STATE_LOCK_001."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

CLAUDE_LANE_LIVE_MODEL_READY_FINAL_STATE_TOKENS = (
    "CLAUDE_LANE_LIVE_MODEL_READY_FINAL_STATE_WRITTEN",
    "EXECUTION_SURFACE_CLEAN",
    "MODEL_ROUTING_READY",
    "LIVE_MODEL_ADMISSION_READY_OPT_IN_LOCAL_ONLY",
    "NETWORK_MODELS_BLOCKED_BY_DEFAULT",
    "DIAGNOSE_ONLY_TRACE_READY",
    "PATCH_PLAN_QUARANTINE_READY",
    "TEMP_PATCH_VERIFIER_GATE_READY",
    "SOURCE_MUTATION_BLOCKED_PENDING_HUMAN_APPROVAL",
    "IDE_LIVE_STATE_READY",
    "TRAINING_ELIGIBILITY_BLOCKED_BY_DEFAULT",
    "RELEASE_READINESS_NOT_RELEASED",
    "NEXT_UNBLOCKER_DECLARED",
)


@dataclass(frozen=True)
class ClaudeLaneLiveModelReadyFinalState:
    generated_at: str
    execution_surface: str
    model_routing: str
    live_model_admission: str
    network_models: str
    diagnose_only_trace: str
    patch_plan_quarantine: str
    temp_patch_verifier_gate: str
    source_mutation: str
    ide_live_state: str
    training_eligibility: str
    release_readiness: str
    next_unblocker: str
    upstream_locks_present: tuple[str, ...] = field(default_factory=tuple)
    upstream_locks_missing: tuple[str, ...] = field(default_factory=tuple)
    statuses_seen: tuple[str, ...] = field(default_factory=tuple)
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["upstream_locks_present"] = list(self.upstream_locks_present)
        d["upstream_locks_missing"] = list(self.upstream_locks_missing)
        d["statuses_seen"] = list(self.statuses_seen)
        d["notes"] = list(self.notes)
        return d

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)
