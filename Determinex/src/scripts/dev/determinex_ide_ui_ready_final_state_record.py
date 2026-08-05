"""Records for DETERMINEX_IDE_UI_READY_FINAL_STATE_LOCK_001."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

DETERMINEX_IDE_UI_READY_FINAL_STATE_TOKENS = (
    "DETERMINEX_IDE_UI_READY_FINAL_STATE_WRITTEN",
    "WORKSPACE_OPEN_FLOW_READY",
    "MODEL_ROUTE_PANEL_READY",
    "DIAGNOSE_FLOW_READY",
    "PATCH_PLAN_FLOW_READY_QUARANTINE",
    "TEMP_VERIFY_FLOW_READY_TEMP_ONLY",
    "HUMAN_APPROVAL_SIGNING_FLOW_READY",
    "SOURCE_APPLY_GATE_FLOW_READY_DRY_RUN_ONLY",
    "TAURI_BACKEND_BRIDGE_READY",
    "FRONTEND_STATE_CONTRACT_READY",
    "APPROVAL_UX_COPY_READY",
    "END_TO_END_UI_FLOW_TRACE_READY",
    "SOURCE_MUTATION_BLOCKED_PENDING_REAL_HUMAN_APPROVAL",
    "TRAINING_ELIGIBILITY_BLOCKED_BY_DEFAULT",
    "RELEASE_READINESS_NOT_RELEASED",
    "NEXT_UNBLOCKER_DECLARED",
)


@dataclass(frozen=True)
class DeterminexIDEUIReadyFinalState:
    generated_at: str
    workspace_open_flow: str
    model_route_panel: str
    diagnose_flow: str
    patch_plan_flow: str
    temp_verify_flow: str
    human_approval_signing_flow: str
    source_apply_gate_flow: str
    tauri_backend_bridge: str
    frontend_state_contract: str
    approval_ux_copy: str
    end_to_end_ui_flow_trace: str
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
