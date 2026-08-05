"""CLAUDE_IDE_HYGIENE_FINAL_STATE_LOCK_001 evaluator.

Rung 9 (finale). Reads the eight prior rungs' lock manifests on
disk and asserts:

  * Each rung's lock manifest exists, parses, declares the right
    lock_id, and has scope_discipline saying source_mutation_authorized
    is False and training is not opened.
  * Each rung's evidence artifact path exists on disk.
  * Aggregate invariants (source_mutation_authorized, training_eligible)
    remain False.
  * release_ready stays False.
  * demo_ready is True iff the rung-8 lock is present.
  * Forge/mobile remain planned/research_track.

The evaluator never calls runtime gates. Read-only on disk.
"""

from __future__ import annotations

import json
from pathlib import Path

from .claude_ide_hygiene_final_state_record import (
    CLAUDE_IDE_HYGIENE_FINAL_STATE_STATUS_TOKENS,
    ClaudeIdeHygieneFinalStateRecord,
)

# Dimension -> (lock_id, finding_or_purpose)
_RUNG_LOCKS: dict[str, tuple[str, str]] = {
    "ready_authorized_language": (
        "CLAUDE_AUTH_005_READY_AUTHORIZED_LANGUAGE_LOCK_001",
        "CLAUDE-AUTH-005",
    ),
    "operator_identity_bounding": (
        "CLAUDE_OPERATOR_IDENTITY_BOUNDING_LOCK_001",
        "CLAUDE-AUTH-014",
    ),
    "approval_replay_staleness": (
        "CLAUDE_APPROVAL_REPLAY_AND_STALENESS_LOCK_001",
        "CLAUDE-AUTH-016,CLAUDE-AUTH-013",
    ),
    "pre_apply_confirmation": (
        "CLAUDE_PRE_APPLY_CONFIRMATION_PANEL_LOCK_001",
        "CLAUDE-AUTH-015",
    ),
    "config_root_allowlist": (
        "CLAUDE_CONFIG_ROOT_ALLOWLIST_LOCK_001",
        "CLAUDE-AUTH-011",
    ),
    "frontend_authority_visuals": (
        "CLAUDE_FRONTEND_AUTHORITY_VISUAL_AUDIT_LOCK_001",
        "CLAUDE-AUTH-012",
    ),
    "public_claims_ledger": (
        "CLAUDE_PUBLIC_CLAIMS_LEDGER_LOCK_001",
        "publication-language-hygiene",
    ),
    "demo_script": (
        "CLAUDE_PROOF_BEFORE_MUTATION_DEMO_SCRIPT_LOCK_001",
        "external-review-demo-readiness",
    ),
}


# Findings that are explicitly NOT in scope for this campaign.
_DEFERRED_FINDINGS = (
    "CLAUDE-AUTH-010",  # evidence index in-place mutability
    "CLAUDE-AUTH-017",  # cross-lane global_operator_action_queue
)


def _lock_path(repo_root: Path, lock_id: str) -> Path:
    return repo_root / "locks" / "sentinel" / f"{lock_id}.json"


def _dimension_closed(repo_root: Path, lock_id: str) -> tuple[bool, str]:
    p = _lock_path(repo_root, lock_id)
    if not p.is_file():
        return False, f"lock manifest missing: {p}"
    try:
        blob = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return False, f"manifest invalid JSON: {exc}"
    if blob.get("lock_id") != lock_id:
        return False, f"lock_id mismatch: {blob.get('lock_id')!r}"
    sd = blob.get("scope_discipline") or {}
    if sd.get("source_mutation_authorized") is not False:
        return False, "scope_discipline.source_mutation_authorized is not False"
    te = sd.get("training_eligible")
    teo = sd.get("training_eligibility_opened")
    if te is True or teo is True:
        return False, "scope_discipline opens training eligibility"
    if te is None and teo is None:
        return False, "scope_discipline declares no training_eligibility key"
    ev = (blob.get("evidence") or {}).get("run_artifact")
    if not ev:
        return False, "evidence.run_artifact missing in manifest"
    if not (repo_root / ev).is_file():
        return False, f"evidence artifact missing on disk: {ev}"
    return True, ""


def evaluate(repo_root: Path | str) -> ClaudeIdeHygieneFinalStateRecord:
    rr = Path(repo_root).resolve()

    closures: dict[str, bool] = {}
    notes: list[str] = []
    missing: list[str] = []

    for dim, (lock_id, _) in _RUNG_LOCKS.items():
        ok, reason = _dimension_closed(rr, lock_id)
        closures[dim] = ok
        if not ok:
            missing.append(f"{dim}({lock_id}): {reason}")

    rungs_inspected = tuple(lid for lid, _ in _RUNG_LOCKS.values())

    all_closed = all(closures.values())

    # Aggregate invariants.
    source_mutation_authorized = False
    training_eligible = False
    release_ready = False  # public_release_scrub_required
    demo_ready = closures.get("demo_script", False)
    forge_status = "planned_research_track"
    mobile_console_status = "planned_research_track"

    if not all_closed:
        decision = "CLAUDE_IDE_HYGIENE_FINAL_STATE_BLOCKED_DIMENSION_NOT_CLOSED"
        notes.extend(missing)
    else:
        decision = "CLAUDE_IDE_HYGIENE_FINAL_STATE_PASSED"
        notes.append(
            "all eight dimensions closed; aggregate invariants "
            "(source_mutation_authorized, training_eligible, release_ready) "
            "stay False; demo_ready=True; Forge and mobile remain planned"
        )

    return ClaudeIdeHygieneFinalStateRecord(
        decision=decision,
        ready_authorized_language_closed=closures["ready_authorized_language"],
        operator_identity_bounding_closed=closures["operator_identity_bounding"],
        approval_replay_staleness_closed=closures["approval_replay_staleness"],
        pre_apply_confirmation_closed=closures["pre_apply_confirmation"],
        config_root_allowlist_closed=closures["config_root_allowlist"],
        frontend_authority_visuals_closed=closures["frontend_authority_visuals"],
        public_claims_ledger_closed=closures["public_claims_ledger"],
        demo_script_closed=closures["demo_script"],
        source_mutation_authorized=source_mutation_authorized,
        training_eligible=training_eligible,
        release_ready=release_ready,
        demo_ready=demo_ready,
        forge_status=forge_status,
        mobile_console_status=mobile_console_status,
        deferred_findings=_DEFERRED_FINDINGS,
        next_recommended_rung=(
            "release_readiness_install_demo_scrub" if all_closed else "complete_missing_rung"
        ),
        rungs_inspected=rungs_inspected,
        notes=tuple(notes),
    )


__all__ = [
    "evaluate",
    "CLAUDE_IDE_HYGIENE_FINAL_STATE_STATUS_TOKENS",
    "ClaudeIdeHygieneFinalStateRecord",
]
