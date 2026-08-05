"""DETERMINEX_LIVE_REACT_PRODUCT_SHELL_DEMO_READINESS_FINAL_STATE_LOCK_001 evaluator.

Rung 5 (finale). Reads the two prior rungs' lock manifests on
disk and asserts:

NOTE (2026-07-20): originally four rungs. Two (verified_demo_binding,
release_blocker_panel) were removed from this requirement set because
their panels + locks + tests were deleted in commit 30b3ff570 ("chore:
land pending IDE product shell archive"), which determined ~74
ide-product-shell panels including these were a Claude<->Codex
tandem-pipeline trail, not real durable features. This finale test kept
requiring their (now-deleted) lock files, which is a stale check
pointing at deliberately-removed work, not a real gap.

  * Each rung's lock manifest exists with the right lock_id.
  * Each rung's scope_discipline keeps source_mutation_authorized
    AND training open-keys False.
  * Each rung's evidence_run_artifact exists on disk.
  * Aggregate invariants stay False (source_mutation_authorized,
    training_eligible, release_ready).
  * unsupported_claims_blocked stays True (no rung opens an
    all-app / all-language / no-followup / readiness-as-
    authorization claim key).

Read-only on disk. Never re-runs runtime gates.
"""

from __future__ import annotations

import json
from pathlib import Path

from .live_react_product_shell_demo_readiness_final_state_record import (
    LIVE_REACT_PRODUCT_SHELL_DEMO_READINESS_FINAL_STATE_STATUS_TOKENS,
    LiveReactProductShellDemoReadinessFinalStateRecord,
)

_RUNG_LOCKS: dict[str, str] = {
    "browser_snapshot": "DETERMINEX_REACT_PRODUCT_SHELL_BROWSER_SNAPSHOT_LOCK_001",
    "happy_blocked_path": "DETERMINEX_REACT_DEMO_NAVIGATION_HAPPY_BLOCKED_PATH_LOCK_001",
}


_UNSUPPORTED_CLAIM_KEYS = (
    "all_apps_claim",
    "all_languages_claim",
    "all_codebases_claim",
    "no_followup_claim",
    "production_ready_arbitrary_apps_claim",
    "training_enabled_in_demo",
    "readiness_treated_as_authorization",
    "broad_public_claims_granted",
    "release_ready_set_true",
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


def evaluate(repo_root: Path | str) -> LiveReactProductShellDemoReadinessFinalStateRecord:
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

    source_mutation_authorized = False
    training_eligible = False
    release_ready = False  # public release scrub still pending
    unsupported_claims_blocked = claims_clean

    if not all_closed:
        decision = (
            "LIVE_REACT_PRODUCT_SHELL_DEMO_READINESS_FINAL_STATE_BLOCKED_DIMENSION_NOT_CLOSED"
        )
        notes = tuple(missing)
        next_rung = "complete_missing_rung"
    elif not claims_clean:
        decision = (
            "LIVE_REACT_PRODUCT_SHELL_DEMO_READINESS_FINAL_STATE_BLOCKED_DIMENSION_NOT_CLOSED"
        )
        notes = (f"unsupported claim keys set to True: {claim_violations!r}",)
        next_rung = "scrub_unsupported_claims"
    else:
        decision = "LIVE_REACT_PRODUCT_SHELL_DEMO_READINESS_FINAL_STATE_PASSED"
        notes = (
            "all two demo-readiness dimensions closed (was four; "
            "verified_demo_binding and release_blocker_panel dropped "
            "2026-07-20 -- their panels+locks+tests were deliberately "
            "archived as a Claude<->Codex tandem-pipeline trail, not real "
            "features, see commit 30b3ff570)",
            "aggregate invariants (source_mutation_authorized, "
            "training_eligible, release_ready) stay False",
            "unsupported_claims_blocked True",
            "shell is browser-demoable",
        )
        next_rung = "DETERMINEX_REPO_CLINIC_FIXTURE_REPAIR_SPLASH_DEMO_LOCK_001"

    rungs_inspected = tuple(_RUNG_LOCKS.values())

    return LiveReactProductShellDemoReadinessFinalStateRecord(
        decision=decision,
        browser_snapshot_closed=closures["browser_snapshot"],
        happy_blocked_path_closed=closures["happy_blocked_path"],
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
    "LIVE_REACT_PRODUCT_SHELL_DEMO_READINESS_FINAL_STATE_STATUS_TOKENS",
    "LiveReactProductShellDemoReadinessFinalStateRecord",
]
