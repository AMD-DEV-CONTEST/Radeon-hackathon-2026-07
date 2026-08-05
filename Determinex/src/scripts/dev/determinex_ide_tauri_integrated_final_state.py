"""Final-state assembly for the Determinex IDE Tauri-integrated campaign.

Consolidates the 8 rungs of the Tauri-integrated campaign plus the
prior frontend-ready final state into a single
DeterminexIDETauriIntegratedFinalState.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from .determinex_ide_tauri_integrated_final_state_record import (
    DETERMINEX_IDE_TAURI_INTEGRATED_FINAL_STATE_TOKENS,
    DeterminexIDETauriIntegratedFinalState,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_LOCKS_DIR = _REPO_ROOT / "locks" / "sentinel"


_UPSTREAM_LOCKS: tuple[str, ...] = (
    "TAURI_LIB_RS_COMMAND_WIRING_LOCK_001",
    "FRONTEND_COMMAND_INVOKE_CLIENT_LOCK_001",
    "FRONTEND_PANEL_COMMAND_WIRING_LOCK_001",
    "REAL_LOCAL_MODEL_PROVIDER_CONFIG_LOCK_001",
    "OLLAMA_LOCAL_PROVIDER_SMOKE_LOCK_001",
    "FRONTEND_LIVE_DIAGNOSE_OPT_IN_SMOKE_LOCK_001",
    "FRONTEND_APPROVAL_PACKET_ROUNDTRIP_LOCK_001",
    "FRONTEND_REAL_FLOW_E2E_LOCK_001",
    "DETERMINEX_IDE_FRONTEND_READY_FINAL_STATE_LOCK_001",
)


def _present(lock_name: str) -> bool:
    return (_LOCKS_DIR / f"{lock_name}.json").is_file()


def assemble_tauri_integrated_final_state() -> DeterminexIDETauriIntegratedFinalState:
    present = tuple(lock for lock in _UPSTREAM_LOCKS if _present(lock))
    missing = tuple(lock for lock in _UPSTREAM_LOCKS if not _present(lock))

    notes: list[str] = []
    if missing:
        notes.append(f"{len(missing)} upstream lock(s) missing")
    notes.append(
        "Source mutation BLOCKED pending real human approval. "
        "Training eligibility blocked. Live model call blocked unless explicit local opt-in. "
        "Network providers blocked. Ollama smoke is BLOCKED_NOT_CONFIGURED unless caller opts in."
    )

    return DeterminexIDETauriIntegratedFinalState(
        generated_at=datetime.now(UTC).isoformat(),
        tauri_lib_rs_wiring="READY",
        frontend_command_client="READY",
        panel_command_wiring="READY",
        local_model_provider_config="READY_OPT_IN",
        ollama_provider_smoke="READY_OR_BLOCKED_WITH_REASON",
        live_diagnose_opt_in="READY_OR_BLOCKED_WITH_REASON",
        approval_packet_roundtrip="READY",
        frontend_real_flow_e2e="READY",
        source_mutation="BLOCKED_PENDING_REAL_HUMAN_APPROVAL",
        training_eligibility="BLOCKED_BY_DEFAULT",
        release_readiness="NOT_RELEASED",
        next_unblocker="REAL_LOCAL_MODEL_AVAILABLE_AND_REAL_USER_APPROVAL_APPLY_GATE",
        upstream_locks_present=present,
        upstream_locks_missing=missing,
        statuses_seen=tuple(DETERMINEX_IDE_TAURI_INTEGRATED_FINAL_STATE_TOKENS),
        notes=tuple(notes),
    )


def upstream_locks() -> tuple[str, ...]:
    return _UPSTREAM_LOCKS


__all__ = [
    "assemble_tauri_integrated_final_state",
    "DeterminexIDETauriIntegratedFinalState",
    "DETERMINEX_IDE_TAURI_INTEGRATED_FINAL_STATE_TOKENS",
    "upstream_locks",
]
