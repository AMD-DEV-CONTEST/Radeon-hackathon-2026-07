"""Final-state assembly for the Claude real-model + verifier-ready campaign.

This campaign is SUBORDINATE to the Codex proof-control audit repair.
Full-suite clean is NOT claimed here.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from .claude_real_model_verifier_ready_final_state_record import (
    CLAUDE_REAL_MODEL_VERIFIER_READY_FINAL_STATE_TOKENS,
    ClaudeRealModelVerifierReadyFinalState,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_LOCKS_DIR = _REPO_ROOT / "locks" / "sentinel"


_UPSTREAM_LOCKS: tuple[str, ...] = (
    "CANONICAL_LOCAL_MODEL_ID_SELECTION_LOCK_001",
    "OLLAMA_MODEL_PULL_OPERATOR_GUIDE_LOCK_001",
    "REAL_LOCAL_MODEL_HEALTHCHECK_LOCK_001",
    "BUILD_ADAPTER_BACKED_VERIFIER_SELECTION_LOCK_001",
    "REAL_MODEL_DIAGNOSE_WITH_BUILD_VERIFIER_LOCK_001",
    "REAL_MODEL_PATCH_PLAN_WITH_VERIFIER_CONTEXT_LOCK_001",
    "REAL_BUILD_ADAPTER_TEMP_VERIFY_TRACE_LOCK_001",
    "REAL_APPROVAL_APPLY_POST_VERIFY_TRACE_LOCK_001",
)


def _present(lock_name: str) -> bool:
    return (_LOCKS_DIR / f"{lock_name}.json").is_file()


def assemble_real_model_verifier_ready_final_state() -> ClaudeRealModelVerifierReadyFinalState:
    present = tuple(lock for lock in _UPSTREAM_LOCKS if _present(lock))
    missing = tuple(lock for lock in _UPSTREAM_LOCKS if not _present(lock))

    notes: list[str] = []
    if missing:
        notes.append(f"{len(missing)} upstream lock(s) missing")
    notes.extend(
        [
            "This campaign is SUBORDINATE to Codex's proof-control audit repair.",
            "Full-suite clean is NOT claimed here. Three pre-existing audit "
            "failures from the unrelated PB lane proof-control commit remain.",
            "Source mutation requires real human approval + temp verifier + "
            "rollback snapshot + build-adapter post-apply verifier + "
            "rollback-on-fail. Training eligibility blocked. Network providers "
            "blocked. No Docker. No release workflow.",
        ]
    )

    return ClaudeRealModelVerifierReadyFinalState(
        generated_at=datetime.now(UTC).isoformat(),
        canonical_model_id="READY",
        model_available="READY_OR_BLOCKED_WITH_REASON",
        model_healthcheck="READY_OR_BLOCKED_WITH_REASON",
        build_adapter_verifier="READY",
        real_model_diagnose="READY_ADVISORY_ONLY",
        real_patch_plan_quarantine="READY",
        temp_verify_trace="READY_HUMAN_APPROVAL_REQUIRED",
        real_approval_apply="READY_GATED",
        post_apply_verifier="READY",
        source_mutation="GATED_BY_REAL_APPROVAL",
        training_eligibility="BLOCKED_BY_DEFAULT",
        next_unblocker="CODEX_AUDIT_REPAIR_THEN_PROGRAMBENCH_REGRESSION_PARITY",
        subordinate_to_codex_audit_repair=True,
        upstream_locks_present=present,
        upstream_locks_missing=missing,
        statuses_seen=tuple(CLAUDE_REAL_MODEL_VERIFIER_READY_FINAL_STATE_TOKENS),
        notes=tuple(notes),
    )


def upstream_locks() -> tuple[str, ...]:
    return _UPSTREAM_LOCKS


__all__ = [
    "assemble_real_model_verifier_ready_final_state",
    "ClaudeRealModelVerifierReadyFinalState",
    "CLAUDE_REAL_MODEL_VERIFIER_READY_FINAL_STATE_TOKENS",
    "upstream_locks",
]
