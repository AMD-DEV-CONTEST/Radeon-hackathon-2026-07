"""DETERMINEX_UNIFIED_PRODUCT_UX_FINAL_STATE_LOCK_001 evaluator.

Rung 9 (finale). Reads the eight prior UX-shell rungs' lock
manifests on disk and asserts:

  * Each rung's lock manifest exists with the right lock_id.
  * Each rung's scope_discipline keeps source_mutation_authorized
    and training open-keys False.
  * Each rung's evidence_run_artifact exists on disk.
  * Aggregate invariants stay False (source_mutation_authorized,
    training_eligible, release_ready).
  * unsupported_claims_blocked stays True (no all-app /
    all-language / no-followup claim was opened).

Read-only on disk. Never re-runs runtime gates.
"""

from __future__ import annotations

import json
from pathlib import Path

from .unified_product_ux_final_state_record import (
    UNIFIED_PRODUCT_UX_FINAL_STATE_STATUS_TOKENS,
    UnifiedProductUxFinalStateRecord,
)

# Dimension -> lock_id
_RUNG_LOCKS: dict[str, str] = {
    "navigation_model": "DETERMINEX_UNIFIED_PRODUCT_NAVIGATION_MODEL_LOCK_001",
    "idea_lab_workflow": "DETERMINEX_IDEA_LAB_WORKFLOW_LOCK_001",
    "repo_clinic_workflow": "DETERMINEX_REPO_CLINIC_WORKFLOW_LOCK_001",
    "maintenance_bay_workflow": "DETERMINEX_MAINTENANCE_BAY_WORKFLOW_LOCK_001",
    "learning_studio_workflow": "DETERMINEX_LEARNING_STUDIO_WORKFLOW_LOCK_001",
    "proof_operator_center_viewmodel": "DETERMINEX_PROOF_OPERATOR_CENTER_VIEWMODEL_LOCK_001",
    "user_levels_teaching_windows": "DETERMINEX_UNIFIED_USER_LEVELS_AND_TEACHING_WINDOWS_LOCK_001",
    "splash_demo_spec": "DETERMINEX_UNIFIED_PRODUCT_SPLASH_DEMO_SPEC_LOCK_001",
}


# Keys in scope_discipline that, if True, indicate an over-claim.
_UNSUPPORTED_CLAIM_KEYS = (
    "all_apps_claim",
    "all_languages_claim",
    "all_codebases_claim",
    "no_followup_claim",
    "production_ready_arbitrary_apps_claim",
    "training_enabled_in_demo",
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
        return False, "scope_discipline opens training"
    if te is None and teo is None:
        return False, "scope_discipline missing training_eligibility key"
    ev = (blob.get("evidence") or {}).get("run_artifact")
    if not ev:
        return False, "evidence.run_artifact missing"
    if not (repo_root / ev).is_file():
        return False, f"evidence artifact missing on disk: {ev}"
    return True, ""


def _unsupported_claims_clean(repo_root: Path) -> tuple[bool, list[str]]:
    """Walk every rung's scope_discipline and flag any unsupported-
    claim key set to True."""
    violations: list[str] = []
    for lock_id in _RUNG_LOCKS.values():
        p = _lock_path(repo_root, lock_id)
        if not p.is_file():
            continue
        try:
            blob = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        sd = blob.get("scope_discipline") or {}
        for k in _UNSUPPORTED_CLAIM_KEYS:
            if sd.get(k) is True:
                violations.append(f"{lock_id}:{k}=True")
    return (not violations), violations


def evaluate(repo_root: Path | str) -> UnifiedProductUxFinalStateRecord:
    rr = Path(repo_root).resolve()
    closures: dict[str, bool] = {}
    missing: list[str] = []
    for dim, lock_id in _RUNG_LOCKS.items():
        ok, reason = _dimension_closed(rr, lock_id)
        closures[dim] = ok
        if not ok:
            missing.append(f"{dim}({lock_id}): {reason}")

    all_closed = all(closures.values())

    claims_clean, claim_violations = _unsupported_claims_clean(rr)

    # Aggregate.
    source_mutation_authorized = False
    training_eligible = False
    release_ready = False  # scrub/install/demo workflow not yet completed
    unsupported_claims_blocked = claims_clean

    if not all_closed:
        decision = "UNIFIED_PRODUCT_UX_FINAL_STATE_BLOCKED_DIMENSION_NOT_CLOSED"
        notes = tuple(missing)
        next_rung = "complete_missing_rung"
    elif not claims_clean:
        decision = "UNIFIED_PRODUCT_UX_FINAL_STATE_BLOCKED_DIMENSION_NOT_CLOSED"
        notes = (f"unsupported claim keys set to True: {claim_violations!r}",)
        next_rung = "scrub_unsupported_claims"
    else:
        decision = "UNIFIED_PRODUCT_UX_FINAL_STATE_PASSED"
        notes = (
            "all eight UX-shell dimensions closed",
            "aggregate invariants (source_mutation_authorized, "
            "training_eligible, release_ready) stay False",
            "unsupported_claims_blocked True (no all-app / all-language "
            "/ no-followup / production-ready-arbitrary-apps claim opened)",
        )
        next_rung = "live_react_mount_for_unified_product_shell"

    rungs_inspected = tuple(_RUNG_LOCKS.values())

    return UnifiedProductUxFinalStateRecord(
        decision=decision,
        navigation_model_closed=closures["navigation_model"],
        idea_lab_workflow_closed=closures["idea_lab_workflow"],
        repo_clinic_workflow_closed=closures["repo_clinic_workflow"],
        maintenance_bay_workflow_closed=closures["maintenance_bay_workflow"],
        learning_studio_workflow_closed=closures["learning_studio_workflow"],
        proof_operator_center_viewmodel_closed=closures["proof_operator_center_viewmodel"],
        user_levels_teaching_windows_closed=closures["user_levels_teaching_windows"],
        splash_demo_spec_closed=closures["splash_demo_spec"],
        source_mutation_authorized=source_mutation_authorized,
        training_eligible=training_eligible,
        release_ready=release_ready,
        unsupported_claims_blocked=unsupported_claims_blocked,
        rungs_inspected=rungs_inspected,
        next_recommended_rung=next_rung,
        notes=notes,
    )


__all__ = [
    "evaluate",
    "UNIFIED_PRODUCT_UX_FINAL_STATE_STATUS_TOKENS",
    "UnifiedProductUxFinalStateRecord",
]
