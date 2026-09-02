"""Tandem post-Claude-binding reconciliation 008 status loader.

DETERMINEX_REACT_TANDEM_POST_CLAUDE_BINDING_RECONCILIATION_008_BINDING_LOCK_001.

Codex reconciliation 008 absorbs the Claude commit 3227e8394 that bound
the campaign + reconciliation 007 + Batch 011/012/013 wave (8 locks).
Codex's prior source-truth checkpoint was 387; the Claude display
checkpoint after the wave was 395; the reconciliation lock itself is
committed at 396.

The panel DISPLAYS the reconciliation result; it does NOT promote any
capability. Reconciliation absorbs display evidence; it does not grant
authority.

Hard rules enforced by load():

  * status != TANDEM_POST_CLAUDE_BINDING_RECONCILIATION_008_PASSED ->
    BLOCKED_MALFORMED
  * authority bag flag true -> BLOCKED_AUTHORITY_CONFUSION
  * broad_claims_granted true -> BLOCKED_BROAD_CLAIM
  * claude_display_checkpoint_before_this_lock missing or counts != 395
    -> BLOCKED_CHECKPOINT_MISMATCH
  * claude_display_checkpoint ledger_chain_valid != True OR
    mutation_detected != False -> BLOCKED_MALFORMED
  * claude_display_checkpoint evidence_index_validation_errors not empty
    -> BLOCKED_MALFORMED
  * prior_codex_source_truth_checkpoint missing or != 387 ->
    BLOCKED_MALFORMED
  * final_expected_evidence_count_after_this_lock < 396 ->
    BLOCKED_MALFORMED
  * absorbed_claude_locks missing all 8 expected Claude bindings ->
    BLOCKED_MALFORMED
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
    _REPO_ROOT / "assurance" / "evidence" / "tandem_post_claude_binding_reconciliation_008"
)

EXPECTED_STATUS = "TANDEM_POST_CLAUDE_BINDING_RECONCILIATION_008_PASSED"
EXPECTED_CLAUDE_DISPLAY_CHECKPOINT = 395
EXPECTED_PRIOR_CODEX_CHECKPOINT = 387
EXPECTED_FINAL_SPINE_MIN = 396
EXPECTED_ABSORBED_LOCKS = frozenset(
    {
        "DETERMINEX_REACT_UNIVERSAL_100_TOP_LEVEL_SECTOR_COMPLETION_CAMPAIGN_BINDING_LOCK_001",
        "DETERMINEX_REACT_TANDEM_POST_CLAUDE_BINDING_RECONCILIATION_007_BINDING_LOCK_001",
        "DETERMINEX_REACT_UNIVERSAL_100_SECTOR_GULP_BATCH_011_BINDING_LOCK_001",
        "DETERMINEX_REACT_UNIVERSAL_100_SUPPORT_MAP_DELTA_BATCH_011_VISUAL_BINDING_LOCK_001",
        "DETERMINEX_REACT_UNIVERSAL_100_SECTOR_GULP_BATCH_012_BINDING_LOCK_001",
        "DETERMINEX_REACT_UNIVERSAL_100_SUPPORT_MAP_DELTA_BATCH_012_VISUAL_BINDING_LOCK_001",
        "DETERMINEX_REACT_UNIVERSAL_100_SECTOR_GULP_BATCH_013_BINDING_LOCK_001",
        "DETERMINEX_REACT_UNIVERSAL_100_SUPPORT_MAP_DELTA_BATCH_013_VISUAL_BINDING_LOCK_001",
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


REACT_TANDEM_POST_CLAUDE_BINDING_RECONCILIATION_008_BINDING_STATUS_TOKENS = (
    "REACT_TANDEM_POST_CLAUDE_BINDING_RECONCILIATION_008_BINDING_PASSED",
    "REACT_TANDEM_POST_CLAUDE_BINDING_RECONCILIATION_008_BINDING_AWAITING_EVIDENCE",
    "REACT_TANDEM_POST_CLAUDE_BINDING_RECONCILIATION_008_BINDING_BLOCKED_MALFORMED",
    "REACT_TANDEM_POST_CLAUDE_BINDING_RECONCILIATION_008_BINDING_BLOCKED_AUTHORITY_CONFUSION",
    "REACT_TANDEM_POST_CLAUDE_BINDING_RECONCILIATION_008_BINDING_BLOCKED_BROAD_CLAIM",
    "REACT_TANDEM_POST_CLAUDE_BINDING_RECONCILIATION_008_BINDING_BLOCKED_CHECKPOINT_MISMATCH",
)


@dataclass(frozen=True)
class Reconciliation008Status:
    decision: str
    target_surface: str
    target_workflow: str
    absorbed_claude_commit: str
    absorbed_claude_locks: tuple[str, ...]
    claude_display_checkpoint_evidence_index_count: int
    claude_display_checkpoint_ledger_entry_count: int
    claude_display_checkpoint_count_drift_status: str
    claude_display_checkpoint_count_drift_actual: int
    claude_display_checkpoint_count_drift_expected: int
    claude_display_checkpoint_stored_index_entry_count: int
    claude_display_checkpoint_ledger_chain_valid: bool
    claude_display_checkpoint_mutation_detected: bool
    claude_display_checkpoint_evidence_index_validation_errors: tuple[str, ...]
    prior_codex_source_truth_evidence_index_count: int
    prior_codex_source_truth_ledger_entry_count: int
    final_expected_evidence_count_after_this_lock: int
    source_truth_locks_preserved: tuple[str, ...]
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
            "claude_display_checkpoint_evidence_index_validation_errors",
            "source_truth_locks_preserved",
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


def _shell(*, decision: str, note: str) -> Reconciliation008Status:
    return Reconciliation008Status(
        decision=decision,
        target_surface="Tandem Post-Claude-Binding Reconciliation 008",
        target_workflow="(awaiting evidence)" if "AWAITING" in decision else "(blocked)",
        absorbed_claude_commit="",
        absorbed_claude_locks=tuple(),
        claude_display_checkpoint_evidence_index_count=0,
        claude_display_checkpoint_ledger_entry_count=0,
        claude_display_checkpoint_count_drift_status="",
        claude_display_checkpoint_count_drift_actual=0,
        claude_display_checkpoint_count_drift_expected=0,
        claude_display_checkpoint_stored_index_entry_count=0,
        claude_display_checkpoint_ledger_chain_valid=False,
        claude_display_checkpoint_mutation_detected=False,
        claude_display_checkpoint_evidence_index_validation_errors=tuple(),
        prior_codex_source_truth_evidence_index_count=0,
        prior_codex_source_truth_ledger_entry_count=0,
        final_expected_evidence_count_after_this_lock=0,
        source_truth_locks_preserved=tuple(),
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


def _awaiting(note: str) -> Reconciliation008Status:
    return _shell(
        decision="REACT_TANDEM_POST_CLAUDE_BINDING_RECONCILIATION_008_BINDING_AWAITING_EVIDENCE",
        note=note,
    )


def _block(decision: str, note: str) -> Reconciliation008Status:
    return _shell(decision=decision, note=note)


def load(evidence_dir: Path | str | None = None) -> Reconciliation008Status:
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
            "REACT_TANDEM_POST_CLAUDE_BINDING_RECONCILIATION_008_BINDING_BLOCKED_MALFORMED",
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
                "REACT_TANDEM_POST_CLAUDE_BINDING_RECONCILIATION_008_BINDING_BLOCKED_AUTHORITY_CONFUSION",
                f"authority flag {flag} is true",
            )
    if _auth("broad_claims_granted"):
        return _block(
            "REACT_TANDEM_POST_CLAUDE_BINDING_RECONCILIATION_008_BINDING_BLOCKED_BROAD_CLAIM",
            "broad_claims_granted is true",
        )

    claude_cp = blob.get("claude_display_checkpoint_before_this_lock") or {}
    if not claude_cp:
        return _block(
            "REACT_TANDEM_POST_CLAUDE_BINDING_RECONCILIATION_008_BINDING_BLOCKED_MALFORMED",
            "claude_display_checkpoint_before_this_lock missing",
        )

    cp_count = int(claude_cp.get("evidence_index_count", 0))
    cp_drift_actual = int(claude_cp.get("count_drift_actual", 0))
    cp_drift_expected = int(claude_cp.get("count_drift_expected", 0))
    cp_ledger = int(claude_cp.get("ledger_entry_count", 0))
    if not (
        cp_count
        == cp_drift_actual
        == cp_drift_expected
        == cp_ledger
        == EXPECTED_CLAUDE_DISPLAY_CHECKPOINT
    ):
        return _block(
            "REACT_TANDEM_POST_CLAUDE_BINDING_RECONCILIATION_008_BINDING_BLOCKED_CHECKPOINT_MISMATCH",
            f"claude display checkpoint counts {cp_count}/{cp_drift_actual}/{cp_drift_expected}/{cp_ledger} != {EXPECTED_CLAUDE_DISPLAY_CHECKPOINT}",
        )

    if claude_cp.get("count_drift_status") != "EVIDENCE_COUNT_DRIFT_GUARD_PASSED":
        return _block(
            "REACT_TANDEM_POST_CLAUDE_BINDING_RECONCILIATION_008_BINDING_BLOCKED_MALFORMED",
            f"claude display checkpoint count_drift_status={claude_cp.get('count_drift_status')!r}",
        )

    if claude_cp.get("ledger_chain_valid") is not True:
        return _block(
            "REACT_TANDEM_POST_CLAUDE_BINDING_RECONCILIATION_008_BINDING_BLOCKED_MALFORMED",
            "claude display checkpoint ledger_chain_valid is not True",
        )
    if claude_cp.get("mutation_detected") is not False:
        return _block(
            "REACT_TANDEM_POST_CLAUDE_BINDING_RECONCILIATION_008_BINDING_BLOCKED_MALFORMED",
            "claude display checkpoint mutation_detected is not False",
        )

    cp_errs = claude_cp.get("evidence_index_validation_errors") or []
    if cp_errs:
        return _block(
            "REACT_TANDEM_POST_CLAUDE_BINDING_RECONCILIATION_008_BINDING_BLOCKED_MALFORMED",
            f"claude display checkpoint evidence_index_validation_errors not empty: {cp_errs}",
        )

    prior_cp = blob.get("prior_codex_source_truth_checkpoint") or {}
    prior_count = int(prior_cp.get("evidence_index_count", 0))
    if prior_count != EXPECTED_PRIOR_CODEX_CHECKPOINT:
        return _block(
            "REACT_TANDEM_POST_CLAUDE_BINDING_RECONCILIATION_008_BINDING_BLOCKED_MALFORMED",
            f"prior_codex_source_truth_checkpoint evidence_index_count={prior_count} != {EXPECTED_PRIOR_CODEX_CHECKPOINT}",
        )

    final_expected = int(blob.get("final_expected_evidence_count_after_this_lock") or 0)
    if final_expected < EXPECTED_FINAL_SPINE_MIN:
        return _block(
            "REACT_TANDEM_POST_CLAUDE_BINDING_RECONCILIATION_008_BINDING_BLOCKED_MALFORMED",
            f"final_expected_evidence_count_after_this_lock={final_expected} < {EXPECTED_FINAL_SPINE_MIN}",
        )

    absorbed_locks = tuple(str(x) for x in (blob.get("absorbed_claude_locks") or []))
    if not EXPECTED_ABSORBED_LOCKS.issubset(absorbed_locks):
        missing = EXPECTED_ABSORBED_LOCKS - set(absorbed_locks)
        return _block(
            "REACT_TANDEM_POST_CLAUDE_BINDING_RECONCILIATION_008_BINDING_BLOCKED_MALFORMED",
            f"absorbed_claude_locks missing expected entries: {sorted(missing)}",
        )

    hits: set[str] = set()
    _walk_strings_for_forbidden(blob, hits)
    if hits:
        return _block(
            "REACT_TANDEM_POST_CLAUDE_BINDING_RECONCILIATION_008_BINDING_BLOCKED_BROAD_CLAIM",
            f"forbidden broad-claim phrases as current claim: {sorted(hits)}",
        )

    return Reconciliation008Status(
        decision="REACT_TANDEM_POST_CLAUDE_BINDING_RECONCILIATION_008_BINDING_PASSED",
        target_surface="Tandem Post-Claude-Binding Reconciliation 008",
        target_workflow="reconciliation 008 absorption record",
        absorbed_claude_commit=str(blob.get("absorbed_claude_commit") or ""),
        absorbed_claude_locks=absorbed_locks,
        claude_display_checkpoint_evidence_index_count=cp_count,
        claude_display_checkpoint_ledger_entry_count=cp_ledger,
        claude_display_checkpoint_count_drift_status=str(claude_cp.get("count_drift_status")),
        claude_display_checkpoint_count_drift_actual=cp_drift_actual,
        claude_display_checkpoint_count_drift_expected=cp_drift_expected,
        claude_display_checkpoint_stored_index_entry_count=int(
            claude_cp.get("stored_index_entry_count", 0)
        ),
        claude_display_checkpoint_ledger_chain_valid=True,
        claude_display_checkpoint_mutation_detected=False,
        claude_display_checkpoint_evidence_index_validation_errors=tuple(str(x) for x in cp_errs),
        prior_codex_source_truth_evidence_index_count=prior_count,
        prior_codex_source_truth_ledger_entry_count=int(prior_cp.get("ledger_entry_count", 0)),
        final_expected_evidence_count_after_this_lock=final_expected,
        source_truth_locks_preserved=tuple(
            str(x) for x in (blob.get("source_truth_locks_preserved") or [])
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
    "REACT_TANDEM_POST_CLAUDE_BINDING_RECONCILIATION_008_BINDING_STATUS_TOKENS",
    "REQUIRED_PANEL_CAPTIONS",
    "Reconciliation008Status",
    "EXPECTED_STATUS",
    "EXPECTED_CLAUDE_DISPLAY_CHECKPOINT",
    "EXPECTED_PRIOR_CODEX_CHECKPOINT",
    "EXPECTED_FINAL_SPINE_MIN",
    "EXPECTED_ABSORBED_LOCKS",
]
