"""Records for DETERMINEX_IDE_FRONTEND_READY_FINAL_STATE_LOCK_001."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

DETERMINEX_IDE_FRONTEND_READY_FINAL_STATE_TOKENS = (
    "DETERMINEX_IDE_FRONTEND_READY_FINAL_STATE_WRITTEN",
    "TAURI_RUST_COMMAND_BRIDGE_READY",
    "FRONTEND_REPAIR_PANEL_SHELL_READY",
    "FRONTEND_WORKSPACE_STATUS_PANEL_READY",
    "FRONTEND_MODEL_ROUTE_PANEL_READY",
    "FRONTEND_DIAGNOSE_AND_PATCH_PLAN_FLOW_READY",
    "FRONTEND_TEMP_VERIFY_PANEL_READY",
    "FRONTEND_HUMAN_APPROVAL_PANEL_READY",
    "FRONTEND_SOURCE_APPLY_DRY_RUN_PANEL_READY",
    "FRONTEND_EVIDENCE_VIEWER_READY",
    "LOCAL_MODEL_SETTINGS_PANEL_READY",
    "FRONTEND_END_TO_END_REPAIR_FLOW_SMOKE_READY",
    "SOURCE_MUTATION_BLOCKED_PENDING_REAL_HUMAN_APPROVAL",
    "TRAINING_ELIGIBILITY_BLOCKED_BY_DEFAULT",
    "LIVE_MODEL_CALL_BLOCKED_BY_DEFAULT",
    "NETWORK_PROVIDER_BLOCKED_BY_DEFAULT",
    "RELEASE_READINESS_NOT_RELEASED",
    "NEXT_UNBLOCKER_DECLARED",
)


@dataclass(frozen=True)
class DeterminexIDEFrontendReadyFinalState:
    generated_at: str
    tauri_rust_command_bridge: str
    frontend_repair_panel_shell: str
    frontend_workspace_status_panel: str
    frontend_model_route_panel: str
    frontend_diagnose_and_patch_plan_flow: str
    frontend_temp_verify_panel: str
    frontend_human_approval_panel: str
    frontend_source_apply_dry_run_panel: str
    frontend_evidence_viewer: str
    local_model_settings_panel: str
    frontend_end_to_end_repair_flow_smoke: str
    source_mutation: str
    training_eligibility: str
    live_model_call: str
    network_provider: str
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
    "DETERMINEX_IDE_FRONTEND_READY_FINAL_STATE_TOKENS",
    "DeterminexIDEFrontendReadyFinalState",
]
