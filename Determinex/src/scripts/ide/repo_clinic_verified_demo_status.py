"""Repo Clinic verified demo status loader.

DETERMINEX_REACT_REPO_CLINIC_VERIFIED_DEMO_STATUS_BINDING_LOCK_001.

load() reads the Codex Repo Clinic fixture-repair splash demo
evidence (if present locally) and produces a render-safe view-model
the React Repo Clinic panel can display. If the evidence file is
not present, returns an AWAITING_EVIDENCE record — the UI must
show "Awaiting Codex reconciliation" rather than fake a verified
status.

The loader is read-only. It does NOT call the network, does NOT
spawn subprocesses, does NOT write training rows, does NOT
broaden the scoped demo claim.

Hard rules enforced by load():

  * source_mutation_authorized / real_user_source_mutation_authorized
    / training_eligible / approval_authority_granted / broad_claims_
    granted True in evidence -> BLOCKED_AUTHORITY_CONFUSION
  * fixture_mutation_only != True -> BLOCKED_AUTHORITY_CONFUSION
  * status != REPO_CLINIC_FIXTURE_REPAIR_SPLASH_DEMO_PASSED ->
    BLOCKED_MALFORMED
  * verification.repair_verified True but baseline_failed False
    or repair_tests_passed False or false_fixed_claim_blocked
    False -> BLOCKED_AUTHORITY_CONFUSION
  * claim_boundary missing one of the required scope statements
    -> BLOCKED_BROAD_CLAIM
  * affirmative forbidden broad-claim phrase appears OUTSIDE
    verification.blocked_path_demo AND evidence.claim_scanner_result
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

from .repo_clinic_verified_demo_status_record import (
    FORBIDDEN_BROAD_CLAIM_PHRASES,
    REPO_CLINIC_VERIFIED_DEMO_STATUS_BINDING_STATUS_TOKENS,
    RepoClinicVerifiedDemoStatus,
)

# Required boundary statements every reconciled demo evidence must
# include in claim_boundary. Missing any of these = BLOCKED_BROAD_CLAIM.
REQUIRED_BOUNDARY_STATEMENTS = (
    "Repo Clinic Python fixture repair demo only",
    "fixture/demo workspace mutation only",
    "not all codebases",
    "not all languages",
    "not arbitrary repair",
    "training remains false",
)


_DEFAULT_EVIDENCE_DIR = (
    Path(__file__).resolve().parents[2]
    / "assurance"
    / "evidence"
    / "repo_clinic_fixture_repair_splash_demo"
)


def _locate_latest_evidence(evidence_dir: Path) -> Path | None:
    if not evidence_dir.is_dir():
        return None
    candidates = sorted(evidence_dir.glob("run_*.json"))
    return candidates[-1] if candidates else None


def _awaiting(note: str) -> RepoClinicVerifiedDemoStatus:
    return RepoClinicVerifiedDemoStatus(
        decision="REACT_REPO_CLINIC_VERIFIED_DEMO_STATUS_BINDING_AWAITING_EVIDENCE",
        demo_title="(awaiting Codex reconciliation)",
        target_surface="Repo Clinic",
        target_workflow="(awaiting evidence)",
        target_language="(awaiting evidence)",
        issue_summary="(awaiting evidence)",
        baseline_failed=False,
        baseline_test_command="",
        repair_test_command="",
        repair_tests_passed=False,
        repair_verified=False,
        false_fixed_claim_blocked=False,
        fixture_mutation_only=True,
        real_user_source_mutation_authorized=False,
        affected_files=(),
        evidence_ref="",
        patch_body_hash="",
        fixture_workspace="",
        claim_boundary=(
            "no verified Repo Clinic fixture repair evidence available locally yet",
            "training remains false",
        ),
        blocked_path_summary=(),
        source_mutation_authorized=False,
        training_eligible=False,
        notes=(note,),
    )


def _block(decision: str, note: str) -> RepoClinicVerifiedDemoStatus:
    return RepoClinicVerifiedDemoStatus(
        decision=decision,
        demo_title="(blocked)",
        target_surface="Repo Clinic",
        target_workflow="(blocked)",
        target_language="(blocked)",
        issue_summary="(blocked)",
        baseline_failed=False,
        baseline_test_command="",
        repair_test_command="",
        repair_tests_passed=False,
        repair_verified=False,
        false_fixed_claim_blocked=False,
        fixture_mutation_only=False,
        real_user_source_mutation_authorized=False,
        affected_files=(),
        evidence_ref="",
        patch_body_hash="",
        fixture_workspace="",
        claim_boundary=(),
        blocked_path_summary=(),
        source_mutation_authorized=False,
        training_eligible=False,
        notes=(note,),
    )


def _blocked_path_summary(blob: dict) -> tuple[str, ...]:
    """Extract the operator-visible blocked-path titles from the
    verification.blocked_path_demo section. Each scenario shows
    'attempt' + 'blocked: true' — we render a short summary line
    per scenario."""
    out: list[str] = []
    section = (blob.get("verification") or {}).get("blocked_path_demo") or {}
    for key, val in section.items():
        if not isinstance(val, dict):
            continue
        blocked = bool(val.get("blocked"))
        if not blocked:
            continue
        attempt = str(val.get("attempt") or key)
        out.append(f"{key}: {attempt}")
    return tuple(sorted(out))


def load(evidence_dir: Path | str | None = None) -> RepoClinicVerifiedDemoStatus:
    ed = Path(evidence_dir) if evidence_dir else _DEFAULT_EVIDENCE_DIR
    chosen = _locate_latest_evidence(ed)
    if chosen is None:
        return _awaiting(f"no evidence file under {ed}")

    try:
        blob = json.loads(chosen.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return _awaiting(f"could not read evidence: {exc}")

    # Status must be PASSED — anything else short-circuits to MALFORMED.
    if blob.get("status") != "REPO_CLINIC_FIXTURE_REPAIR_SPLASH_DEMO_PASSED":
        return _block(
            "REACT_REPO_CLINIC_VERIFIED_DEMO_STATUS_BINDING_BLOCKED_MALFORMED",
            f"evidence status={blob.get('status')!r} (expected PASSED)",
        )

    # Aggregate-invariant gates.
    auth = blob.get("authority") or {}
    if blob.get("source_mutation_authorized") is True:
        return _block(
            "REACT_REPO_CLINIC_VERIFIED_DEMO_STATUS_BINDING_BLOCKED_AUTHORITY_CONFUSION",
            "evidence declares source_mutation_authorized=True",
        )
    if blob.get("training_eligible") is True:
        return _block(
            "REACT_REPO_CLINIC_VERIFIED_DEMO_STATUS_BINDING_BLOCKED_AUTHORITY_CONFUSION",
            "evidence declares training_eligible=True",
        )
    if auth.get("approval_authority_granted") is True:
        return _block(
            "REACT_REPO_CLINIC_VERIFIED_DEMO_STATUS_BINDING_BLOCKED_AUTHORITY_CONFUSION",
            "evidence declares approval_authority_granted=True",
        )
    if auth.get("real_user_source_mutation_authorized") is True:
        return _block(
            "REACT_REPO_CLINIC_VERIFIED_DEMO_STATUS_BINDING_BLOCKED_AUTHORITY_CONFUSION",
            "evidence declares real_user_source_mutation_authorized=True",
        )
    if auth.get("broad_claims_granted") is True:
        return _block(
            "REACT_REPO_CLINIC_VERIFIED_DEMO_STATUS_BINDING_BLOCKED_BROAD_CLAIM",
            "evidence declares broad_claims_granted=True",
        )
    if blob.get("real_user_source_mutation_authorized") is True:
        return _block(
            "REACT_REPO_CLINIC_VERIFIED_DEMO_STATUS_BINDING_BLOCKED_AUTHORITY_CONFUSION",
            "evidence top-level declares real_user_source_mutation_authorized=True",
        )
    if blob.get("fixture_mutation_only") is not True:
        return _block(
            "REACT_REPO_CLINIC_VERIFIED_DEMO_STATUS_BINDING_BLOCKED_AUTHORITY_CONFUSION",
            "evidence does not assert fixture_mutation_only=True",
        )

    # Boundary statements present?
    boundary_list = blob.get("claim_boundary") or []
    boundary_joined = " ; ".join(str(b) for b in boundary_list).lower()
    missing_required = [
        req for req in REQUIRED_BOUNDARY_STATEMENTS if req.lower() not in boundary_joined
    ]
    if missing_required:
        return _block(
            "REACT_REPO_CLINIC_VERIFIED_DEMO_STATUS_BINDING_BLOCKED_BROAD_CLAIM",
            f"evidence claim_boundary missing required statements: {missing_required!r}",
        )

    # Strip subsections that legitimately mention the forbidden
    # phrases as REFUSED attempts (verification.blocked_path_demo),
    # as scanner input/patterns (evidence.claim_scanner_result), or
    # as negation statements (claim_boundary entries like 'not
    # production-ready arbitrary repair' — the negation here is
    # 'not production-ready' which the per-phrase regex would not
    # catch). claim_boundary is already validated against
    # REQUIRED_BOUNDARY_STATEMENTS above; we do not also scan it.
    safe = {k: v for k, v in blob.items() if k not in ("verification", "claim_boundary")}
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
                "REACT_REPO_CLINIC_VERIFIED_DEMO_STATUS_BINDING_BLOCKED_BROAD_CLAIM",
                f"evidence carries affirmative forbidden broad-claim phrase {phrase!r}",
            )

    # Verification subsection coherence.
    ver = blob.get("verification") or {}
    baseline_failed = bool(ver.get("baseline_failed"))
    repair_tests_passed = bool(ver.get("repair_tests_passed"))
    repair_verified = bool(ver.get("repair_verified"))
    false_fixed_claim_blocked = bool(ver.get("false_fixed_claim_blocked"))

    if repair_verified and not (
        baseline_failed and repair_tests_passed and false_fixed_claim_blocked
    ):
        return _block(
            "REACT_REPO_CLINIC_VERIFIED_DEMO_STATUS_BINDING_BLOCKED_AUTHORITY_CONFUSION",
            (
                "repair_verified=True without "
                f"baseline_failed={baseline_failed} / "
                f"repair_tests_passed={repair_tests_passed} / "
                f"false_fixed_claim_blocked={false_fixed_claim_blocked}"
            ),
        )

    artifacts = blob.get("artifacts") or {}
    quarantined = artifacts.get("quarantined_patch") or {}
    affected_files = tuple(quarantined.get("affected_files") or [])
    patch_body_hash = str(
        quarantined.get("patch_body_hash")
        or (blob.get("evidence") or {}).get("patch_body_hash")
        or ""
    )

    return RepoClinicVerifiedDemoStatus(
        decision="REACT_REPO_CLINIC_VERIFIED_DEMO_STATUS_BINDING_PASSED",
        demo_title=str(blob.get("record_id") or chosen.stem),
        target_surface=str(blob.get("target_surface") or "Repo Clinic"),
        target_workflow=str(blob.get("target_workflow") or ""),
        target_language=str(blob.get("target_language") or ""),
        issue_summary=str(blob.get("issue_summary") or ""),
        baseline_failed=baseline_failed,
        baseline_test_command=str(ver.get("baseline_test_command") or ""),
        repair_test_command=str(ver.get("repair_test_command") or ""),
        repair_tests_passed=repair_tests_passed,
        repair_verified=repair_verified,
        false_fixed_claim_blocked=false_fixed_claim_blocked,
        fixture_mutation_only=True,
        real_user_source_mutation_authorized=False,
        affected_files=affected_files,
        evidence_ref=str(chosen.as_posix()),
        patch_body_hash=patch_body_hash,
        fixture_workspace=str(blob.get("fixture_workspace") or ""),
        claim_boundary=tuple(str(b) for b in boundary_list),
        blocked_path_summary=_blocked_path_summary(blob),
        source_mutation_authorized=False,
        training_eligible=False,
        notes=(
            "evidence read from Codex Repo Clinic fixture-repair demo bundle",
            "verified ONLY for this Python fixture repair path",
            "real user source mutation NOT authorized; training remains false",
        ),
    )


__all__ = [
    "load",
    "REQUIRED_BOUNDARY_STATEMENTS",
    "REPO_CLINIC_VERIFIED_DEMO_STATUS_BINDING_STATUS_TOKENS",
    "RepoClinicVerifiedDemoStatus",
]
