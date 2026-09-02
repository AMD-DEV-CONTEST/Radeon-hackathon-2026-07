"""Learning Studio verified demo status loader.

DETERMINEX_REACT_LEARNING_STUDIO_VERIFIED_DEMO_STATUS_BINDING_LOCK_001.

load() reads the Codex Learning Studio teaching splash demo
evidence (if present locally) and produces a render-safe view-model
the React Learning Studio panel can display. If the evidence file
is not present, returns an AWAITING_EVIDENCE record — the UI must
show "Awaiting Codex reconciliation" rather than fake a verified
status.

Teaching outputs are NON-AUTHORIZING by construction. Even when
PASSED, no field implies mutation, approval, training, or release
authorization.

The loader is read-only. It does NOT call the network, does NOT
spawn subprocesses, does NOT write training rows.

Hard rules enforced by load():

  * status != LEARNING_STUDIO_TEACHING_SPLASH_DEMO_PASSED
    -> BLOCKED_MALFORMED
  * source_mutation_authorized / training_eligible /
    training_rows_written / approval_authority_granted /
    release_ready True at top level or under .authority
    -> BLOCKED_AUTHORITY_CONFUSION
  * authority.real_user_source_mutation_authorized True
    -> BLOCKED_AUTHORITY_CONFUSION
  * authority.broad_claims_granted / top-level broad_claims_granted
    True -> BLOCKED_BROAD_CLAIM
  * non_authorizing_teaching_only != True
    -> BLOCKED_AUTHORITY_CONFUSION
  * beginner_explanation_written / pro_explanation_written /
    failure_explanation_written / safe_next_steps_written /
    what_this_does_not_prove_written / verifier_grounding_present
    != True -> BLOCKED_MALFORMED
  * verification.learning_success_label.success_label_allowed True
    -> BLOCKED_BROAD_CLAIM
  * claim_boundary missing required statements
    -> BLOCKED_BROAD_CLAIM
  * affirmative forbidden broad-claim phrase OUTSIDE
    verification.blocked_path_demo + top-level blocked_path_demo +
    evidence.claim_scanner_result + claim_boundary +
    source_evidence_summary + explanations + verification.*
    -> BLOCKED_BROAD_CLAIM
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
_SCRIPTS = _HERE.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from .learning_studio_verified_demo_status_record import (
    FORBIDDEN_BROAD_CLAIM_PHRASES,
    LEARNING_STUDIO_VERIFIED_DEMO_STATUS_BINDING_STATUS_TOKENS,
    LearningStudioVerifiedDemoStatus,
)

# Required claim-boundary statements. The boundary list itself is
# excluded from the broad-claim regex scan so that benign 'not all
# projects' / 'no source mutation authorized' etc. do not trip it.
REQUIRED_BOUNDARY_STATEMENTS = (
    "Learning Studio explanation only",
    "non-authorizing teaching only",
    "no source mutation authorized",
    "not all projects",
    "not all languages",
    "not all users",
    "training remains false",
    "release readiness remains false",
)


_DEFAULT_EVIDENCE_DIR = (
    Path(__file__).resolve().parents[2]
    / "assurance"
    / "evidence"
    / "learning_studio_teaching_splash_demo"
)


def _locate_latest_evidence(evidence_dir: Path) -> Path | None:
    if not evidence_dir.is_dir():
        return None
    candidates = sorted(evidence_dir.glob("run_*.json"))
    return candidates[-1] if candidates else None


def _awaiting(note: str) -> LearningStudioVerifiedDemoStatus:
    return LearningStudioVerifiedDemoStatus(
        decision="REACT_LEARNING_STUDIO_VERIFIED_DEMO_STATUS_BINDING_AWAITING_EVIDENCE",
        demo_title="(awaiting Codex reconciliation)",
        target_surface="Learning Studio",
        target_workflow="(awaiting evidence)",
        teaching_subject="(awaiting evidence)",
        beginner_explanation_written=False,
        pro_explanation_written=False,
        failure_explanation_written=False,
        safe_next_steps_written=False,
        what_this_does_not_prove_written=False,
        verifier_grounding_present=False,
        non_authorizing_teaching_only=True,
        beginner_explanation="(awaiting)",
        professional_explanation="(awaiting)",
        what_failed="(awaiting)",
        why_fix_or_update_worked="(awaiting)",
        safe_next_steps="(awaiting)",
        what_this_does_not_prove="(awaiting)",
        source_mutation_authorized=False,
        approval_authority_granted=False,
        training_eligible=False,
        training_rows_written=False,
        release_ready=False,
        broad_claims_granted=False,
        real_user_source_mutation_authorized=False,
        source_evidence_paths=(),
        final_report_path="",
        evidence_manifest_path="",
        evidence_ref="",
        repo_clinic_source_summary={},
        maintenance_bay_source_summary={},
        claim_boundary=(
            "no verified Learning Studio teaching evidence available locally yet",
            "training remains false",
            "release readiness remains false",
        ),
        blocked_path_summary=(),
        notes=(note,),
    )


def _block(decision: str, note: str) -> LearningStudioVerifiedDemoStatus:
    return LearningStudioVerifiedDemoStatus(
        decision=decision,
        demo_title="(blocked)",
        target_surface="Learning Studio",
        target_workflow="(blocked)",
        teaching_subject="(blocked)",
        beginner_explanation_written=False,
        pro_explanation_written=False,
        failure_explanation_written=False,
        safe_next_steps_written=False,
        what_this_does_not_prove_written=False,
        verifier_grounding_present=False,
        non_authorizing_teaching_only=True,
        beginner_explanation="(blocked)",
        professional_explanation="(blocked)",
        what_failed="(blocked)",
        why_fix_or_update_worked="(blocked)",
        safe_next_steps="(blocked)",
        what_this_does_not_prove="(blocked)",
        source_mutation_authorized=False,
        approval_authority_granted=False,
        training_eligible=False,
        training_rows_written=False,
        release_ready=False,
        broad_claims_granted=False,
        real_user_source_mutation_authorized=False,
        source_evidence_paths=(),
        final_report_path="",
        evidence_manifest_path="",
        evidence_ref="",
        repo_clinic_source_summary={},
        maintenance_bay_source_summary={},
        claim_boundary=(),
        blocked_path_summary=(),
        notes=(note,),
    )


def _blocked_path_summary(blob: dict) -> tuple[str, ...]:
    """Extract operator-visible blocked-path titles. The evidence
    carries blocked_path_demo at the top level (verification has a
    different shape for Learning Studio); we use the top-level
    section as canonical."""
    out: list[str] = []
    section = blob.get("blocked_path_demo")
    if not isinstance(section, dict):
        return ()
    for key, val in section.items():
        if not isinstance(val, dict):
            continue
        if not val.get("blocked"):
            continue
        attempt = str(val.get("attempt") or key)
        out.append(f"{key}: {attempt}")
    return tuple(sorted(out))


def load(evidence_dir: Path | str | None = None) -> LearningStudioVerifiedDemoStatus:
    ed = Path(evidence_dir) if evidence_dir else _DEFAULT_EVIDENCE_DIR
    chosen = _locate_latest_evidence(ed)
    if chosen is None:
        return _awaiting(f"no evidence file under {ed}")

    try:
        blob = json.loads(chosen.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return _awaiting(f"could not read evidence: {exc}")

    # Status must be PASSED.
    if blob.get("status") != "LEARNING_STUDIO_TEACHING_SPLASH_DEMO_PASSED":
        return _block(
            "REACT_LEARNING_STUDIO_VERIFIED_DEMO_STATUS_BINDING_BLOCKED_MALFORMED",
            f"evidence status={blob.get('status')!r} (expected PASSED)",
        )

    # Aggregate-invariant gates.
    auth = blob.get("authority") or {}

    # source_mutation_authorized
    if (
        blob.get("source_mutation_authorized") is True
        or auth.get("source_mutation_authorized") is True
    ):
        return _block(
            "REACT_LEARNING_STUDIO_VERIFIED_DEMO_STATUS_BINDING_BLOCKED_AUTHORITY_CONFUSION",
            "evidence declares source_mutation_authorized=True",
        )
    # training_eligible
    if blob.get("training_eligible") is True or auth.get("training_eligible") is True:
        return _block(
            "REACT_LEARNING_STUDIO_VERIFIED_DEMO_STATUS_BINDING_BLOCKED_AUTHORITY_CONFUSION",
            "evidence declares training_eligible=True",
        )
    # training_rows_written
    if blob.get("training_rows_written") is True or auth.get("training_rows_written") is True:
        return _block(
            "REACT_LEARNING_STUDIO_VERIFIED_DEMO_STATUS_BINDING_BLOCKED_AUTHORITY_CONFUSION",
            "evidence declares training_rows_written=True",
        )
    # approval_authority_granted
    if (
        blob.get("approval_authority_granted") is True
        or auth.get("approval_authority_granted") is True
    ):
        return _block(
            "REACT_LEARNING_STUDIO_VERIFIED_DEMO_STATUS_BINDING_BLOCKED_AUTHORITY_CONFUSION",
            "evidence declares approval_authority_granted=True",
        )
    # release_ready
    if blob.get("release_ready") is True or auth.get("release_ready") is True:
        return _block(
            "REACT_LEARNING_STUDIO_VERIFIED_DEMO_STATUS_BINDING_BLOCKED_AUTHORITY_CONFUSION",
            "evidence declares release_ready=True",
        )
    # real_user_source_mutation_authorized
    if auth.get("real_user_source_mutation_authorized") is True:
        return _block(
            "REACT_LEARNING_STUDIO_VERIFIED_DEMO_STATUS_BINDING_BLOCKED_AUTHORITY_CONFUSION",
            "evidence declares authority.real_user_source_mutation_authorized=True",
        )
    # broad_claims_granted
    if blob.get("broad_claims_granted") is True or auth.get("broad_claims_granted") is True:
        return _block(
            "REACT_LEARNING_STUDIO_VERIFIED_DEMO_STATUS_BINDING_BLOCKED_BROAD_CLAIM",
            "evidence declares broad_claims_granted=True",
        )
    # non_authorizing_teaching_only must be explicitly True.
    if blob.get("non_authorizing_teaching_only") is not True:
        return _block(
            "REACT_LEARNING_STUDIO_VERIFIED_DEMO_STATUS_BINDING_BLOCKED_AUTHORITY_CONFUSION",
            "evidence does not assert non_authorizing_teaching_only=True",
        )

    # learning_success_label.success_label_allowed must be False —
    # if Codex allowed a success label, that's a broad-claim leak.
    ver = blob.get("verification") or {}
    label = ver.get("learning_success_label") or {}
    if label.get("success_label_allowed") is True:
        return _block(
            "REACT_LEARNING_STUDIO_VERIFIED_DEMO_STATUS_BINDING_BLOCKED_BROAD_CLAIM",
            "verification.learning_success_label.success_label_allowed=True",
        )

    # All required explanation fields must be written.
    required_flags = {
        "beginner_explanation_written": blob.get("beginner_explanation_written"),
        "pro_explanation_written": blob.get("pro_explanation_written"),
        "failure_explanation_written": blob.get("failure_explanation_written"),
        "safe_next_steps_written": blob.get("safe_next_steps_written"),
        "what_this_does_not_prove_written": blob.get("what_this_does_not_prove_written"),
        "verifier_grounding_present": blob.get("verifier_grounding_present"),
    }
    missing_flags = [k for k, v in required_flags.items() if v is not True]
    if missing_flags:
        return _block(
            "REACT_LEARNING_STUDIO_VERIFIED_DEMO_STATUS_BINDING_BLOCKED_MALFORMED",
            f"evidence missing required flags: {missing_flags!r}",
        )

    # Required claim_boundary statements.
    boundary_list = blob.get("claim_boundary") or []
    boundary_joined = " ; ".join(str(b) for b in boundary_list).lower()
    missing_required = [
        req for req in REQUIRED_BOUNDARY_STATEMENTS if req.lower() not in boundary_joined
    ]
    if missing_required:
        return _block(
            "REACT_LEARNING_STUDIO_VERIFIED_DEMO_STATUS_BINDING_BLOCKED_BROAD_CLAIM",
            f"evidence claim_boundary missing required statements: {missing_required!r}",
        )

    # Strip subsections that legitimately mention the forbidden
    # phrases as REFUSED attempts, scanner input/patterns, negation
    # statements, source-evidence summaries (which legitimately
    # mention the upstream Repo Clinic + Maintenance Bay claim
    # boundaries), explanations text (which legitimately quotes the
    # 'this does not prove' language), and verification flags. The
    # boundary list itself already validated above.
    safe = {
        k: v
        for k, v in blob.items()
        if k
        not in (
            "verification",
            "claim_boundary",
            "blocked_path_demo",
            "explanations",
            "source_evidence_summary",
        )
    }
    if "evidence" in safe:
        ev_copy = {k: v for k, v in safe["evidence"].items() if k != "claim_scanner_result"}
        safe["evidence"] = ev_copy
    verification_copy = dict(blob.get("verification") or {})
    verification_copy.pop("blocked_path_demo", None)
    safe["verification"] = verification_copy
    safe_haystack = json.dumps(safe).lower()

    for phrase in FORBIDDEN_BROAD_CLAIM_PHRASES:
        if phrase not in safe_haystack:
            continue
        affirmative_pattern = re.compile(
            r"(?<!not )(?<!refuses )(?<!refused )(?<!refusing )"
            r"(?<!refuse )(?<!blocks )(?<!blocked )" + re.escape(phrase)
        )
        if affirmative_pattern.search(safe_haystack):
            return _block(
                "REACT_LEARNING_STUDIO_VERIFIED_DEMO_STATUS_BINDING_BLOCKED_BROAD_CLAIM",
                f"evidence carries affirmative forbidden broad-claim phrase {phrase!r}",
            )

    # Pull the rendered fields.
    explanations = blob.get("explanations") or {}
    summary = blob.get("source_evidence_summary") or {}
    source_paths = tuple(blob.get("source_evidence_paths") or [])

    return LearningStudioVerifiedDemoStatus(
        decision="REACT_LEARNING_STUDIO_VERIFIED_DEMO_STATUS_BINDING_PASSED",
        demo_title=str(blob.get("record_id") or chosen.stem),
        target_surface=str(blob.get("target_surface") or "Learning Studio"),
        target_workflow=str(blob.get("target_workflow") or ""),
        teaching_subject=str(blob.get("teaching_subject") or ""),
        beginner_explanation_written=True,
        pro_explanation_written=True,
        failure_explanation_written=True,
        safe_next_steps_written=True,
        what_this_does_not_prove_written=True,
        verifier_grounding_present=True,
        non_authorizing_teaching_only=True,
        beginner_explanation=str(explanations.get("beginner") or ""),
        professional_explanation=str(explanations.get("professional") or ""),
        what_failed=str(explanations.get("what_failed") or ""),
        why_fix_or_update_worked=str(explanations.get("why_fix_or_update_worked") or ""),
        safe_next_steps=str(explanations.get("safe_next_steps") or ""),
        what_this_does_not_prove=str(explanations.get("what_this_does_not_prove") or ""),
        source_mutation_authorized=False,
        approval_authority_granted=False,
        training_eligible=False,
        training_rows_written=False,
        release_ready=False,
        broad_claims_granted=False,
        real_user_source_mutation_authorized=False,
        source_evidence_paths=tuple(str(p) for p in source_paths),
        final_report_path=str(blob.get("final_report_path") or ""),
        evidence_manifest_path=str(blob.get("evidence_manifest_path") or ""),
        evidence_ref=str(chosen.as_posix()),
        repo_clinic_source_summary=dict(summary.get("repo_clinic") or {}),
        maintenance_bay_source_summary=dict(summary.get("maintenance_bay") or {}),
        claim_boundary=tuple(str(b) for b in boundary_list),
        blocked_path_summary=_blocked_path_summary(blob),
        notes=(
            "evidence read from Codex Learning Studio teaching splash demo bundle",
            "teaching outputs are non-authorizing by construction",
            "explanations are grounded in existing verified Repo Clinic + Maintenance Bay evidence",
            "source mutation, approval, training, release all remain False",
        ),
    )


__all__ = [
    "load",
    "REQUIRED_BOUNDARY_STATEMENTS",
    "LEARNING_STUDIO_VERIFIED_DEMO_STATUS_BINDING_STATUS_TOKENS",
    "LearningStudioVerifiedDemoStatus",
]
