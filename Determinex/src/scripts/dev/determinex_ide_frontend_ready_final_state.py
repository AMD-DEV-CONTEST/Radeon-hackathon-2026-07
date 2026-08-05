"""Final-state assembly for the Determinex IDE real-frontend-ready campaign.

Consolidates the 11 rungs of the real-frontend campaign plus the prior
UI-ready foundation into a single DeterminexIDEFrontendReadyFinalState.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from .determinex_ide_frontend_ready_final_state_record import (
    DETERMINEX_IDE_FRONTEND_READY_FINAL_STATE_TOKENS,
    DeterminexIDEFrontendReadyFinalState,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_LOCKS_DIR = _REPO_ROOT / "locks" / "sentinel"


_UPSTREAM_LOCKS: tuple[str, ...] = (
    "TAURI_RUST_COMMAND_BRIDGE_LOCK_001",
    "FRONTEND_REPAIR_PANEL_SHELL_LOCK_001",
    "FRONTEND_WORKSPACE_STATUS_PANEL_LOCK_001",
    "FRONTEND_MODEL_ROUTE_PANEL_LOCK_001",
    "FRONTEND_DIAGNOSE_AND_PATCH_PLAN_FLOW_LOCK_001",
    "FRONTEND_TEMP_VERIFY_PANEL_LOCK_001",
    "FRONTEND_HUMAN_APPROVAL_PANEL_LOCK_001",
    "FRONTEND_SOURCE_APPLY_DRY_RUN_PANEL_LOCK_001",
    "FRONTEND_EVIDENCE_VIEWER_LOCK_001",
    "LOCAL_MODEL_SETTINGS_PANEL_LOCK_001",
    "FRONTEND_END_TO_END_REPAIR_FLOW_SMOKE_LOCK_001",
    "DETERMINEX_IDE_UI_READY_FINAL_STATE_LOCK_001",
)


def _present(lock_name: str) -> bool:
    return (_LOCKS_DIR / f"{lock_name}.json").is_file()


def assemble_frontend_ready_final_state() -> DeterminexIDEFrontendReadyFinalState:
    present = tuple(lock for lock in _UPSTREAM_LOCKS if _present(lock))
    missing = tuple(lock for lock in _UPSTREAM_LOCKS if not _present(lock))

    notes: list[str] = []
    if missing:
        notes.append(f"{len(missing)} upstream lock(s) missing")
    notes.append(
        "Source mutation BLOCKED pending real human approval. "
        "Training eligibility blocked. No live model call. "
        "Network providers blocked. lib.rs not auto-modified."
    )

    return DeterminexIDEFrontendReadyFinalState(
        generated_at=datetime.now(UTC).isoformat(),
        tauri_rust_command_bridge="READY_AS_STANDALONE_MODULE",
        frontend_repair_panel_shell="READY",
        frontend_workspace_status_panel="READY",
        frontend_model_route_panel="READY",
        frontend_diagnose_and_patch_plan_flow="READY_OPT_IN_GATED",
        frontend_temp_verify_panel="READY_TEMP_ONLY",
        frontend_human_approval_panel="READY_FIXTURE_APPROVAL_ONLY",
        frontend_source_apply_dry_run_panel="READY_NO_REAL_APPLY",
        frontend_evidence_viewer="READY_READ_ONLY",
        local_model_settings_panel="READY_NO_LIVE_CALL_ON_SAVE",
        frontend_end_to_end_repair_flow_smoke="READY",
        source_mutation="BLOCKED_PENDING_REAL_HUMAN_APPROVAL",
        training_eligibility="BLOCKED_BY_DEFAULT",
        live_model_call="BLOCKED_BY_DEFAULT",
        network_provider="BLOCKED_BY_DEFAULT",
        release_readiness="NOT_RELEASED",
        next_unblocker="REAL_TAURI_LIB_RS_WIRING_AND_LIVE_LOCAL_MODEL_PROVIDER",
        upstream_locks_present=present,
        upstream_locks_missing=missing,
        statuses_seen=tuple(DETERMINEX_IDE_FRONTEND_READY_FINAL_STATE_TOKENS),
        notes=tuple(notes),
    )


def upstream_locks() -> tuple[str, ...]:
    return _UPSTREAM_LOCKS


__all__ = [
    "assemble_frontend_ready_final_state",
    "DeterminexIDEFrontendReadyFinalState",
    "DETERMINEX_IDE_FRONTEND_READY_FINAL_STATE_TOKENS",
    "upstream_locks",
]
