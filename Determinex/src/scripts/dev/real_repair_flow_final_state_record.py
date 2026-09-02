"""Records for REAL_REPAIR_FLOW_FINAL_STATE_LOCK_001."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

REAL_REPAIR_FLOW_FINAL_STATE_TOKENS = (
    "REAL_REPAIR_FLOW_FINAL_STATE_WRITTEN",
    "REAL_LOCAL_MODEL_PROVIDER_READY_OR_BLOCKED_WITH_REASON",
    "REAL_MODEL_ADMISSION_READY_OPT_IN",
    "LIVE_DIAGNOSE_READY_ADVISORY_ONLY",
    "PATCH_PLAN_QUARANTINE_READY",
    "TEMP_PATCH_VERIFIER_READY_HUMAN_APPROVAL_REQUIRED",
    "HUMAN_APPROVAL_READY_REAL_SIGNED_ONLY",
    "ROLLBACK_SNAPSHOT_READY",
    "SOURCE_APPLY_AFTER_APPROVAL_READY_GATED",
    "POST_APPLY_VERIFIER_READY",
    "ROLLBACK_STATUS_READY_ON_FAIL",
    "SOURCE_MUTATION_GATED_BY_REAL_APPROVAL",
    "TRAINING_ELIGIBILITY_BLOCKED_BY_DEFAULT",
    "RELEASE_READINESS_NOT_RELEASED",
    "NEXT_UNBLOCKER_DECLARED",
)


@dataclass(frozen=True)
class RealRepairFlowFinalState:
    generated_at: str
    real_local_model_provider: str
    real_model_admission: str
    live_diagnose: str
    patch_plan_quarantine: str
    temp_patch_verifier: str
    human_approval: str
    rollback_snapshot: str
    source_apply_after_approval: str
    post_apply_verifier: str
    rollback_status: str
    source_mutation: str
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


__all__ = [
    "REAL_REPAIR_FLOW_FINAL_STATE_TOKENS",
    "RealRepairFlowFinalState",
]
