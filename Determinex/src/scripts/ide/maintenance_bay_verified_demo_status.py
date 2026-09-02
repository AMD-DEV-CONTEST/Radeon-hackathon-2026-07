"""Maintenance Bay verified demo status loader.

DETERMINEX_REACT_MAINTENANCE_BAY_VERIFIED_DEMO_STATUS_BINDING_LOCK_001.

load() reads the Codex Maintenance Bay dry-run/update splash demo
evidence (if present locally) and produces a render-safe view-model
the React Maintenance Bay panel can display. If the evidence file
is not present, returns an AWAITING_EVIDENCE record — the UI must
show "Awaiting Codex reconciliation" rather than fake a verified
status.

The loader is read-only. It does NOT call the network, does NOT
spawn subprocesses, does NOT write training rows, does NOT
broaden the scoped demo claim.

Hard rules enforced by load():

  * status != MAINTENANCE_BAY_DRY_RUN_UPDATE_SPLASH_DEMO_PASSED
    -> BLOCKED_MALFORMED
  * source_mutation_authorized / training_eligible /
    training_rows_written / authority.real_user_source_mutation_
    authorized / authority.approval_authority_granted / top-level
    real_user_source_mutation_authorized True
    -> BLOCKED_AUTHORITY_CONFUSION
  * authority.broad_claims_granted True -> BLOCKED_BROAD_CLAIM
  * fixture_mutation_only != True -> BLOCKED_AUTHORITY_CONFUSION
  * compatibility_verified != True -> BLOCKED_AUTHORITY_CONFUSION
    (panel cannot render 'updated/maintained' without compatibility
    verifier evidence)
  * post_change_tests_passed != True -> BLOCKED_AUTHORITY_CONFUSION
  * claim_boundary missing required statements -> BLOCKED_BROAD_CLAIM
  * affirmative forbidden broad-claim phrase appears OUTSIDE
    verification.blocked_path_demo + evidence.claim_scanner_result
    + claim_boundary + top-level blocked_path_demo
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

from .maintenance_bay_verified_demo_status_record import (
    FORBIDDEN_BROAD_CLAIM_PHRASES,
    MAINTENANCE_BAY_VERIFIED_DEMO_STATUS_BINDING_STATUS_TOKENS,
    MaintenanceBayVerifiedDemoStatus,
)

# Required boundary statements every reconciled demo evidence must
# include in claim_boundary. Missing any of these = BLOCKED_BROAD_CLAIM.
REQUIRED_BOUNDARY_STATEMENTS = (
    "Maintenance Bay Python fixture dry-run demo only",
    "fixture compatibility workspace mutation only",
    "not all projects",
    "not all languages",
    "not arbitrary maintenance",
    "not production-ready maintenance",
    "training remains false",
)


_DEFAULT_EVIDENCE_DIR = (
    Path(__file__).resolve().parents[2]
    / "assurance"
    / "evidence"
    / "maintenance_bay_dry_run_update_splash_demo"
)


def _locate_latest_evidence(evidence_dir: Path) -> Path | None:
    if not evidence_dir.is_dir():
        return None
    candidates = sorted(evidence_dir.glob("run_*.json"))
    return candidates[-1] if candidates else None


def _awaiting(note: str) -> MaintenanceBayVerifiedDemoStatus:
    return MaintenanceBayVerifiedDemoStatus(
        decision="REACT_MAINTENANCE_BAY_VERIFIED_DEMO_STATUS_BINDING_AWAITING_EVIDENCE",
        demo_title="(awaiting Codex reconciliation)",
        target_surface="Maintenance Bay",
        target_workflow="(awaiting evidence)",
        target_language="(awaiting evidence)",
        target_stack="(awaiting evidence)",
        maintenance_issue_summary="(awaiting evidence)",
        change_type="(awaiting evidence)",
        baseline_failed=False,
        baseline_test_command="",
        compatibility_verifier_command="",
        compatibility_verified=False,
        post_change_tests_passed=False,
        false_updated_claim_blocked=False,
        false_maintained_claim_blocked=False,
        unsafe_real_repo_mutation_blocked=False,
        unsupported_all_projects_claim_blocked=False,
        training_eligibility_without_positive_gate_blocked=False,
        release_deploy_readiness_claim_blocked=False,
        fixture_mutation_only=True,
        real_user_source_mutation_authorized=False,
        affected_files=(),
        evidence_ref="",
        change_body_hash="",
        fixture_workspace="",
        compatibility_workspace="",
        source_repo_workspace="",
        claim_boundary=(
            "no verified Maintenance Bay dry-run/update evidence available locally yet",
            "training remains false",
        ),
        blocked_path_summary=(),
        source_mutation_authorized=False,
        training_eligible=False,
        training_rows_written=False,
        notes=(note,),
    )


def _block(decision: str, note: str) -> MaintenanceBayVerifiedDemoStatus:
    return MaintenanceBayVerifiedDemoStatus(
        decision=decision,
        demo_title="(blocked)",
        target_surface="Maintenance Bay",
        target_workflow="(blocked)",
        target_language="(blocked)",
        target_stack="(blocked)",
        maintenance_issue_summary="(blocked)",
        change_type="(blocked)",
        baseline_failed=False,
        baseline_test_command="",
        compatibility_verifier_command="",
        compatibility_verified=False,
        post_change_tests_passed=False,
        false_updated_claim_blocked=False,
        false_maintained_claim_blocked=False,
        unsafe_real_repo_mutation_blocked=False,
        unsupported_all_projects_claim_blocked=False,
        training_eligibility_without_positive_gate_blocked=False,
        release_deploy_readiness_claim_blocked=False,
        fixture_mutation_only=False,
        real_user_source_mutation_authorized=False,
        affected_files=(),
        evidence_ref="",
        change_body_hash="",
        fixture_workspace="",
        compatibility_workspace="",
        source_repo_workspace="",
        claim_boundary=(),
        blocked_path_summary=(),
        source_mutation_authorized=False,
        training_eligible=False,
        training_rows_written=False,
        notes=(note,),
    )


def _blocked_path_summary(blob: dict) -> tuple[str, ...]:
    """Extract operator-visible blocked-path titles. The Maintenance
    Bay evidence carries blocked_path_demo at both the top level AND
    under verification — we take the verification copy as canonical
    and fall back to top-level."""
    out: list[str] = []
    section = (blob.get("verification") or {}).get("blocked_path_demo")
    if not section:
        section = blob.get("blocked_path_demo") or {}
    if isinstance(section, dict):
        for key, val in section.items():
            if not isinstance(val, dict):
                continue
            if not val.get("blocked"):
                continue
            attempt = str(val.get("attempt") or key)
            out.append(f"{key}: {attempt}")
    return tuple(sorted(out))


def load(evidence_dir: Path | str | None = None) -> MaintenanceBayVerifiedDemoStatus:
    ed = Path(evidence_dir) if evidence_dir else _DEFAULT_EVIDENCE_DIR
    chosen = _locate_latest_evidence(ed)
    if chosen is None:
        return _awaiting(f"no evidence file under {ed}")

    try:
        blob = json.loads(chosen.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return _awaiting(f"could not read evidence: {exc}")

    # Status must be PASSED — anything else short-circuits.
    if blob.get("status") != "MAINTENANCE_BAY_DRY_RUN_UPDATE_SPLASH_DEMO_PASSED":
        return _block(
            "REACT_MAINTENANCE_BAY_VERIFIED_DEMO_STATUS_BINDING_BLOCKED_MALFORMED",
            f"evidence status={blob.get('status')!r} (expected PASSED)",
        )

    # Aggregate-invariant gates.
    auth = blob.get("authority") or {}
    if blob.get("source_mutation_authorized") is True:
        return _block(
            "REACT_MAINTENANCE_BAY_VERIFIED_DEMO_STATUS_BINDING_BLOCKED_AUTHORITY_CONFUSION",
            "evidence declares source_mutation_authorized=True",
        )
    if blob.get("training_eligible") is True:
        return _block(
            "REACT_MAINTENANCE_BAY_VERIFIED_DEMO_STATUS_BINDING_BLOCKED_AUTHORITY_CONFUSION",
            "evidence declares training_eligible=True",
        )
    if blob.get("training_rows_written") is True:
        return _block(
            "REACT_MAINTENANCE_BAY_VERIFIED_DEMO_STATUS_BINDING_BLOCKED_AUTHORITY_CONFUSION",
            "evidence declares training_rows_written=True",
        )
    if auth.get("approval_authority_granted") is True:
        return _block(
            "REACT_MAINTENANCE_BAY_VERIFIED_DEMO_STATUS_BINDING_BLOCKED_AUTHORITY_CONFUSION",
            "evidence declares approval_authority_granted=True",
        )
    if auth.get("real_user_source_mutation_authorized") is True:
        return _block(
            "REACT_MAINTENANCE_BAY_VERIFIED_DEMO_STATUS_BINDING_BLOCKED_AUTHORITY_CONFUSION",
            "evidence declares authority.real_user_source_mutation_authorized=True",
        )
    if auth.get("broad_claims_granted") is True:
        return _block(
            "REACT_MAINTENANCE_BAY_VERIFIED_DEMO_STATUS_BINDING_BLOCKED_BROAD_CLAIM",
            "evidence declares broad_claims_granted=True",
        )
    if blob.get("real_user_source_mutation_authorized") is True:
        return _block(
            "REACT_MAINTENANCE_BAY_VERIFIED_DEMO_STATUS_BINDING_BLOCKED_AUTHORITY_CONFUSION",
            "evidence top-level declares real_user_source_mutation_authorized=True",
        )
    if blob.get("fixture_mutation_only") is not True:
        return _block(
            "REACT_MAINTENANCE_BAY_VERIFIED_DEMO_STATUS_BINDING_BLOCKED_AUTHORITY_CONFUSION",
            "evidence does not assert fixture_mutation_only=True",
        )

    # Compatibility verifier + post-change tests are required for any
    # 'updated/maintained' rendering. The 'updated/maintained' badge
    # in the React panel is gated on these being True.
    if blob.get("compatibility_verified") is not True:
        return _block(
            "REACT_MAINTENANCE_BAY_VERIFIED_DEMO_STATUS_BINDING_BLOCKED_AUTHORITY_CONFUSION",
            "evidence does not assert compatibility_verified=True",
        )
    if blob.get("post_change_tests_passed") is not True:
        return _block(
            "REACT_MAINTENANCE_BAY_VERIFIED_DEMO_STATUS_BINDING_BLOCKED_AUTHORITY_CONFUSION",
            "evidence does not assert post_change_tests_passed=True",
        )

    # Boundary statements present?
    boundary_list = blob.get("claim_boundary") or []
    boundary_joined = " ; ".join(str(b) for b in boundary_list).lower()
    missing_required = [
        req for req in REQUIRED_BOUNDARY_STATEMENTS if req.lower() not in boundary_joined
    ]
    if missing_required:
        return _block(
            "REACT_MAINTENANCE_BAY_VERIFIED_DEMO_STATUS_BINDING_BLOCKED_BROAD_CLAIM",
            f"evidence claim_boundary missing required statements: {missing_required!r}",
        )

    # Strip subsections that legitimately mention the forbidden
    # phrases as REFUSED attempts (top-level blocked_path_demo,
    # verification.blocked_path_demo), as scanner input/patterns
    # (evidence.claim_scanner_result), or as negation statements
    # (claim_boundary, since negations like 'not production-ready
    # maintenance' embed the phrase without a 'not ' immediately
    # adjacent to it).
    safe = {
        k: v
        for k, v in blob.items()
        if k not in ("verification", "claim_boundary", "blocked_path_demo")
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
                "REACT_MAINTENANCE_BAY_VERIFIED_DEMO_STATUS_BINDING_BLOCKED_BROAD_CLAIM",
                f"evidence carries affirmative forbidden broad-claim phrase {phrase!r}",
            )

    # Pull the rendered fields from the now-validated evidence.
    ver = blob.get("verification") or {}
    artifacts = blob.get("artifacts") or {}
    quarantined = artifacts.get("quarantined_change") or {}
    diagnosis = artifacts.get("maintenance_diagnosis") or {}
    affected_files = tuple(quarantined.get("affected_files") or [])
    change_body_hash = str(
        quarantined.get("change_body_hash")
        or (blob.get("evidence") or {}).get("change_body_hash")
        or ""
    )

    baseline_failed = bool(ver.get("baseline_failed"))
    baseline_test_command = str(ver.get("baseline_test_command") or "")
    compatibility_verifier_command = str(ver.get("compatibility_verifier_command") or "")
    false_updated_claim_blocked = bool(
        ver.get("false_updated_claim_blocked") or blob.get("false_updated_claim_blocked")
    )
    false_maintained_claim_blocked = bool(
        ver.get("false_maintained_claim_blocked") or blob.get("false_maintained_claim_blocked")
    )

    return MaintenanceBayVerifiedDemoStatus(
        decision="REACT_MAINTENANCE_BAY_VERIFIED_DEMO_STATUS_BINDING_PASSED",
        demo_title=str(blob.get("record_id") or chosen.stem),
        target_surface=str(blob.get("target_surface") or "Maintenance Bay"),
        target_workflow=str(blob.get("target_workflow") or ""),
        target_language=str(blob.get("target_language") or ""),
        target_stack=str(blob.get("target_stack") or ""),
        maintenance_issue_summary=str(
            blob.get("maintenance_issue_summary") or diagnosis.get("maintenance_issue") or ""
        ),
        change_type=str(
            (artifacts.get("maintenance_plan") or {}).get("plan_type")
            or "quarantined config/docs cleanup only"
        ),
        baseline_failed=baseline_failed,
        baseline_test_command=baseline_test_command,
        compatibility_verifier_command=compatibility_verifier_command,
        compatibility_verified=True,
        post_change_tests_passed=True,
        false_updated_claim_blocked=false_updated_claim_blocked,
        false_maintained_claim_blocked=false_maintained_claim_blocked,
        unsafe_real_repo_mutation_blocked=bool(blob.get("unsafe_real_repo_mutation_blocked")),
        unsupported_all_projects_claim_blocked=bool(
            blob.get("unsupported_all_projects_claim_blocked")
        ),
        training_eligibility_without_positive_gate_blocked=bool(
            blob.get("training_eligibility_without_positive_gate_blocked")
        ),
        release_deploy_readiness_claim_blocked=bool(
            blob.get("release_deploy_readiness_claim_blocked")
        ),
        fixture_mutation_only=True,
        real_user_source_mutation_authorized=False,
        affected_files=affected_files,
        evidence_ref=str(chosen.as_posix()),
        change_body_hash=change_body_hash,
        fixture_workspace=str(blob.get("fixture_workspace") or ""),
        compatibility_workspace=str(blob.get("compatibility_workspace") or ""),
        source_repo_workspace=str(blob.get("source_repo_workspace") or ""),
        claim_boundary=tuple(str(b) for b in boundary_list),
        blocked_path_summary=_blocked_path_summary(blob),
        source_mutation_authorized=False,
        training_eligible=False,
        training_rows_written=False,
        notes=(
            "evidence read from Codex Maintenance Bay dry-run/update demo bundle",
            "verified ONLY for this Python fixture dry-run/update path",
            "real user repo mutation NOT authorized; training remains false",
            "updated/maintained label gated on compatibility verifier + post-change tests",
        ),
    )


__all__ = [
    "load",
    "REQUIRED_BOUNDARY_STATEMENTS",
    "MAINTENANCE_BAY_VERIFIED_DEMO_STATUS_BINDING_STATUS_TOKENS",
    "MaintenanceBayVerifiedDemoStatus",
]
