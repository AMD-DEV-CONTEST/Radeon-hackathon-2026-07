"""Proof / Operator Center milestone dashboard status loader.

DETERMINEX_REACT_PROOF_OPERATOR_CENTER_MILESTONE_DASHBOARD_BINDING_LOCK_001.

load() reads the Codex Proof / Operator Center milestone dashboard
evidence (if present locally) and produces a render-safe view-model
the React Proof / Operator Center panel can display. If the
evidence file is not present, returns an AWAITING_EVIDENCE record —
the UI must show "Awaiting Codex reconciliation" rather than fake
a passed dashboard.

The dashboard DISPLAYS authority; it does not GRANT authority. Even
at PASSED, the binding remains read-only: no field implies source
mutation, approval, proof-execution authority, training, or release
readiness. Roadmap items (Cathedral Index, Columbia House Tracker,
Scale-to-100, Full Cathedral roadmap, Windows-first matrix, public
claims ledger, release scrub, fresh install / demo workflow) are
not converted into product truth.

The loader is read-only. It does NOT call the network, does NOT
spawn subprocesses, does NOT write training rows.

Hard rules enforced by load():

  * status != PROOF_OPERATOR_CENTER_MILESTONE_DASHBOARD_PASSED
    -> BLOCKED_MALFORMED
  * source_mutation_authorized / training_eligible /
    training_rows_written / approval_authority_granted /
    release_ready / proof_execution_authority_granted /
    release_deploy_workflow_created / artifact_import_authorized /
    benchmark_execution_authorized /
    programbench_execution_authorized True at top level or under
    authority_status -> BLOCKED_AUTHORITY_CONFUSION
  * broad_claims_granted True at top level or under
    authority_status -> BLOCKED_BROAD_CLAIM
  * release_gate_status.release_ready True -> BLOCKED_AUTHORITY_CONFUSION
  * release_gate_status.columbia_house_tracker not in {pending,
    pending_not_built} -> BLOCKED_BROAD_CLAIM
  * scale_to_100_status.normalized_as_current_ct_lock True
    -> BLOCKED_BROAD_CLAIM
  * surface_statuses[*].react_bound == True for Proof / Operator
    Center (means dashboard pretends a React binding already exists
    inside the dashboard evidence itself) -> BLOCKED_MALFORMED
  * surface_statuses missing a five-room entry
    -> BLOCKED_MALFORMED
  * evidence_health.count_drift_status not in {
    EVIDENCE_COUNT_DRIFT_GUARD_PASSED} -> BLOCKED_MALFORMED
  * evidence_health.append_only_ledger_chain_valid != True
    -> BLOCKED_MALFORMED
  * evidence_health.evidence_index_valid != True
    -> BLOCKED_MALFORMED
  * claim_boundary missing required statements
    -> BLOCKED_BROAD_CLAIM
  * affirmative forbidden broad-claim phrase outside
    blocked_path_demo / claim_boundary / claim_boundary_status /
    surface_statuses / source_evidence_paths / source_audit_paths /
    forbidden_claims -> BLOCKED_BROAD_CLAIM
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

from .proof_operator_center_milestone_dashboard_status_record import (
    FORBIDDEN_BROAD_CLAIM_PHRASES,
    REACT_PROOF_OPERATOR_CENTER_MILESTONE_DASHBOARD_BINDING_STATUS_TOKENS,
    ProofOperatorCenterMilestoneDashboardStatus,
    SurfaceStatus,
)

REQUIRED_BOUNDARY_STATEMENTS = (
    "Proof / Operator Center milestone dashboard only",
    "evidence dashboard is read-only",
    "not release ready",
    "source mutation remains false",
    "approval authority remains false",
    "proof execution authority remains false",
    "training remains false",
    "not all apps",
    "not all languages",
    "not all platforms",
    "Scale-to-100 remains roadmap draft, not current C&T lock",
    "Columbia House Tracker remains pending",
)


REQUIRED_SURFACES = (
    "Idea Lab",
    "Repo Clinic",
    "Maintenance Bay",
    "Learning Studio",
    "Proof / Operator Center",
)


_DEFAULT_EVIDENCE_DIR = (
    Path(__file__).resolve().parents[2]
    / "assurance"
    / "evidence"
    / "proof_operator_center_milestone_dashboard"
)


def _locate_latest_evidence(evidence_dir: Path) -> Path | None:
    if not evidence_dir.is_dir():
        return None
    candidates = sorted(evidence_dir.glob("run_*.json"))
    return candidates[-1] if candidates else None


def _zero_surface() -> tuple[SurfaceStatus, ...]:
    return tuple()


def _awaiting(note: str) -> ProofOperatorCenterMilestoneDashboardStatus:
    return ProofOperatorCenterMilestoneDashboardStatus(
        decision=("REACT_PROOF_OPERATOR_CENTER_MILESTONE_DASHBOARD_BINDING_AWAITING_EVIDENCE"),
        target_surface="Proof / Operator Center",
        target_workflow="(awaiting evidence)",
        dashboard_title="(awaiting Codex reconciliation)",
        source_mutation_authorized=False,
        approval_authority_granted=False,
        proof_execution_authority_granted=False,
        training_eligible=False,
        training_rows_written=False,
        release_ready=False,
        broad_claims_granted=False,
        artifact_import_authorized=False,
        benchmark_execution_authorized=False,
        programbench_execution_authorized=False,
        release_deploy_workflow_created=False,
        surfaces=_zero_surface(),
        cathedral_index_status="(awaiting)",
        columbia_house_tracker_status="(awaiting)",
        public_claims_ledger_status="(awaiting)",
        release_repo_scrub_status="(awaiting)",
        fresh_install_demo_workflow_status="(awaiting)",
        windows_first_support_matrix_status="(awaiting)",
        release_ready_label="release_ready: false (remains false)",
        scale_to_100_claim_truth_status="(awaiting)",
        scale_to_100_normalized_as_current_ct_lock=False,
        scale_to_100_scaling_plan_exists=False,
        scale_to_100_corpus_training_reconciliation_lock="(awaiting)",
        scale_to_100_platform_language_appclass_expansion_queue="(awaiting)",
        scale_to_100_windows_first_matrix_lock="(awaiting)",
        scale_to_100_legacy_enterprise="(awaiting)",
        scale_to_100_audit_path="",
        evidence_index_count=0,
        evidence_index_entry_count_field=0,
        evidence_index_valid=False,
        append_only_ledger_status="(awaiting)",
        append_only_ledger_chain_valid=False,
        append_only_ledger_entry_count=0,
        count_drift_status="(awaiting)",
        count_drift_expected=0,
        count_drift_actual=0,
        json_parse_status="(awaiting)",
        claim_boundary=(
            "no verified Proof / Operator Center milestone dashboard "
            "evidence available locally yet",
            "release readiness remains false",
            "training remains false",
        ),
        blocked_path_summary=(),
        forbidden_claims=(),
        implemented_narrow_rooms=(),
        implemented_with_caveats=(),
        roadmap_items=(),
        source_evidence_paths=(),
        source_audit_paths=(),
        dashboard_report_path="",
        machine_readable_dashboard_path="",
        evidence_ref="",
        current_next_rung="",
        notes=(note,),
    )


def _block(decision: str, note: str) -> ProofOperatorCenterMilestoneDashboardStatus:
    return ProofOperatorCenterMilestoneDashboardStatus(
        decision=decision,
        target_surface="Proof / Operator Center",
        target_workflow="(blocked)",
        dashboard_title="(blocked)",
        source_mutation_authorized=False,
        approval_authority_granted=False,
        proof_execution_authority_granted=False,
        training_eligible=False,
        training_rows_written=False,
        release_ready=False,
        broad_claims_granted=False,
        artifact_import_authorized=False,
        benchmark_execution_authorized=False,
        programbench_execution_authorized=False,
        release_deploy_workflow_created=False,
        surfaces=_zero_surface(),
        cathedral_index_status="(blocked)",
        columbia_house_tracker_status="(blocked)",
        public_claims_ledger_status="(blocked)",
        release_repo_scrub_status="(blocked)",
        fresh_install_demo_workflow_status="(blocked)",
        windows_first_support_matrix_status="(blocked)",
        release_ready_label="release_ready: false (remains false)",
        scale_to_100_claim_truth_status="(blocked)",
        scale_to_100_normalized_as_current_ct_lock=False,
        scale_to_100_scaling_plan_exists=False,
        scale_to_100_corpus_training_reconciliation_lock="(blocked)",
        scale_to_100_platform_language_appclass_expansion_queue="(blocked)",
        scale_to_100_windows_first_matrix_lock="(blocked)",
        scale_to_100_legacy_enterprise="(blocked)",
        scale_to_100_audit_path="",
        evidence_index_count=0,
        evidence_index_entry_count_field=0,
        evidence_index_valid=False,
        append_only_ledger_status="(blocked)",
        append_only_ledger_chain_valid=False,
        append_only_ledger_entry_count=0,
        count_drift_status="(blocked)",
        count_drift_expected=0,
        count_drift_actual=0,
        json_parse_status="(blocked)",
        claim_boundary=(),
        blocked_path_summary=(),
        forbidden_claims=(),
        implemented_narrow_rooms=(),
        implemented_with_caveats=(),
        roadmap_items=(),
        source_evidence_paths=(),
        source_audit_paths=(),
        dashboard_report_path="",
        machine_readable_dashboard_path="",
        evidence_ref="",
        current_next_rung="",
        notes=(note,),
    )


def _blocked_path_summary(blob: dict) -> tuple[str, ...]:
    """Operator-visible blocked-path scenarios."""
    out: list[str] = []
    raw = blob.get("blocked_path_demo")
    if not isinstance(raw, list):
        return ()
    for item in raw:
        if not isinstance(item, dict):
            continue
        if not item.get("blocked"):
            continue
        scen = str(item.get("scenario") or "unknown")
        out.append(scen)
    return tuple(sorted(out))


_ALLOWED_COLUMBIA_HOUSE_STATES = ("pending", "pending_not_built")


def load(evidence_dir: Path | str | None = None) -> ProofOperatorCenterMilestoneDashboardStatus:
    ed = Path(evidence_dir) if evidence_dir else _DEFAULT_EVIDENCE_DIR
    chosen = _locate_latest_evidence(ed)
    if chosen is None:
        return _awaiting(f"no evidence file under {ed}")

    try:
        blob = json.loads(chosen.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return _awaiting(f"could not read evidence: {exc}")

    # Status must be PASSED.
    if blob.get("status") != "PROOF_OPERATOR_CENTER_MILESTONE_DASHBOARD_PASSED":
        return _block(
            "REACT_PROOF_OPERATOR_CENTER_MILESTONE_DASHBOARD_BINDING_BLOCKED_MALFORMED",
            f"evidence status={blob.get('status')!r} (expected PASSED)",
        )

    # Authority bag: every flag must be False (top-level or under authority_status).
    auth = blob.get("authority_status") or {}

    def _auth(flag: str) -> bool:
        return bool(blob.get(flag) is True or auth.get(flag) is True)

    authority_flags_to_block = (
        ("source_mutation_authorized", "AUTHORITY_CONFUSION"),
        ("training_eligible", "AUTHORITY_CONFUSION"),
        ("training_rows_written", "AUTHORITY_CONFUSION"),
        ("approval_authority_granted", "AUTHORITY_CONFUSION"),
        ("release_ready", "AUTHORITY_CONFUSION"),
        ("proof_execution_authority_granted", "AUTHORITY_CONFUSION"),
        ("release_deploy_workflow_created", "AUTHORITY_CONFUSION"),
        ("artifact_import_authorized", "AUTHORITY_CONFUSION"),
        ("benchmark_execution_authorized", "AUTHORITY_CONFUSION"),
        ("programbench_execution_authorized", "AUTHORITY_CONFUSION"),
        ("broad_claims_granted", "BROAD_CLAIM"),
    )
    for flag, kind in authority_flags_to_block:
        if _auth(flag):
            return _block(
                f"REACT_PROOF_OPERATOR_CENTER_MILESTONE_DASHBOARD_BINDING_BLOCKED_{kind}",
                f"evidence declares {flag}=True",
            )

    # release_gate_status block.
    rgs = blob.get("release_gate_status") or {}
    if rgs.get("release_ready") is True:
        return _block(
            "REACT_PROOF_OPERATOR_CENTER_MILESTONE_DASHBOARD_BINDING_BLOCKED_AUTHORITY_CONFUSION",
            "release_gate_status.release_ready=True",
        )
    columbia = str(rgs.get("columbia_house_tracker") or "").lower()
    if columbia and columbia not in _ALLOWED_COLUMBIA_HOUSE_STATES:
        return _block(
            "REACT_PROOF_OPERATOR_CENTER_MILESTONE_DASHBOARD_BINDING_BLOCKED_BROAD_CLAIM",
            f"release_gate_status.columbia_house_tracker={columbia!r} (expected pending/pending_not_built)",
        )

    # scale_to_100 must NOT be normalized as the current C&T lock.
    s100 = blob.get("scale_to_100_status") or {}
    if s100.get("normalized_as_current_ct_lock") is True:
        return _block(
            "REACT_PROOF_OPERATOR_CENTER_MILESTONE_DASHBOARD_BINDING_BLOCKED_BROAD_CLAIM",
            "scale_to_100_status.normalized_as_current_ct_lock=True",
        )

    # surface_statuses gates.
    surfaces_raw = blob.get("surface_statuses") or []
    if not isinstance(surfaces_raw, list):
        return _block(
            "REACT_PROOF_OPERATOR_CENTER_MILESTONE_DASHBOARD_BINDING_BLOCKED_MALFORMED",
            "surface_statuses is not a list",
        )
    surface_names = {str(s.get("surface")) for s in surfaces_raw if isinstance(s, dict)}
    missing = [n for n in REQUIRED_SURFACES if n not in surface_names]
    if missing:
        return _block(
            "REACT_PROOF_OPERATOR_CENTER_MILESTONE_DASHBOARD_BINDING_BLOCKED_MALFORMED",
            f"surface_statuses missing required surfaces: {missing!r}",
        )
    # Proof / Operator Center must NOT claim react_bound=True inside the
    # dashboard evidence (that pre-converts dashboard visibility into a
    # React binding that does not yet exist at the time of dashboard
    # generation).
    for s in surfaces_raw:
        if not isinstance(s, dict):
            continue
        if s.get("surface") == "Proof / Operator Center" and s.get("react_bound") is True:
            return _block(
                "REACT_PROOF_OPERATOR_CENTER_MILESTONE_DASHBOARD_BINDING_BLOCKED_MALFORMED",
                "dashboard evidence pre-declares react_bound=True for Proof / Operator Center",
            )

    # Evidence health gates.
    eh = blob.get("evidence_health") or {}
    if eh.get("count_drift_status") not in (
        "EVIDENCE_COUNT_DRIFT_GUARD_PASSED",
        # Accept the explicit explained-addition channel ONLY when the
        # binding-rung is reconciled by Codex; for now we require PASSED.
    ):
        return _block(
            "REACT_PROOF_OPERATOR_CENTER_MILESTONE_DASHBOARD_BINDING_BLOCKED_MALFORMED",
            f"evidence_health.count_drift_status={eh.get('count_drift_status')!r}",
        )
    if eh.get("append_only_ledger_chain_valid") is not True:
        return _block(
            "REACT_PROOF_OPERATOR_CENTER_MILESTONE_DASHBOARD_BINDING_BLOCKED_MALFORMED",
            "evidence_health.append_only_ledger_chain_valid is not True",
        )
    if eh.get("evidence_index_valid") is not True:
        return _block(
            "REACT_PROOF_OPERATOR_CENTER_MILESTONE_DASHBOARD_BINDING_BLOCKED_MALFORMED",
            "evidence_health.evidence_index_valid is not True",
        )

    # Required claim_boundary statements.
    boundary_list = blob.get("claim_boundary") or []
    boundary_joined = " ; ".join(str(b) for b in boundary_list).lower()
    missing_required = [
        req for req in REQUIRED_BOUNDARY_STATEMENTS if req.lower() not in boundary_joined
    ]
    if missing_required:
        return _block(
            "REACT_PROOF_OPERATOR_CENTER_MILESTONE_DASHBOARD_BINDING_BLOCKED_BROAD_CLAIM",
            f"evidence claim_boundary missing required statements: {missing_required!r}",
        )

    # Strip subsections that legitimately quote refused phrases /
    # roadmap labels / per-surface evidence_paths / scenarios / explicit
    # forbidden_claims lists, then scan the remainder for affirmative
    # forbidden broad-claim phrases.
    safe = {
        k: v
        for k, v in blob.items()
        if k
        not in (
            "blocked_path_demo",
            "claim_boundary",
            "claim_boundary_status",
            "surface_statuses",
            "source_evidence_paths",
            "source_audit_paths",
        )
    }
    # We also strip blocked_path_demo scenarios already counted.
    safe_haystack = json.dumps(safe).lower()
    for phrase in FORBIDDEN_BROAD_CLAIM_PHRASES:
        if phrase not in safe_haystack:
            continue
        affirmative_pattern = re.compile(
            r"(?<!not )(?<!no )(?<!refuses )(?<!refused )(?<!refusing )"
            r"(?<!refuse )(?<!blocks )(?<!blocked )" + re.escape(phrase)
        )
        if affirmative_pattern.search(safe_haystack):
            return _block(
                "REACT_PROOF_OPERATOR_CENTER_MILESTONE_DASHBOARD_BINDING_BLOCKED_BROAD_CLAIM",
                f"evidence carries affirmative forbidden broad-claim phrase {phrase!r}",
            )

    # All gates passed — build the view-model.
    surfaces: list[SurfaceStatus] = []
    for s in surfaces_raw:
        if not isinstance(s, dict):
            continue
        surfaces.append(
            SurfaceStatus(
                surface=str(s.get("surface") or ""),
                verified=bool(s.get("verified")),
                react_bound=bool(s.get("react_bound")),
                splash_status=str(s.get("splash_status") or ""),
                binding_status=str(s.get("binding_status") or ""),
                claim=str(s.get("claim") or ""),
                evidence_paths=tuple(str(p) for p in (s.get("evidence_paths") or [])),
            )
        )

    cbs = blob.get("claim_boundary_status") or {}

    return ProofOperatorCenterMilestoneDashboardStatus(
        decision="REACT_PROOF_OPERATOR_CENTER_MILESTONE_DASHBOARD_BINDING_PASSED",
        target_surface=str(blob.get("target_surface") or "Proof / Operator Center"),
        target_workflow=str(blob.get("target_workflow") or "milestone evidence dashboard"),
        dashboard_title=str(blob.get("record_id") or chosen.stem),
        source_mutation_authorized=False,
        approval_authority_granted=False,
        proof_execution_authority_granted=False,
        training_eligible=False,
        training_rows_written=False,
        release_ready=False,
        broad_claims_granted=False,
        artifact_import_authorized=False,
        benchmark_execution_authorized=False,
        programbench_execution_authorized=False,
        release_deploy_workflow_created=False,
        surfaces=tuple(surfaces),
        cathedral_index_status=str(rgs.get("cathedral_index") or ""),
        columbia_house_tracker_status=str(rgs.get("columbia_house_tracker") or ""),
        public_claims_ledger_status=str(rgs.get("public_claims_ledger") or ""),
        release_repo_scrub_status=str(rgs.get("release_repo_scrub") or ""),
        fresh_install_demo_workflow_status=str(rgs.get("fresh_install_demo_workflow") or ""),
        windows_first_support_matrix_status=str(rgs.get("windows_first_support_matrix") or ""),
        release_ready_label="release_ready: false (remains false)",
        scale_to_100_claim_truth_status=str(s100.get("claim_truth_status") or ""),
        scale_to_100_normalized_as_current_ct_lock=False,
        scale_to_100_scaling_plan_exists=bool(s100.get("scaling_plan_exists")),
        scale_to_100_corpus_training_reconciliation_lock=str(
            s100.get("corpus_training_reconciliation_lock") or ""
        ),
        scale_to_100_platform_language_appclass_expansion_queue=str(
            s100.get("platform_language_appclass_expansion_queue") or ""
        ),
        scale_to_100_windows_first_matrix_lock=str(s100.get("windows_first_matrix_lock") or ""),
        scale_to_100_legacy_enterprise=str(s100.get("legacy_enterprise") or ""),
        scale_to_100_audit_path=str(s100.get("scale_to_100_audit_path") or ""),
        evidence_index_count=int(eh.get("evidence_index_count") or 0),
        evidence_index_entry_count_field=int(eh.get("evidence_index_entry_count_field") or 0),
        evidence_index_valid=True,
        append_only_ledger_status=str(eh.get("append_only_ledger_status") or ""),
        append_only_ledger_chain_valid=True,
        append_only_ledger_entry_count=int(eh.get("append_only_ledger_entry_count") or 0),
        count_drift_status=str(eh.get("count_drift_status") or ""),
        count_drift_expected=int(eh.get("count_drift_expected") or 0),
        count_drift_actual=int(eh.get("count_drift_actual") or 0),
        json_parse_status=str(eh.get("json_parse_status") or ""),
        claim_boundary=tuple(str(b) for b in boundary_list),
        blocked_path_summary=_blocked_path_summary(blob),
        forbidden_claims=tuple(str(c) for c in (cbs.get("forbidden_claims") or [])),
        implemented_narrow_rooms=tuple(str(c) for c in (cbs.get("implemented_narrow_rooms") or [])),
        implemented_with_caveats=tuple(str(c) for c in (cbs.get("implemented_with_caveats") or [])),
        roadmap_items=tuple(str(c) for c in (cbs.get("roadmap_items") or [])),
        source_evidence_paths=tuple(str(p) for p in (blob.get("source_evidence_paths") or [])),
        source_audit_paths=tuple(str(p) for p in (blob.get("source_audit_paths") or [])),
        dashboard_report_path=str(blob.get("dashboard_report_path") or ""),
        machine_readable_dashboard_path=str(blob.get("machine_readable_dashboard_path") or ""),
        evidence_ref=str(chosen.as_posix()),
        current_next_rung=str(blob.get("current_next_rung") or ""),
        notes=(
            "evidence read from Codex Proof / Operator Center milestone dashboard bundle",
            "dashboard DISPLAYS authority; it does not grant authority",
            "Scale-to-100 remains roadmap draft, not current C&T lock",
            "Columbia House Tracker remains pending, not built",
            "Full Cathedral roadmap is audit input only, not validated by this binding",
            "source mutation, approval, proof-execution, training, release all remain False",
        ),
    )


__all__ = [
    "load",
    "REQUIRED_BOUNDARY_STATEMENTS",
    "REQUIRED_SURFACES",
    "REACT_PROOF_OPERATOR_CENTER_MILESTONE_DASHBOARD_BINDING_STATUS_TOKENS",
    "ProofOperatorCenterMilestoneDashboardStatus",
    "SurfaceStatus",
]
