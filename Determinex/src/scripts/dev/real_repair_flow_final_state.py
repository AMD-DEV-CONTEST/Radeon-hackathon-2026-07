"""Final-state assembly for the real repair flow campaign."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from .real_repair_flow_final_state_record import (
    REAL_REPAIR_FLOW_FINAL_STATE_TOKENS,
    RealRepairFlowFinalState,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_LOCKS_DIR = _REPO_ROOT / "locks" / "sentinel"


_UPSTREAM_LOCKS: tuple[str, ...] = (
    "REAL_OLLAMA_PROVIDER_DETECTION_LOCK_001",
    "REAL_LOCAL_MODEL_ADMISSION_LOCK_001",
    "REAL_LIVE_DIAGNOSE_ONLY_LOCK_001",
    "REAL_PATCH_PLAN_QUARANTINE_LOCK_001",
    "REAL_TEMP_PATCH_VERIFY_LOCK_001",
    "REAL_HUMAN_APPROVAL_ADMISSION_LOCK_001",
    "SOURCE_MUTATION_ROLLBACK_SNAPSHOT_LOCK_001",
    "SOURCE_MUTATION_APPLY_AFTER_APPROVAL_LOCK_001",
    "POST_APPLY_VERIFIER_LOCK_001",
    "SOURCE_MUTATION_ROLLBACK_EXECUTION_LOCK_001",
)


def _present(lock_name: str) -> bool:
    return (_LOCKS_DIR / f"{lock_name}.json").is_file()


def assemble_real_repair_flow_final_state() -> RealRepairFlowFinalState:
    present = tuple(lock for lock in _UPSTREAM_LOCKS if _present(lock))
    missing = tuple(lock for lock in _UPSTREAM_LOCKS if not _present(lock))

    notes: list[str] = []
    if missing:
        notes.append(f"{len(missing)} upstream lock(s) missing")
    notes.append(
        "Source mutation gated by real human approval + temp verifier + "
        "rollback snapshot + source+diff hash binding. Training "
        "eligibility blocked. Live model call is opt-in, advisory only. "
        "Network providers blocked. No Docker. No release workflow."
    )

    return RealRepairFlowFinalState(
        generated_at=datetime.now(UTC).isoformat(),
        real_local_model_provider="READY_OR_BLOCKED_WITH_REASON",
        real_model_admission="READY_OPT_IN",
        live_diagnose="READY_ADVISORY_ONLY",
        patch_plan_quarantine="READY",
        temp_patch_verifier="READY_HUMAN_APPROVAL_REQUIRED",
        human_approval="READY_REAL_SIGNED_ONLY",
        rollback_snapshot="READY",
        source_apply_after_approval="READY_GATED",
        post_apply_verifier="READY",
        rollback_status="READY_ON_FAIL",
        source_mutation="GATED_BY_REAL_APPROVAL",
        training_eligibility="BLOCKED_BY_DEFAULT",
        release_readiness="NOT_RELEASED",
        next_unblocker="REAL_BUILD_ADAPTER_BACKED_VERIFIER_AND_REAL_LOCAL_MODEL_PULLED",
        upstream_locks_present=present,
        upstream_locks_missing=missing,
        statuses_seen=tuple(REAL_REPAIR_FLOW_FINAL_STATE_TOKENS),
        notes=tuple(notes),
    )


def upstream_locks() -> tuple[str, ...]:
    return _UPSTREAM_LOCKS


__all__ = [
    "assemble_real_repair_flow_final_state",
    "RealRepairFlowFinalState",
    "REAL_REPAIR_FLOW_FINAL_STATE_TOKENS",
    "upstream_locks",
]
