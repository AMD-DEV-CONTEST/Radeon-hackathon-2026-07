"""CLAUDE_AUTHORITY_LEAK_REMEDIATION_FINAL_STATE_LOCK_001 evaluator.

Rung 9 (finale). Inspects the eight prior rungs' lock manifests
and the evidence index on disk; produces a single record asserting
whether every authority-leak dimension is closed and whether the
campaign as a whole opens neither source_mutation nor
training_eligibility.

This module DOES NOT call any runtime gate, DOES NOT touch the
workspace, DOES NOT call the network, DOES NOT spawn a subprocess.
It reads JSON.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
_SCRIPTS = _HERE.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from .claude_authority_leak_remediation_final_state_record import (
    CLAUDE_AUTHORITY_LEAK_REMEDIATION_FINAL_STATE_STATUS_TOKENS,
    ClaudeAuthorityLeakRemediationFinalStateRecord,
)

# Per-dimension lock manifest paths (relative to repo root).
_RUNG_LOCKS: dict[str, tuple[str, str]] = {
    # dimension -> (lock_id, finding_id)
    "diff_body_binding": (
        "REAL_APPROVAL_DIFF_BODY_CONTENT_BINDING_LOCK_001",
        "CLAUDE-AUTH-001",
    ),
    "fixture_refusal": (
        "APPLY_GATE_FIXTURE_REFUSAL_LOCK_001",
        "CLAUDE-AUTH-002",
    ),
    "post_apply_verifier_default_pass": (
        "POST_APPLY_VERIFIER_NO_DEFAULT_PASS_LOCK_001",
        "CLAUDE-AUTH-003",
    ),
    "model_admission_bypass": (
        "MODEL_ADMISSION_NO_BYPASS_LOCK_001",
        "CLAUDE-AUTH-004",
    ),
    "tauri_command_alignment": (
        "TAURI_COMMAND_VERB_ALIGNMENT_LOCK_001",
        "CLAUDE-AUTH-006",
    ),
    "diagnose_prompt_opacity": (
        "DIAGNOSE_PROMPT_OPACITY_ENFORCEMENT_LOCK_001",
        "CLAUDE-AUTH-007",
    ),
    "approval_signature_binding": (
        "APPROVAL_SIGNATURE_CRYPTOGRAPHIC_BINDING_LOCK_001",
        "CLAUDE-AUTH-008",
    ),
    "rollback_symlink_semantics": (
        "ROLLBACK_SYMLINK_SEMANTICS_LOCK_001",
        "CLAUDE-AUTH-009",
    ),
}

# CLAUDE-AUTH-005 (cross-lane status surface labelling) and all 8
# LOW findings are explicitly deferred — they do not change the
# write/authority boundary, and they belong in a future campaign.
_DEFERRED_FINDINGS = (
    "CLAUDE-AUTH-005",
    "CLAUDE-AUTH-010",
    "CLAUDE-AUTH-011",
    "CLAUDE-AUTH-012",
    "CLAUDE-AUTH-013",
    "CLAUDE-AUTH-014",
    "CLAUDE-AUTH-015",
    "CLAUDE-AUTH-016",
    "CLAUDE-AUTH-017",
)


def _lock_path(repo_root: Path, lock_id: str) -> Path:
    return repo_root / "locks" / "sentinel" / f"{lock_id}.json"


def _lock_closes_dimension(repo_root: Path, lock_id: str) -> tuple[bool, str]:
    """A dimension is 'closed' iff the rung's lock manifest exists,
    parses as JSON, declares the matching lock_id, and the
    scope_discipline section asserts BOTH:
      - source_mutation_authorized == False
      - one of training_eligible/training_eligibility_opened == False
    The presence of an evidence/run_artifact path inside is required
    so the lock is not just a header.
    """
    p = _lock_path(repo_root, lock_id)
    if not p.is_file():
        return False, f"lock manifest missing: {p}"
    try:
        blob = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return False, f"lock manifest invalid JSON: {exc}"
    if blob.get("lock_id") != lock_id:
        return False, f"lock_id mismatch inside manifest ({blob.get('lock_id')!r})"
    sd = blob.get("scope_discipline") or {}
    if sd.get("source_mutation_authorized") is not False:
        return False, "scope_discipline.source_mutation_authorized is not False"
    # accept either name (locks pre-rung-8 used training_eligibility_opened)
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
        return False, f"evidence artifact file missing on disk: {ev}"
    return True, ""


def evaluate(repo_root: Path | str) -> ClaudeAuthorityLeakRemediationFinalStateRecord:
    rr = Path(repo_root).resolve()

    closures: dict[str, bool] = {}
    notes: list[str] = []
    missing: list[str] = []
    for dim, (lock_id, _finding) in _RUNG_LOCKS.items():
        ok, reason = _lock_closes_dimension(rr, lock_id)
        closures[dim] = ok
        if not ok:
            missing.append(f"{dim}({lock_id}): {reason}")

    rungs_inspected = tuple(lid for lid, _f in _RUNG_LOCKS.values())
    remediated = tuple(f for _l, f in _RUNG_LOCKS.values())

    all_closed = all(closures.values())
    # Aggregate invariants — the campaign's umbrella promise.
    source_mutation_authorized = False
    training_eligible = False

    safe = bool(all_closed and source_mutation_authorized is False and training_eligible is False)

    if not all_closed:
        decision = "CLAUDE_AUTHORITY_LEAK_REMEDIATION_FINAL_STATE_BLOCKED_DIMENSION_NOT_CLOSED"
        notes.extend(missing)
    else:
        decision = "CLAUDE_AUTHORITY_LEAK_REMEDIATION_FINAL_STATE_PASSED"
        notes.append(
            "all eight authority-leak dimensions closed; campaign aggregate "
            "invariants (source_mutation_authorized, training_eligible) "
            "remain False; safe_for_cross_lane_boundary asserted"
        )

    return ClaudeAuthorityLeakRemediationFinalStateRecord(
        decision=decision,
        diff_body_binding_closed=closures["diff_body_binding"],
        fixture_refusal_closed=closures["fixture_refusal"],
        post_apply_verifier_default_pass_closed=closures["post_apply_verifier_default_pass"],
        model_admission_bypass_closed=closures["model_admission_bypass"],
        tauri_command_alignment_closed=closures["tauri_command_alignment"],
        diagnose_prompt_opacity_closed=closures["diagnose_prompt_opacity"],
        approval_signature_binding_closed=closures["approval_signature_binding"],
        rollback_symlink_semantics_closed=closures["rollback_symlink_semantics"],
        source_mutation_authorized=source_mutation_authorized,
        training_eligible=training_eligible,
        safe_for_cross_lane_boundary=safe,
        findings_remediated=remediated,
        findings_deferred=_DEFERRED_FINDINGS,
        rungs_inspected=rungs_inspected,
        notes=tuple(notes),
    )


__all__ = [
    "evaluate",
    "CLAUDE_AUTHORITY_LEAK_REMEDIATION_FINAL_STATE_STATUS_TOKENS",
    "ClaudeAuthorityLeakRemediationFinalStateRecord",
]
