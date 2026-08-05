"""Final-state assembly for the Claude lane after live-local-model admission.

Pure function over lock-manifest file presence. Emits a single
:class:`ClaudeLaneLiveModelReadyFinalState` consolidating the
campaign's equilibrium.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from .claude_lane_live_model_ready_final_state_record import (
    CLAUDE_LANE_LIVE_MODEL_READY_FINAL_STATE_TOKENS,
    ClaudeLaneLiveModelReadyFinalState,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_LOCKS_DIR = _REPO_ROOT / "locks" / "sentinel"


_UPSTREAM_LOCKS: tuple[str, ...] = (
    # Backend apparatus (prior campaign)
    "DETERMINEX_IDE_BACKEND_FINAL_STATE_LOCK_001",
    "MODEL_ROUTER_LOCK_001",
    "LLM_MOCKED_INTAKE_REPAIR_LOCK_001",
    "SAFE_PATCH_DIFF_ROLLBACK_LOCK_001",
    "VERIFIED_REPAIR_TRACE_LOCK_001",
    "HUMAN_APPROVAL_SOURCE_MUTATION_GATE_LOCK_001",
    "IDE_REPAIR_STATE_MODEL_LOCK_001",
    "CORPUS_ELIGIBILITY_REPAIR_TRACE_GUARD_LOCK_001",
    "LOCAL_MODEL_ADMISSION_POLICY_LOCK_001",
    "ARBITRARY_REPO_READINESS_MATRIX_LOCK_001",
    # Live-local-model campaign
    "LOCAL_MODEL_LIVE_ADMISSION_LOCK_001",
    "LIVE_MODEL_MOCK_COMPATIBILITY_HARNESS_LOCK_001",
    "LIVE_MODEL_DIAGNOSE_ONLY_TRACE_LOCK_001",
    "LIVE_MODEL_PATCH_PLAN_QUARANTINE_LOCK_001",
    "LIVE_MODEL_TEMP_PATCH_VERIFIER_GATE_LOCK_001",
    "IDE_LIVE_MODEL_REPAIR_FLOW_STATE_LOCK_001",
)


def _present(lock_name: str) -> bool:
    return (_LOCKS_DIR / f"{lock_name}.json").is_file()


def assemble_live_model_ready_final_state() -> ClaudeLaneLiveModelReadyFinalState:
    present = tuple(lock for lock in _UPSTREAM_LOCKS if _present(lock))
    missing = tuple(lock for lock in _UPSTREAM_LOCKS if not _present(lock))

    statuses_seen = list(CLAUDE_LANE_LIVE_MODEL_READY_FINAL_STATE_TOKENS)

    notes: list[str] = []
    if missing:
        notes.append(
            f"{len(missing)} upstream lock(s) missing — reported in upstream_locks_missing."
        )
    notes.append(
        "Live local-model admission is opt-in; dry-run is the default. "
        "Network model calls remain blocked by default. Source mutation "
        "remains BLOCKED pending human approval. Training eligibility "
        "blocked by default."
    )

    return ClaudeLaneLiveModelReadyFinalState(
        generated_at=datetime.now(UTC).isoformat(),
        execution_surface="CLEAN",
        model_routing="READY",
        live_model_admission="READY_OPT_IN_LOCAL_ONLY",
        network_models="BLOCKED_BY_DEFAULT",
        diagnose_only_trace="READY",
        patch_plan_quarantine="READY",
        temp_patch_verifier_gate="READY",
        source_mutation="BLOCKED_PENDING_HUMAN_APPROVAL",
        ide_live_state="READY",
        training_eligibility="BLOCKED_BY_DEFAULT",
        release_readiness="NOT_RELEASED",
        next_unblocker="REAL_LOCAL_MODEL_CONFIG_AND_HUMAN_APPROVAL_UI",
        upstream_locks_present=present,
        upstream_locks_missing=missing,
        statuses_seen=tuple(statuses_seen),
        notes=tuple(notes),
    )


def upstream_locks() -> tuple[str, ...]:
    return _UPSTREAM_LOCKS


__all__ = [
    "assemble_live_model_ready_final_state",
    "ClaudeLaneLiveModelReadyFinalState",
    "CLAUDE_LANE_LIVE_MODEL_READY_FINAL_STATE_TOKENS",
    "upstream_locks",
]
