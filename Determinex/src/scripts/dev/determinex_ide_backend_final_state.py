"""Campaign-end final backend state assembly.

Pure function over lock-manifest file presence. Emits a
:class:`FinalBackendState` that consolidates every dimension of the
Claude lane's verified-repair apparatus into a single snapshot.

This is the apparatus's "final word" record for the campaign — read by
the audit chain, consumed by the IDE state model, and pinned by the
focused test for :mod:`DETERMINEX_IDE_BACKEND_FINAL_STATE_LOCK_001`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from .determinex_ide_backend_final_state_record import (
    DETERMINEX_IDE_BACKEND_FINAL_STATE_TOKENS,
    FinalBackendState,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_LOCKS_DIR = _REPO_ROOT / "locks" / "sentinel"


# Locks whose presence the final-state assembly requires. Tests pin
# this set.
_UPSTREAM_LOCKS: tuple[str, ...] = (
    # Foundation hardening
    "CONFIG_SPINE_LOCK_001",
    "PATH_PORTABILITY_LOCK_001",
    "EVIDENCE_IMMUTABILITY_GUARD_LOCK_001",
    "CORPUS_WRITE_GUARD_LOCK_001",
    "DETERMINEX_ARCHITECTURE_REGRESSION_GAUNTLET_LOCK_001",
    "ARCH_GAUNTLET_CI_LOCK_001",
    "CODEBASE_EXPLORER_SMOKE_LOCK_001",
    "BUILD_ADAPTER_REGISTRY_LOCK_001",
    "VERIFIER_COVERAGE_MATRIX_LOCK_001",
    "PARALLEL_EXECUTION_LAYER_AUDIT_LOCK_001",
    "HARDENED_INTAKE_EXECUTION_RUNNER_LOCK_001",
    "HARDENED_REPAIR_PIPELINE_EXECUTORS_LOCK_001",
    "SCRIPT_HELPER_EXECUTION_CLASSIFICATION_SWEEP_LOCK_001",
    "HARDENED_VERIFIED_TASK_AND_CODECLASH_LOCK_001",
    # Verified-repair campaign
    "MODEL_ROUTER_LOCK_001",
    "LLM_MOCKED_INTAKE_REPAIR_LOCK_001",
    "SAFE_PATCH_DIFF_ROLLBACK_LOCK_001",
    "VERIFIED_REPAIR_TRACE_LOCK_001",
    "HUMAN_APPROVAL_SOURCE_MUTATION_GATE_LOCK_001",
    "IDE_REPAIR_STATE_MODEL_LOCK_001",
    "CORPUS_ELIGIBILITY_REPAIR_TRACE_GUARD_LOCK_001",
    "LOCAL_MODEL_ADMISSION_POLICY_LOCK_001",
    "ARBITRARY_REPO_READINESS_MATRIX_LOCK_001",
)


def _present(lock_name: str) -> bool:
    return (_LOCKS_DIR / f"{lock_name}.json").is_file()


def assemble_final_state() -> FinalBackendState:
    present = tuple(lock for lock in _UPSTREAM_LOCKS if _present(lock))
    missing = tuple(lock for lock in _UPSTREAM_LOCKS if not _present(lock))

    statuses_seen: list[str] = [
        "DETERMINEX_IDE_BACKEND_FINAL_STATE_WRITTEN",
        "EXECUTION_SURFACE_CLEAN",
        "MODEL_ROUTING_READY_DRY_RUN",
        "REPO_INTAKE_READY_FIXTURES",
        "VERIFIER_MATRIX_PARTIAL_BACKED",
        "MOCKED_REPAIR_LOOP_READY",
        "SAFE_PATCH_WORKSPACE_READY_TEMP_ONLY",
        "SOURCE_MUTATION_BLOCKED_PENDING_HUMAN_APPROVAL",
        "IDE_BACKEND_STATE_READY",
        "LIVE_MODEL_CALLS_NOT_ADMITTED",
        "TRAINING_ELIGIBILITY_BLOCKED_BY_DEFAULT",
        "RELEASE_READINESS_NOT_RELEASED",
        "NEXT_UNBLOCKER_DECLARED",
    ]

    notes: list[str] = []
    if missing:
        notes.append(
            f"{len(missing)} upstream lock(s) missing — final-state assembly "
            f"reports their absence in upstream_locks_missing."
        )
    notes.append(
        "Live model calls are NOT admitted. Source mutation remains "
        "BLOCKED pending human approval. Training eligibility is blocked "
        "by default. The apparatus is at its end-of-campaign equilibrium."
    )

    return FinalBackendState(
        generated_at=datetime.now(UTC).isoformat(),
        execution_surface="CLEAN",
        model_routing="READY_DRY_RUN",
        repo_intake="READY_FIXTURES",
        verifier_matrix="PARTIAL_BACKED",
        mocked_repair_loop="READY",
        safe_patch_workspace="READY_TEMP_ONLY",
        source_mutation="BLOCKED_PENDING_HUMAN_APPROVAL",
        ide_backend_state="READY",
        live_model_calls="NOT_ADMITTED",
        training_eligibility="BLOCKED_BY_DEFAULT",
        release_readiness="NOT_RELEASED",
        next_unblocker="LOCAL_MODEL_LIVE_ADMISSION_AND_IDE_UI_FLOW",
        upstream_locks_present=present,
        upstream_locks_missing=missing,
        statuses_seen=tuple(statuses_seen),
        notes=tuple(notes),
    )


def upstream_locks() -> tuple[str, ...]:
    return _UPSTREAM_LOCKS


__all__ = [
    "assemble_final_state",
    "FinalBackendState",
    "DETERMINEX_IDE_BACKEND_FINAL_STATE_TOKENS",
    "upstream_locks",
]
