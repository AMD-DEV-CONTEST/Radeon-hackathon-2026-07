"""Final-state assembly for the Determinex IDE consumer-ready backend."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from .determinex_ide_consumer_ready_final_state_record import (
    DETERMINEX_IDE_CONSUMER_READY_FINAL_STATE_TOKENS,
    DeterminexIDEConsumerReadyFinalState,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_LOCKS_DIR = _REPO_ROOT / "locks" / "sentinel"


_UPSTREAM_LOCKS: tuple[str, ...] = (
    "LOCAL_MODEL_CONFIG_WIZARD_LOCK_001",
    "LOCAL_PROVIDER_SMOKE_TEST_LOCK_001",
    "OPT_IN_LIVE_DIAGNOSE_COMMAND_LOCK_001",
    "OPT_IN_PATCH_PLAN_COMMAND_LOCK_001",
    "TEMP_PATCH_VERIFY_COMMAND_LOCK_001",
    "HUMAN_APPROVAL_PACKET_UI_MODEL_LOCK_001",
    "IDE_BACKEND_COMMAND_SURFACE_LOCK_001",
    "SOURCE_MUTATION_APPLY_DRY_RUN_LOCK_001",
    "IDE_CONSUMER_FLOW_TRACE_LOCK_001",
    # Prior campaign foundations
    "CLAUDE_LANE_LIVE_MODEL_READY_FINAL_STATE_LOCK_001",
    "DETERMINEX_IDE_BACKEND_FINAL_STATE_LOCK_001",
)


def _present(lock_name: str) -> bool:
    return (_LOCKS_DIR / f"{lock_name}.json").is_file()


def assemble_consumer_ready_final_state() -> DeterminexIDEConsumerReadyFinalState:
    present = tuple(lock for lock in _UPSTREAM_LOCKS if _present(lock))
    missing = tuple(lock for lock in _UPSTREAM_LOCKS if not _present(lock))

    statuses_seen = list(DETERMINEX_IDE_CONSUMER_READY_FINAL_STATE_TOKENS)
    notes: list[str] = []
    if missing:
        notes.append(f"{len(missing)} upstream lock(s) missing")
    notes.append(
        "Source mutation remains BLOCKED pending real human approval; "
        "training eligibility blocked by default."
    )

    return DeterminexIDEConsumerReadyFinalState(
        generated_at=datetime.now(UTC).isoformat(),
        local_model_config="READY_OPT_IN",
        local_provider_smoke="READY",
        live_diagnose_command="READY_OPT_IN",
        patch_plan_command="READY_QUARANTINE",
        temp_patch_verify_command="READY_TEMP_ONLY",
        human_approval_ui_model="READY",
        ide_backend_command_surface="READY",
        source_apply_dry_run="READY_NO_MUTATION",
        ide_consumer_flow_trace="READY",
        source_mutation="BLOCKED_PENDING_REAL_HUMAN_APPROVAL",
        training_eligibility="BLOCKED_BY_DEFAULT",
        release_readiness="NOT_RELEASED",
        next_unblocker="FRONTEND_UI_AND_REAL_USER_APPROVAL_FLOW",
        upstream_locks_present=present,
        upstream_locks_missing=missing,
        statuses_seen=tuple(statuses_seen),
        notes=tuple(notes),
    )


def upstream_locks() -> tuple[str, ...]:
    return _UPSTREAM_LOCKS


__all__ = [
    "assemble_consumer_ready_final_state",
    "DeterminexIDEConsumerReadyFinalState",
    "DETERMINEX_IDE_CONSUMER_READY_FINAL_STATE_TOKENS",
    "upstream_locks",
]
