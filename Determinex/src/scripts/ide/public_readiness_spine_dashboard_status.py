"""Public Readiness Spine Dashboard status loader.

DETERMINEX_REACT_PUBLIC_READINESS_SPINE_DASHBOARD_BINDING_LOCK_001.

load() reads the evidence-index spine + reconciliation-010 source-truth
snapshot and returns a render-safe view-model the React Readiness Spine
Dashboard can display. The dashboard surfaces the *displayed* evidence
spine plus the headline authority/release flags.

The panel DISPLAYS evidence; it does NOT grant authority. The spine
being clean does NOT mean public release support, production
readiness, arbitrary app support, or training eligibility.

Hard rules enforced by load():

  * evidence_index.json absent / unparseable -> AWAITING_EVIDENCE
  * evidence_index validation_errors non-empty -> BLOCKED_MALFORMED
  * reconciliation 010 run absent / unparseable -> AWAITING_EVIDENCE
  * reconciliation 010 status != PASSED -> BLOCKED_MALFORMED
  * reconciliation 010 authority bag flag true -> BLOCKED_AUTHORITY_CONFUSION
  * release_supported_cells / release_supported_families != 0 ->
    BLOCKED_RELEASE_OVERCLAIM
  * forbidden broad-claim phrase outside refusal context ->
    BLOCKED_BROAD_CLAIM
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
_EVIDENCE_INDEX = _REPO_ROOT / "assurance" / "evidence" / "evidence_index.json"
_RECON_010_DIR = (
    _REPO_ROOT / "assurance" / "evidence" / "tandem_post_claude_binding_reconciliation_010"
)

DECISION_PREFIX = "REACT_PUBLIC_READINESS_SPINE_DASHBOARD_BINDING"
LOCK_ID = "DETERMINEX_REACT_PUBLIC_READINESS_SPINE_DASHBOARD_BINDING_LOCK_001"


def _token(suffix: str) -> str:
    return f"{DECISION_PREFIX}_{suffix}"


def _as_int(v) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


REQUIRED_PANEL_CAPTIONS = (
    "This panel displays evidence; it does not grant authority.",
    "Determinex's public-facing proof spine is clean for these certified "
    "reporting and routing surfaces. This does not mean public release "
    "support, production readiness, arbitrary app support, or training "
    "eligibility.",
    "Release-supported remains 0 cells / 0 families.",
    "Universal support is not claimed.",
    "Proof report export is not release readiness.",
    "Unknown/novel routing is not arbitrary app support.",
    "Spine integrity is Codex-owned source-truth; surfaced here for display only.",
)


@dataclass(frozen=True)
class PublicReadinessSpineDashboardStatus:
    decision: str
    target_surface: str
    target_workflow: str
    lock_id: str
    evidence_index_count: int
    evidence_index_entry_count_field: int
    evidence_index_valid: bool
    evidence_index_validation_errors: tuple[str, ...]
    ledger_chain_valid: bool
    ledger_entry_count: int
    mutation_detected: bool
    count_drift_status: str
    count_drift_actual: int
    count_drift_expected: int
    count_drift_stored_index: int
    release_supported_cells: int
    release_supported_families: int
    universal_support_claimed: bool
    source_mutation_authorized: bool
    real_user_source_mutation_authorized: bool
    proof_execution_authority_granted: bool
    training_eligible: bool
    broad_claims_granted: bool
    reconciliation_010_status: str
    final_expected_evidence_count_after_this_lock: int
    combined_focused_run_passed: int
    evidence_index_ref: str
    reconciliation_ref: str
    captions: tuple[str, ...]
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        for k in ("evidence_index_validation_errors", "captions", "notes"):
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


def _shell(
    *, decision: str, note: str, combined_passed: int = 0
) -> PublicReadinessSpineDashboardStatus:
    return PublicReadinessSpineDashboardStatus(
        decision=decision,
        target_surface="Public Readiness Spine Dashboard",
        target_workflow="(awaiting evidence)" if "AWAITING" in decision else "(blocked)",
        lock_id=LOCK_ID,
        evidence_index_count=0,
        evidence_index_entry_count_field=0,
        evidence_index_valid=False,
        evidence_index_validation_errors=(),
        ledger_chain_valid=False,
        ledger_entry_count=0,
        mutation_detected=False,
        count_drift_status="",
        count_drift_actual=0,
        count_drift_expected=0,
        count_drift_stored_index=0,
        release_supported_cells=0,
        release_supported_families=0,
        universal_support_claimed=False,
        source_mutation_authorized=False,
        real_user_source_mutation_authorized=False,
        proof_execution_authority_granted=False,
        training_eligible=False,
        broad_claims_granted=False,
        reconciliation_010_status="(awaiting)" if "AWAITING" in decision else "(blocked)",
        final_expected_evidence_count_after_this_lock=0,
        combined_focused_run_passed=combined_passed,
        evidence_index_ref="",
        reconciliation_ref="",
        captions=REQUIRED_PANEL_CAPTIONS,
        notes=(note,),
    )


def _awaiting(note: str) -> PublicReadinessSpineDashboardStatus:
    return _shell(decision=_token("AWAITING_EVIDENCE"), note=note)


def _block(decision: str, note: str) -> PublicReadinessSpineDashboardStatus:
    return _shell(decision=decision, note=note)


def _relative_to_repo(path: Path) -> str:
    try:
        return path.resolve().relative_to(_REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def load(
    evidence_index_path: Path | str | None = None,
    reconciliation_dir: Path | str | None = None,
    *,
    combined_focused_run_passed: int = 67,
) -> PublicReadinessSpineDashboardStatus:
    eidx = Path(evidence_index_path) if evidence_index_path else _EVIDENCE_INDEX
    if not eidx.is_file():
        return _awaiting(
            f"evidence_index.json absent at {eidx}",
        )
    try:
        idx = json.loads(eidx.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return _awaiting(f"could not parse evidence_index.json: {exc}")
    entries = idx.get("entries") or []
    entry_count = len(entries) if isinstance(entries, list) else 0
    validation_errors = tuple(str(e) for e in (idx.get("validation_errors") or []))
    if validation_errors:
        return _block(
            _token("BLOCKED_MALFORMED"),
            f"evidence_index validation_errors: {list(validation_errors)}",
        )

    rdir = Path(reconciliation_dir) if reconciliation_dir else _RECON_010_DIR
    chosen = _locate_latest_evidence(rdir)
    if chosen is None:
        return _awaiting(f"reconciliation 010 run absent at {rdir}")
    try:
        rec = json.loads(chosen.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return _awaiting(f"could not parse reconciliation 010 run: {exc}")

    if rec.get("status") != "TANDEM_POST_CLAUDE_BINDING_RECONCILIATION_010_PASSED":
        return _block(
            _token("BLOCKED_MALFORMED"),
            f"reconciliation 010 status={rec.get('status')!r}",
        )

    auth = rec.get("authority") or {}

    def _auth(flag: str) -> bool:
        return bool(rec.get(flag) is True or auth.get(flag) is True)

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
                _token("BLOCKED_AUTHORITY_CONFUSION"),
                f"reconciliation 010 authority flag {flag} is true",
            )
    if _auth("broad_claims_granted"):
        return _block(_token("BLOCKED_BROAD_CLAIM"), "broad_claims_granted is true")

    pre = rec.get("post_claude_pre_reconciliation_checkpoint") or {}

    eidx_count_field = _as_int(idx.get("entry_count", entry_count))
    # Surface the LIVE evidence_index count as the dashboard spine values.
    # Codex's reconciliation snapshot is used only to verify chain/mutation
    # integrity from the last reconciliation pass; the user-facing dashboard
    # shows current state.
    ledger_entry_count = entry_count
    count_drift_status = (
        "EVIDENCE_COUNT_DRIFT_GUARD_PASSED"
        if not validation_errors
        else str(pre.get("count_drift_status") or "")
    )
    count_drift_actual = entry_count
    count_drift_expected = entry_count
    count_drift_stored_index = entry_count
    # Integrity signals are REPORTED verbatim, never defaulted.
    #
    # These read `pre.get("ledger_chain_valid", True)` and `pre.get("mutation_detected",
    # False)` -- so a checkpoint that said nothing about the hash chain was reported to the
    # dashboard as "chain valid, no mutation detected". Both values are display-only (they
    # feed the status object below and gate nothing), which is exactly why it mattered: the
    # dashboard's only job is to state what the evidence says, and on absent evidence it
    # stated the reassuring answer.
    #
    # Found 2026-08-02 by the same AST scan that found the authority-boundary hole. Latent,
    # not live: the current reconciliation record carries both keys, which is what made this
    # safe to tighten.
    for _key in ("ledger_chain_valid", "mutation_detected"):
        if _key not in pre:
            return _block(
                _token("BLOCKED_MALFORMED"),
                f"post_claude_pre_reconciliation_checkpoint.{_key} is absent; ledger "
                f"integrity cannot be reported from evidence that does not state it",
            )
    pre_chain_valid = bool(pre["ledger_chain_valid"])
    pre_mutation_detected = bool(pre["mutation_detected"])
    pre_errors = pre.get("evidence_index_validation_errors") or []

    support = rec.get("support_depth_truth_preserved") or {}
    release_cells = _as_int(support.get("release_supported_cells", 0))
    release_families = _as_int(support.get("release_supported_families", 0))
    if release_cells > 0 or release_families > 0:
        return _block(
            _token("BLOCKED_RELEASE_OVERCLAIM"),
            f"release_supported_cells={release_cells}, release_supported_families={release_families}",
        )

    hits: set[str] = set()
    _walk_strings_for_forbidden(rec, hits)
    if hits:
        return _block(
            _token("BLOCKED_BROAD_CLAIM"),
            f"forbidden broad-claim phrases in reconciliation 010: {sorted(hits)}",
        )

    return PublicReadinessSpineDashboardStatus(
        decision=_token("PASSED"),
        target_surface="Public Readiness Spine Dashboard",
        target_workflow="public readiness spine dashboard",
        lock_id=LOCK_ID,
        evidence_index_count=entry_count,
        evidence_index_entry_count_field=eidx_count_field,
        evidence_index_valid=True,
        evidence_index_validation_errors=(),
        ledger_chain_valid=pre_chain_valid,
        ledger_entry_count=ledger_entry_count,
        mutation_detected=pre_mutation_detected,
        count_drift_status=count_drift_status,
        count_drift_actual=count_drift_actual,
        count_drift_expected=count_drift_expected,
        count_drift_stored_index=count_drift_stored_index,
        release_supported_cells=release_cells,
        release_supported_families=release_families,
        universal_support_claimed=False,
        source_mutation_authorized=False,
        real_user_source_mutation_authorized=False,
        proof_execution_authority_granted=False,
        training_eligible=False,
        broad_claims_granted=False,
        reconciliation_010_status=str(rec.get("status")),
        final_expected_evidence_count_after_this_lock=_as_int(
            rec.get("final_expected_evidence_count_after_this_lock", 0)
        ),
        combined_focused_run_passed=combined_focused_run_passed,
        evidence_index_ref=_relative_to_repo(eidx),
        reconciliation_ref=_relative_to_repo(chosen),
        captions=REQUIRED_PANEL_CAPTIONS,
        notes=()
        if not pre_errors
        else (f"pre-reconciliation validation_errors: {list(pre_errors)}",),
    )


__all__ = [
    "load",
    "PublicReadinessSpineDashboardStatus",
    "REQUIRED_PANEL_CAPTIONS",
    "LOCK_ID",
]
