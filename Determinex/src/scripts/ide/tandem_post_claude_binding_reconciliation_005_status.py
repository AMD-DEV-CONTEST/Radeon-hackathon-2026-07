"""Tandem post-Claude-binding reconciliation 005 status loader.

DETERMINEX_REACT_TANDEM_POST_CLAUDE_BINDING_RECONCILIATION_005_BINDING_LOCK_001.

load() reads the Codex reconciliation 005 evidence and returns a
render-safe view-model the React reconciliation panel can display.

The panel DISPLAYS the reconciliation result; it does NOT promote any
capability. Reconciliation absorbs display evidence; it does not grant
authority, training eligibility, source mutation, or any release claim.

Hard rules enforced by load():

  * status != TANDEM_POST_CLAUDE_BINDING_RECONCILIATION_005_PASSED ->
    BLOCKED_MALFORMED
  * authority bag flag true -> BLOCKED_AUTHORITY_CONFUSION
  * broad_claims_granted true -> BLOCKED_BROAD_CLAIM
  * absorbed_checkpoint_before_this_lock missing or count_drift_status
    != EVIDENCE_COUNT_DRIFT_GUARD_PASSED -> BLOCKED_MALFORMED
  * absorbed checkpoint counts != 354 (Claude-Batch-005/006 absorbed
    state) -> BLOCKED_CHECKPOINT_MISMATCH
  * absorbed_checkpoint.ledger_chain_valid != True OR
    mutation_detected != False -> BLOCKED_MALFORMED
  * absorbed_checkpoint.evidence_index_validation_errors not empty
    -> BLOCKED_MALFORMED
  * final_expected_evidence_count_after_this_lock < 355 -> BLOCKED_MALFORMED
  * absorbed_claude_locks does not contain all 5 expected Claude
    bindings -> BLOCKED_MALFORMED
  * forbidden broad-claim phrase as current claim -> BLOCKED_BROAD_CLAIM
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

_HERE = Path(__file__).resolve()
_SCRIPTS = _HERE.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from .universal_100_matrix_probe_batch_status import (  # noqa: E402
    _walk_strings_for_forbidden,
)

_REPO_ROOT = _HERE.parent.parent.parent

_DEFAULT_EVIDENCE_DIR = (
    _REPO_ROOT / "assurance" / "evidence" / "tandem_post_claude_binding_reconciliation_005"
)

EXPECTED_STATUS = "TANDEM_POST_CLAUDE_BINDING_RECONCILIATION_005_PASSED"
EXPECTED_ABSORBED_CHECKPOINT = 354
EXPECTED_FINAL_SPINE_MIN = 355
EXPECTED_ABSORBED_LOCKS = frozenset(
    {
        "DETERMINEX_REACT_UNIVERSAL_100_SECTOR_STATE_LADDER_BINDING_LOCK_001",
        "DETERMINEX_REACT_UNIVERSAL_100_SECTOR_GULP_BATCH_005_BINDING_LOCK_001",
        "DETERMINEX_REACT_UNIVERSAL_100_SUPPORT_MAP_DELTA_BATCH_005_VISUAL_BINDING_LOCK_001",
        "DETERMINEX_REACT_UNIVERSAL_100_SECTOR_GULP_BATCH_006_BINDING_LOCK_001",
        "DETERMINEX_REACT_UNIVERSAL_100_SUPPORT_MAP_DELTA_BATCH_006_VISUAL_BINDING_LOCK_001",
    }
)

REQUIRED_PANEL_CAPTIONS = (
    "This panel displays evidence; it does not grant authority.",
    "Reconciliation absorbs display evidence; it does not promote capability.",
    "Fixture-local proof is not production readiness.",
    "Smoke-supported is not release-supported.",
    "Fully supported with caveats is not release-supported.",
    "No source mutation without authority.",
    "Universal 100 means universal intake/routing, not magic execution.",
    "Blocked cells are visible by exact missing rung.",
)


REACT_TANDEM_POST_CLAUDE_BINDING_RECONCILIATION_005_BINDING_STATUS_TOKENS = (
    "REACT_TANDEM_POST_CLAUDE_BINDING_RECONCILIATION_005_BINDING_PASSED",
    "REACT_TANDEM_POST_CLAUDE_BINDING_RECONCILIATION_005_BINDING_AWAITING_EVIDENCE",
    "REACT_TANDEM_POST_CLAUDE_BINDING_RECONCILIATION_005_BINDING_BLOCKED_MALFORMED",
    "REACT_TANDEM_POST_CLAUDE_BINDING_RECONCILIATION_005_BINDING_BLOCKED_AUTHORITY_CONFUSION",
    "REACT_TANDEM_POST_CLAUDE_BINDING_RECONCILIATION_005_BINDING_BLOCKED_BROAD_CLAIM",
    "REACT_TANDEM_POST_CLAUDE_BINDING_RECONCILIATION_005_BINDING_BLOCKED_CHECKPOINT_MISMATCH",
)


@dataclass(frozen=True)
class Reconciliation005Status:
    decision: str
    target_surface: str
    target_workflow: str
    absorbed_claude_locks: tuple[str, ...]
    absorbed_checkpoint_evidence_index_count: int
    absorbed_checkpoint_ledger_entry_count: int
    absorbed_checkpoint_count_drift_status: str
    absorbed_checkpoint_count_drift_actual: int
    absorbed_checkpoint_count_drift_expected: int
    absorbed_checkpoint_ledger_chain_valid: bool
    absorbed_checkpoint_mutation_detected: bool
    absorbed_checkpoint_evidence_index_validation_errors: tuple[str, ...]
    final_expected_evidence_count_after_this_lock: int
    subprocess_reclassification_required: bool
    subprocess_unknown_requires_review_after: int
    claim_boundary: tuple[str, ...]
    forbidden_claims: tuple[str, ...]
    source_mutation_authorized: bool
    real_user_source_mutation_authorized: bool
    approval_authority_granted: bool
    proof_execution_authority_granted: bool
    training_eligible: bool
    training_rows_written: bool
    release_ready: bool
    broad_claims_granted: bool
    artifact_import_authorized: bool
    benchmark_execution_authorized: bool
    programbench_execution_authorized: bool
    release_deploy_workflow_created: bool
    evidence_ref: str
    captions: tuple[str, ...]
    current_next_rung: str
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        for k in (
            "absorbed_claude_locks",
            "absorbed_checkpoint_evidence_index_validation_errors",
            "claim_boundary",
            "forbidden_claims",
            "captions",
            "notes",
        ):
            d[k] = list(getattr(self, k))
        return d

    @property
    def is_passed(self) -> bool:
        return self.decision.endswith("_BINDING_PASSED")

    @property
    def is_awaiting(self) -> bool:
        return self.decision.endswith("_BINDING_AWAITING_EVIDENCE")

    @property
    def is_blocked(self) -> bool:
        return "_BINDING_BLOCKED_" in self.decision


def _locate_latest_evidence(evidence_dir: Path) -> Path | None:
    if not evidence_dir.is_dir():
        return None
    candidates = sorted(evidence_dir.glob("run_*.json"))
    return candidates[-1] if candidates else None


def _shell(*, decision: str, note: str) -> Reconciliation005Status:
    return Reconciliation005Status(
        decision=decision,
        target_surface="Tandem Post-Claude-Binding Reconciliation 005",
        target_workflow="(awaiting evidence)" if "AWAITING" in decision else "(blocked)",
        absorbed_claude_locks=tuple(),
        absorbed_checkpoint_evidence_index_count=0,
        absorbed_checkpoint_ledger_entry_count=0,
        absorbed_checkpoint_count_drift_status="",
        absorbed_checkpoint_count_drift_actual=0,
        absorbed_checkpoint_count_drift_expected=0,
        absorbed_checkpoint_ledger_chain_valid=False,
        absorbed_checkpoint_mutation_detected=False,
        absorbed_checkpoint_evidence_index_validation_errors=tuple(),
        final_expected_evidence_count_after_this_lock=0,
        subprocess_reclassification_required=False,
        subprocess_unknown_requires_review_after=0,
        claim_boundary=tuple(),
        forbidden_claims=tuple(),
        source_mutation_authorized=False,
        real_user_source_mutation_authorized=False,
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
        evidence_ref="",
        captions=REQUIRED_PANEL_CAPTIONS,
        current_next_rung="",
        notes=(note,),
    )


def _awaiting(note: str) -> Reconciliation005Status:
    return _shell(
        decision="REACT_TANDEM_POST_CLAUDE_BINDING_RECONCILIATION_005_BINDING_AWAITING_EVIDENCE",
        note=note,
    )


def _block(decision: str, note: str) -> Reconciliation005Status:
    return _shell(decision=decision, note=note)


def load(evidence_dir: Path | str | None = None) -> Reconciliation005Status:
    ed = Path(evidence_dir) if evidence_dir else _DEFAULT_EVIDENCE_DIR
    chosen = _locate_latest_evidence(ed)
    if chosen is None:
        return _awaiting(f"no evidence file under {ed}")
    try:
        blob = json.loads(chosen.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return _awaiting(f"could not read evidence: {exc}")

    if blob.get("status") != EXPECTED_STATUS:
        return _block(
            "REACT_TANDEM_POST_CLAUDE_BINDING_RECONCILIATION_005_BINDING_BLOCKED_MALFORMED",
            f"evidence status={blob.get('status')!r} (expected {EXPECTED_STATUS})",
        )

    auth = blob.get("authority") or {}

    def _auth(flag: str) -> bool:
        return bool(blob.get(flag) is True or auth.get(flag) is True)

    for flag in (
        "source_mutation_authorized",
        "real_user_source_mutation_authorized",
        "training_eligible",
        "training_rows_written",
        "approval_authority_granted",
        "release_ready",
        "proof_execution_authority_granted",
        "release_deploy_workflow_created",
        "artifact_import_authorized",
        "benchmark_execution_authorized",
        "programbench_execution_authorized",
    ):
        if _auth(flag):
            return _block(
                "REACT_TANDEM_POST_CLAUDE_BINDING_RECONCILIATION_005_BINDING_BLOCKED_AUTHORITY_CONFUSION",
                f"authority flag {flag} is true",
            )
    if _auth("broad_claims_granted"):
        return _block(
            "REACT_TANDEM_POST_CLAUDE_BINDING_RECONCILIATION_005_BINDING_BLOCKED_BROAD_CLAIM",
            "broad_claims_granted is true",
        )

    checkpoint = blob.get("absorbed_checkpoint_before_this_lock") or {}
    if not checkpoint:
        return _block(
            "REACT_TANDEM_POST_CLAUDE_BINDING_RECONCILIATION_005_BINDING_BLOCKED_MALFORMED",
            "absorbed_checkpoint_before_this_lock missing",
        )

    if checkpoint.get("count_drift_status") != "EVIDENCE_COUNT_DRIFT_GUARD_PASSED":
        return _block(
            "REACT_TANDEM_POST_CLAUDE_BINDING_RECONCILIATION_005_BINDING_BLOCKED_MALFORMED",
            f"absorbed checkpoint count_drift_status={checkpoint.get('count_drift_status')!r}",
        )

    cp_count = int(checkpoint.get("evidence_index_count", 0))
    cp_drift_actual = int(checkpoint.get("count_drift_actual", 0))
    cp_drift_expected = int(checkpoint.get("count_drift_expected", 0))
    cp_ledger = int(checkpoint.get("ledger_entry_count", 0))
    if not (
        cp_count
        == cp_drift_actual
        == cp_drift_expected
        == cp_ledger
        == EXPECTED_ABSORBED_CHECKPOINT
    ):
        return _block(
            "REACT_TANDEM_POST_CLAUDE_BINDING_RECONCILIATION_005_BINDING_BLOCKED_CHECKPOINT_MISMATCH",
            f"absorbed checkpoint counts {cp_count}/{cp_drift_actual}/{cp_drift_expected}/{cp_ledger} != {EXPECTED_ABSORBED_CHECKPOINT}",
        )

    if checkpoint.get("ledger_chain_valid") is not True:
        return _block(
            "REACT_TANDEM_POST_CLAUDE_BINDING_RECONCILIATION_005_BINDING_BLOCKED_MALFORMED",
            "absorbed checkpoint ledger_chain_valid is not True",
        )
    if checkpoint.get("mutation_detected") is not False:
        return _block(
            "REACT_TANDEM_POST_CLAUDE_BINDING_RECONCILIATION_005_BINDING_BLOCKED_MALFORMED",
            "absorbed checkpoint mutation_detected is not False",
        )

    cp_errs = checkpoint.get("evidence_index_validation_errors") or []
    if cp_errs:
        return _block(
            "REACT_TANDEM_POST_CLAUDE_BINDING_RECONCILIATION_005_BINDING_BLOCKED_MALFORMED",
            f"absorbed checkpoint evidence_index_validation_errors not empty: {cp_errs}",
        )

    final_expected = int(blob.get("final_expected_evidence_count_after_this_lock") or 0)
    if final_expected < EXPECTED_FINAL_SPINE_MIN:
        return _block(
            "REACT_TANDEM_POST_CLAUDE_BINDING_RECONCILIATION_005_BINDING_BLOCKED_MALFORMED",
            f"final_expected_evidence_count_after_this_lock={final_expected} < {EXPECTED_FINAL_SPINE_MIN}",
        )

    absorbed_locks = tuple(str(x) for x in (blob.get("absorbed_claude_locks") or []))
    if not EXPECTED_ABSORBED_LOCKS.issubset(absorbed_locks):
        missing = EXPECTED_ABSORBED_LOCKS - set(absorbed_locks)
        return _block(
            "REACT_TANDEM_POST_CLAUDE_BINDING_RECONCILIATION_005_BINDING_BLOCKED_MALFORMED",
            f"absorbed_claude_locks missing expected entries: {sorted(missing)}",
        )

    hits: set[str] = set()
    _walk_strings_for_forbidden(blob, hits)
    if hits:
        return _block(
            "REACT_TANDEM_POST_CLAUDE_BINDING_RECONCILIATION_005_BINDING_BLOCKED_BROAD_CLAIM",
            f"forbidden broad-claim phrases as current claim: {sorted(hits)}",
        )

    return Reconciliation005Status(
        decision="REACT_TANDEM_POST_CLAUDE_BINDING_RECONCILIATION_005_BINDING_PASSED",
        target_surface="Tandem Post-Claude-Binding Reconciliation 005",
        target_workflow="reconciliation 005 absorption record",
        absorbed_claude_locks=absorbed_locks,
        absorbed_checkpoint_evidence_index_count=cp_count,
        absorbed_checkpoint_ledger_entry_count=cp_ledger,
        absorbed_checkpoint_count_drift_status=str(checkpoint.get("count_drift_status")),
        absorbed_checkpoint_count_drift_actual=cp_drift_actual,
        absorbed_checkpoint_count_drift_expected=cp_drift_expected,
        absorbed_checkpoint_ledger_chain_valid=True,
        absorbed_checkpoint_mutation_detected=False,
        absorbed_checkpoint_evidence_index_validation_errors=tuple(str(x) for x in cp_errs),
        final_expected_evidence_count_after_this_lock=final_expected,
        subprocess_reclassification_required=bool(blob.get("subprocess_reclassification_required")),
        subprocess_unknown_requires_review_after=int(
            blob.get("subprocess_unknown_requires_review_after") or 0
        ),
        claim_boundary=tuple(str(x) for x in (blob.get("claim_boundary") or [])),
        forbidden_claims=tuple(str(x) for x in (blob.get("forbidden_claims") or [])),
        source_mutation_authorized=False,
        real_user_source_mutation_authorized=False,
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
        evidence_ref=_relative_to_repo(chosen),
        captions=REQUIRED_PANEL_CAPTIONS,
        current_next_rung=str(blob.get("next_recommended_rung") or ""),
        notes=(),
    )


def _relative_to_repo(path: Path) -> str:
    try:
        return path.resolve().relative_to(_REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


__all__ = [
    "load",
    "REACT_TANDEM_POST_CLAUDE_BINDING_RECONCILIATION_005_BINDING_STATUS_TOKENS",
    "REQUIRED_PANEL_CAPTIONS",
    "Reconciliation005Status",
]
