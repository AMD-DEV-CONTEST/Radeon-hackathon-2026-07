"""Records for DETERMINEX_IDE_CONSUMER_READY_FINAL_STATE_LOCK_001."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

DETERMINEX_IDE_CONSUMER_READY_FINAL_STATE_TOKENS = (
    "DETERMINEX_IDE_CONSUMER_READY_FINAL_STATE_WRITTEN",
    "LOCAL_MODEL_CONFIG_READY_OPT_IN",
    "LOCAL_PROVIDER_SMOKE_READY",
    "LIVE_DIAGNOSE_COMMAND_READY_OPT_IN",
    "PATCH_PLAN_COMMAND_READY_QUARANTINE",
    "TEMP_PATCH_VERIFY_COMMAND_READY_TEMP_ONLY",
    "HUMAN_APPROVAL_UI_MODEL_READY",
    "IDE_BACKEND_COMMAND_SURFACE_READY",
    "SOURCE_APPLY_DRY_RUN_READY_NO_MUTATION",
    "IDE_CONSUMER_FLOW_TRACE_READY",
    "SOURCE_MUTATION_BLOCKED_PENDING_REAL_HUMAN_APPROVAL",
    "TRAINING_ELIGIBILITY_BLOCKED_BY_DEFAULT",
    "RELEASE_READINESS_NOT_RELEASED",
    "NEXT_UNBLOCKER_DECLARED",
)


@dataclass(frozen=True)
class DeterminexIDEConsumerReadyFinalState:
    generated_at: str
    local_model_config: str
    local_provider_smoke: str
    live_diagnose_command: str
    patch_plan_command: str
    temp_patch_verify_command: str
    human_approval_ui_model: str
    ide_backend_command_surface: str
    source_apply_dry_run: str
    ide_consumer_flow_trace: str
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
