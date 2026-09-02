"""Final-state assembly for the Determinex IDE UI-ready backend."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from .determinex_ide_ui_ready_final_state_record import (
    DETERMINEX_IDE_UI_READY_FINAL_STATE_TOKENS,
    DeterminexIDEUIReadyFinalState,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_LOCKS_DIR = _REPO_ROOT / "locks" / "sentinel"


_UPSTREAM_LOCKS: tuple[str, ...] = (
    "IDE_WORKSPACE_OPEN_FLOW_LOCK_001",
    "IDE_MODEL_ROUTE_PANEL_LOCK_001",
    "IDE_DIAGNOSE_FLOW_LOCK_001",
    "IDE_PATCH_PLAN_FLOW_LOCK_001",
    "IDE_TEMP_VERIFY_FLOW_LOCK_001",
    "IDE_HUMAN_APPROVAL_SIGNING_FLOW_LOCK_001",
    "IDE_SOURCE_APPLY_GATE_FLOW_LOCK_001",
    "TAURI_BACKEND_COMMAND_BRIDGE_LOCK_001",
    "IDE_FRONTEND_STATE_CONTRACT_LOCK_001",
    "IDE_APPROVAL_UX_COPY_LOCK_001",
    "IDE_END_TO_END_UI_FLOW_TRACE_LOCK_001",
    "DETERMINEX_IDE_CONSUMER_READY_FINAL_STATE_LOCK_001",
)


def _present(lock_name: str) -> bool:
    return (_LOCKS_DIR / f"{lock_name}.json").is_file()


def assemble_ui_ready_final_state() -> DeterminexIDEUIReadyFinalState:
    present = tuple(lock for lock in _UPSTREAM_LOCKS if _present(lock))
    missing = tuple(lock for lock in _UPSTREAM_LOCKS if not _present(lock))

    statuses_seen = list(DETERMINEX_IDE_UI_READY_FINAL_STATE_TOKENS)
    notes: list[str] = []
    if missing:
        notes.append(f"{len(missing)} upstream lock(s) missing")
    notes.append(
        "Source mutation BLOCKED pending real human approval. "
        "Training eligibility blocked. Tauri Rust UI not modified."
    )

    return DeterminexIDEUIReadyFinalState(
        generated_at=datetime.now(UTC).isoformat(),
        workspace_open_flow="READY",
        model_route_panel="READY",
        diagnose_flow="READY",
        patch_plan_flow="READY_QUARANTINE",
        temp_verify_flow="READY_TEMP_ONLY",
        human_approval_signing_flow="READY",
        source_apply_gate_flow="READY_DRY_RUN_ONLY",
        tauri_backend_bridge="READY",
        frontend_state_contract="READY",
        approval_ux_copy="READY",
        end_to_end_ui_flow_trace="READY",
        source_mutation="BLOCKED_PENDING_REAL_HUMAN_APPROVAL",
        training_eligibility="BLOCKED_BY_DEFAULT",
        release_readiness="NOT_RELEASED",
        next_unblocker="REAL_FRONTEND_IMPLEMENTATION_AND_REAL_LOCAL_MODEL_CONFIG",
        upstream_locks_present=present,
        upstream_locks_missing=missing,
        statuses_seen=tuple(statuses_seen),
        notes=tuple(notes),
    )


def upstream_locks() -> tuple[str, ...]:
    return _UPSTREAM_LOCKS


__all__ = [
    "assemble_ui_ready_final_state",
    "DeterminexIDEUIReadyFinalState",
    "DETERMINEX_IDE_UI_READY_FINAL_STATE_TOKENS",
    "upstream_locks",
]
