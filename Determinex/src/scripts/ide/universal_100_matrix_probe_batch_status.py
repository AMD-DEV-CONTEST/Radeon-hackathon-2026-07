"""Universal 100 Matrix Probe Batch 001 status loader.

DETERMINEX_REACT_UNIVERSAL_100_MATRIX_PROBE_EXECUTION_BATCH_BINDING_LOCK_001.

load() reads the Codex Universal 100 Matrix Probe Execution Batch 001
evidence and returns a render-safe view-model the React
Universal100MatrixProbeBatchStatus panel can display.

The panel DISPLAYS evidence; it does NOT grant authority. No field
implies source mutation, approval, proof-execution authority, training,
release readiness, or universal app/language/platform support.
Fixture-local executable proof is not production readiness.

Hard rules enforced by load():

  * status != UNIVERSAL_100_MATRIX_PROBE_EXECUTION_BATCH_PASSED ->
    BLOCKED_MALFORMED
  * authority bag (source_mutation_authorized, training_eligible,
    training_rows_written, approval_authority_granted, release_ready,
    proof_execution_authority_granted, release_deploy_workflow_created,
    artifact_import_authorized, benchmark_execution_authorized,
    programbench_execution_authorized) True at top level or under
    `authority` -> BLOCKED_AUTHORITY_CONFUSION
  * broad_claims_granted True -> BLOCKED_BROAD_CLAIM
  * summary.release_supported > 0 without an accompanying release-proof
    lock referenced in the evidence -> BLOCKED_RELEASE_OVERCLAIM
  * blocked_cells list missing (i.e., promoted cells displayed but
    blocked cells hidden) -> BLOCKED_BLOCKED_CELLS_HIDDEN
  * fixture-local caveat absent from claim_boundary AND captions ->
    BLOCKED_FIXTURE_CAVEAT_MISSING
  * any forbidden broad-claim phrase outside refusal-context fields
    (claim_boundary / forbidden_claims / blocked_path_demo /
    what_remains_forbidden / does_not_mean / fallbacks_enforced) ->
    BLOCKED_BROAD_CLAIM
  * summary.cells_probed missing -> BLOCKED_MALFORMED
  * promoted cell with IMPLEMENTED claim but support_state ranked
    below demo_proven -> BLOCKED_MALFORMED
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
_SCRIPTS = _HERE.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from .universal_100_matrix_probe_batch_status_record import (
    FORBIDDEN_BROAD_CLAIM_PHRASES,
    REQUIRED_FIXTURE_CAVEATS,
    ProbeCellRow,
    Universal100MatrixProbeBatchStatus,
)

_REPO_ROOT = _HERE.parent.parent.parent

_DEFAULT_EVIDENCE_DIR = (
    _REPO_ROOT / "assurance" / "evidence" / "universal_100_matrix_probe_execution_batch"
)


# Per-batch configuration. Each entry binds a Claude batch-binding lock to
# its Codex evidence directory + expected status + batch metadata.
class _BatchConfig:
    def __init__(
        self,
        *,
        batch_label: str,
        batch_lock_id: str,
        evidence_dir_name: str,
        expected_status: str,
    ) -> None:
        self.batch_label = batch_label
        self.batch_lock_id = batch_lock_id
        self.evidence_dir_name = evidence_dir_name
        self.expected_status = expected_status

    @property
    def evidence_dir(self) -> Path:
        return _REPO_ROOT / "assurance" / "evidence" / self.evidence_dir_name


BATCH_001 = _BatchConfig(
    batch_label="Batch 001",
    batch_lock_id="DETERMINEX_UNIVERSAL_100_MATRIX_PROBE_EXECUTION_BATCH_001",
    evidence_dir_name="universal_100_matrix_probe_execution_batch",
    expected_status="UNIVERSAL_100_MATRIX_PROBE_EXECUTION_BATCH_PASSED",
)
BATCH_002 = _BatchConfig(
    batch_label="Batch 002",
    batch_lock_id="DETERMINEX_UNIVERSAL_100_MATRIX_PROBE_EXECUTION_BATCH_002",
    evidence_dir_name="universal_100_matrix_probe_execution_batch_002",
    expected_status="UNIVERSAL_100_MATRIX_PROBE_EXECUTION_BATCH_002_PASSED",
)
BATCH_003 = _BatchConfig(
    batch_label="Batch 003",
    batch_lock_id="DETERMINEX_UNIVERSAL_100_MATRIX_PROBE_EXECUTION_BATCH_003",
    evidence_dir_name="universal_100_matrix_probe_execution_batch_003",
    expected_status="UNIVERSAL_100_MATRIX_PROBE_EXECUTION_BATCH_003_PASSED",
)
BATCH_004 = _BatchConfig(
    batch_label="Batch 004",
    batch_lock_id="DETERMINEX_UNIVERSAL_100_MATRIX_PROBE_EXECUTION_BATCH_004",
    evidence_dir_name="universal_100_matrix_probe_execution_batch_004",
    expected_status="UNIVERSAL_100_MATRIX_PROBE_EXECUTION_BATCH_004_PASSED",
)

# Required canonical captions surfaced by the Claude panel. These are
# the panel-side overlay, independent of what Codex provides.
REQUIRED_PANEL_CAPTIONS = (
    "This panel displays evidence; it does not grant authority.",
    "Fixture-local proof is not production readiness.",
    "No release-supported cells in this batch.",
    "Unsupported or blocked cells are routed by exact missing rung.",
    "No working-app claim without build/test/smoke evidence.",
    "No source mutation without authority.",
    "Universal 100 means universal intake/routing, not magic execution.",
)


SUPPORT_STATE_LADDER = (
    "unsupported",
    "roadmap",
    "scaffold_only",
    "scaffold_supported",
    "build_supported",
    "test_supported",
    "smoke_supported",
    "repair_supported",
    "maintain_supported",
    "teach_supported",
    "demo_proven",
    "user_ready",
    "user_ready_with_caveats",
    "packaging_supported",
    "fresh_install_verified",
    "release_gate_ready",
    "release_supported",
    "fully_supported_with_caveats",
)


_REFUSAL_CONTEXT_KEYS = {
    "forbidden_claims",
    "still_forbidden_claims",
    "blocked_path_demo",
    "blocked_path_summary",
    "blockers_by_category",
    "blocked_reasons",
    "claim_boundary",
    "does_not_mean",
    "what_remains_forbidden",
    "fallbacks_enforced",
    "captions",
    "required_panel_captions",
    "negative_claims",
    "refused_claims",
    "must_never_claim",
    "must_not_claim",
    "never_claim",
    "what_this_does_not_prove",
    "safety_or_authority_constraints",
    "release_boundary",
    "universal_100_level_1_not_claimed",
    "universal_100_level_n_not_claimed",
    "not_claimed",
    # Public-proof / claim-scanner refusal contexts (wave 12).
    "false_claim_scanner_model",
    "blocked_or_flagged_phrases",
    "forbidden_report_claims",
    "blocker_handling",
    "phrase",
    "safe_replacement_boundary",
    "what_the_user_may_not_claim",
    "forbidden_policy_blocked_handling",
    "do_not_claim_support",
    "exportability_boundary",
    "authority_boundary",
    "user_claims_forbidden",
    "user_claims_not_allowed",
    "claims_forbidden",
    "report_blocked_or_flagged_claims",
    "safety_or_policy_notes",
    "do_not_execute",
    "do_not_scaffold_dangerous_behavior",
}


def _locate_latest_evidence(evidence_dir: Path) -> Path | None:
    if not evidence_dir.is_dir():
        return None
    candidates = sorted(evidence_dir.glob("run_*.json"))
    return candidates[-1] if candidates else None


def _zero_cells() -> tuple[ProbeCellRow, ...]:
    return tuple()


def _awaiting(note: str, cfg: _BatchConfig = BATCH_001) -> Universal100MatrixProbeBatchStatus:
    return _shell(
        decision="REACT_UNIVERSAL_100_MATRIX_PROBE_EXECUTION_BATCH_BINDING_AWAITING_EVIDENCE",
        note=note,
        cfg=cfg,
    )


def _block(
    decision: str, note: str, cfg: _BatchConfig = BATCH_001
) -> Universal100MatrixProbeBatchStatus:
    return _shell(decision=decision, note=note, cfg=cfg)


def _shell(
    *, decision: str, note: str, cfg: _BatchConfig = BATCH_001
) -> Universal100MatrixProbeBatchStatus:
    return Universal100MatrixProbeBatchStatus(
        decision=decision,
        target_surface="Universal 100 Matrix Probe",
        target_workflow="(awaiting evidence)" if "AWAITING" in decision else "(blocked)",
        batch_label=cfg.batch_label,
        batch_lock_id=cfg.batch_lock_id,
        cells_probed=0,
        cells_promoted=0,
        blocked_or_forbidden=0,
        cells_partial_or_roadmap=0,
        smoke_supported_count=0,
        repair_supported_count=0,
        maintain_supported_count=0,
        release_supported_count=0,
        build_supported_count=0,
        test_supported_count=0,
        scaffold_only_count=0,
        roadmap_count=0,
        unsupported_count=0,
        missing_oracle_count=0,
        missing_smoke_count=0,
        missing_toolchain_count=0,
        missing_adapter_count=0,
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
        promoted_cells=_zero_cells(),
        blocked_cells=_zero_cells(),
        claim_boundary=(),
        forbidden_claims=(),
        blocked_path_summary=(),
        strongest_truthful_new_claim="(awaiting evidence)"
        if "AWAITING" in decision
        else "(blocked)",
        evidence_index_count=0,
        evidence_index_entry_count_field=0,
        evidence_index_valid=False,
        append_only_ledger_status="(awaiting)" if "AWAITING" in decision else "(blocked)",
        append_only_ledger_chain_valid=False,
        append_only_ledger_entry_count=0,
        count_drift_status="(awaiting)" if "AWAITING" in decision else "(blocked)",
        count_drift_expected=0,
        count_drift_actual=0,
        json_parse_status="(awaiting)" if "AWAITING" in decision else "(blocked)",
        source_evidence_paths=(),
        machine_readable_paths=(),
        evidence_ref="",
        captions=REQUIRED_PANEL_CAPTIONS,
        fixture_caveats_present=(),
        current_next_rung="",
        notes=(note,),
    )


def _cell_row(cell: dict, *, promoted: bool, blocked: bool) -> ProbeCellRow:
    return ProbeCellRow(
        cell_id=str(cell.get("cell_id") or "(unknown)"),
        claim_state=str(cell.get("claim_state") or "(unknown)"),
        support_state=str(cell.get("support_state") or "(unknown)"),
        workflow=str(cell.get("workflow") or ""),
        language=str(cell.get("language") or ""),
        app_class=str(cell.get("app_class") or ""),
        promoted=promoted,
        blocked=blocked,
        blocker=str(cell.get("blocker") or ""),
        missing_rung=str(cell.get("missing_rung") or ""),
        caveat=str(cell.get("caveat") or ""),
    )


def _blocked_path_summary(blob: dict) -> tuple[str, ...]:
    out: list[str] = []
    raw = blob.get("blocked_path_demo")
    if not isinstance(raw, list):
        return ()
    for item in raw:
        if isinstance(item, dict) and item.get("blocked"):
            out.append(str(item.get("scenario") or "unknown"))
    return tuple(sorted(out))


def _walk_strings_for_forbidden(node, hits: set[str]) -> None:
    if isinstance(node, str):
        lowered = node.lower()
        for phrase in FORBIDDEN_BROAD_CLAIM_PHRASES:
            if phrase in lowered:
                hits.add(phrase)
    elif isinstance(node, dict):
        for k, v in node.items():
            if isinstance(k, str) and k.lower() in _REFUSAL_CONTEXT_KEYS:
                continue
            _walk_strings_for_forbidden(v, hits)
    elif isinstance(node, list):
        for item in node:
            _walk_strings_for_forbidden(item, hits)


def _fixture_caveat_hits(blob: dict, captions: tuple[str, ...]) -> tuple[str, ...]:
    """Find which required fixture caveat substrings appear in claim_boundary / captions."""
    haystack = " ".join(
        list(blob.get("claim_boundary") or [])
        + list(blob.get("forbidden_claims") or [])
        + list(captions)
    ).lower()
    found: list[str] = []
    for needle in REQUIRED_FIXTURE_CAVEATS:
        if needle.lower() in haystack:
            found.append(needle)
    return tuple(found)


def _has_release_proof_reference(blob: dict) -> bool:
    """Check whether any source_evidence_paths reference a release-proof lock."""
    paths = blob.get("source_evidence_paths") or []
    for p in paths:
        s = str(p).lower()
        if "release_supported" in s or "release_proof" in s or "release_supported_lock" in s:
            return True
    return False


def load(
    evidence_dir: Path | str | None = None,
    *,
    cfg: _BatchConfig = BATCH_001,
) -> Universal100MatrixProbeBatchStatus:
    ed = Path(evidence_dir) if evidence_dir else cfg.evidence_dir
    chosen = _locate_latest_evidence(ed)
    if chosen is None:
        return _awaiting(f"no evidence file under {ed}", cfg=cfg)
    try:
        blob = json.loads(chosen.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return _awaiting(f"could not read evidence: {exc}", cfg=cfg)

    if blob.get("status") != cfg.expected_status:
        return _block(
            "REACT_UNIVERSAL_100_MATRIX_PROBE_EXECUTION_BATCH_BINDING_BLOCKED_MALFORMED",
            f"evidence status={blob.get('status')!r} (expected {cfg.expected_status})",
            cfg=cfg,
        )

    auth = blob.get("authority") or {}

    def _auth(flag: str) -> bool:
        return bool(blob.get(flag) is True or auth.get(flag) is True)

    authority_to_block = (
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
    )
    for flag in authority_to_block:
        if _auth(flag):
            return _block(
                "REACT_UNIVERSAL_100_MATRIX_PROBE_EXECUTION_BATCH_BINDING_BLOCKED_AUTHORITY_CONFUSION",
                f"authority flag {flag} is true (must be false)",
                cfg=cfg,
            )
    if _auth("broad_claims_granted"):
        return _block(
            "REACT_UNIVERSAL_100_MATRIX_PROBE_EXECUTION_BATCH_BINDING_BLOCKED_BROAD_CLAIM",
            "broad_claims_granted is true",
            cfg=cfg,
        )

    summary = blob.get("summary") or {}
    if "cells_probed" not in summary:
        return _block(
            "REACT_UNIVERSAL_100_MATRIX_PROBE_EXECUTION_BATCH_BINDING_BLOCKED_MALFORMED",
            "summary.cells_probed missing",
            cfg=cfg,
        )

    promoted_raw = blob.get("promoted_cells") or []
    blocked_raw = blob.get("blocked_cells")
    if blocked_raw is None:
        return _block(
            "REACT_UNIVERSAL_100_MATRIX_PROBE_EXECUTION_BATCH_BINDING_BLOCKED_BLOCKED_CELLS_HIDDEN",
            "blocked_cells key absent — blocked cells must remain visible",
            cfg=cfg,
        )

    promoted = tuple(_cell_row(c, promoted=True, blocked=False) for c in promoted_raw)
    blocked = tuple(_cell_row(c, promoted=False, blocked=True) for c in blocked_raw)

    # claim_above_evidence guard: an IMPLEMENTED claim requires demo_proven+.
    rank = {s: i for i, s in enumerate(SUPPORT_STATE_LADDER)}
    for row in promoted:
        c = row.claim_state.upper()
        s = row.support_state.lower()
        if s not in rank:
            return _block(
                "REACT_UNIVERSAL_100_MATRIX_PROBE_EXECUTION_BATCH_BINDING_BLOCKED_MALFORMED",
                f"promoted cell {row.cell_id} has unknown support_state {s!r}",
                cfg=cfg,
            )
        if c == "IMPLEMENTED" and rank[s] < rank["demo_proven"]:
            return _block(
                "REACT_UNIVERSAL_100_MATRIX_PROBE_EXECUTION_BATCH_BINDING_BLOCKED_MALFORMED",
                f"promoted cell {row.cell_id} has IMPLEMENTED claim but support_state {s} < demo_proven",
                cfg=cfg,
            )

    # release_supported overclaim guard.
    release_supported = int(summary.get("release_supported", 0))
    if release_supported > 0 and not _has_release_proof_reference(blob):
        return _block(
            "REACT_UNIVERSAL_100_MATRIX_PROBE_EXECUTION_BATCH_BINDING_BLOCKED_RELEASE_OVERCLAIM",
            f"summary.release_supported={release_supported} but no release-proof source path referenced",
            cfg=cfg,
        )

    captions = REQUIRED_PANEL_CAPTIONS

    # Fixture-caveat guard.
    fixture_hits = _fixture_caveat_hits(blob, captions)
    if not fixture_hits:
        return _block(
            "REACT_UNIVERSAL_100_MATRIX_PROBE_EXECUTION_BATCH_BINDING_BLOCKED_FIXTURE_CAVEAT_MISSING",
            f"required fixture caveats missing from claim_boundary/captions: {REQUIRED_FIXTURE_CAVEATS}",
            cfg=cfg,
        )

    # Forbidden broad-claim guard.
    hits: set[str] = set()
    _walk_strings_for_forbidden(blob, hits)
    if hits:
        return _block(
            "REACT_UNIVERSAL_100_MATRIX_PROBE_EXECUTION_BATCH_BINDING_BLOCKED_BROAD_CLAIM",
            f"forbidden broad-claim phrases as current claim: {sorted(hits)}",
            cfg=cfg,
        )

    support_counts = summary.get("support_state_counts") or {}
    blocker_counts = summary.get("blocker_counts") or {}
    evidence_health = blob.get("evidence_health") or {}

    promoted_count = int(summary.get("cells_promoted", len(promoted)))
    blocked_or_forbidden = int(summary.get("blocked_or_forbidden", len(blocked)))

    machine_paths = tuple(sorted(str(p) for p in (blob.get("output_paths") or [])))

    return Universal100MatrixProbeBatchStatus(
        decision="REACT_UNIVERSAL_100_MATRIX_PROBE_EXECUTION_BATCH_BINDING_PASSED",
        target_surface="Universal 100 Matrix Probe",
        target_workflow="matrix probe execution batch",
        batch_label=cfg.batch_label,
        batch_lock_id=cfg.batch_lock_id,
        cells_probed=int(summary.get("cells_probed", 0)),
        cells_promoted=promoted_count,
        blocked_or_forbidden=blocked_or_forbidden,
        cells_partial_or_roadmap=int(summary.get("cells_partial_or_roadmap", 0)),
        smoke_supported_count=int(support_counts.get("smoke_supported", 0)),
        repair_supported_count=int(support_counts.get("repair_supported", 0)),
        maintain_supported_count=int(support_counts.get("maintain_supported", 0)),
        release_supported_count=release_supported,
        build_supported_count=int(support_counts.get("build_supported", 0)),
        test_supported_count=int(support_counts.get("test_supported", 0)),
        scaffold_only_count=int(support_counts.get("scaffold_only", 0)),
        roadmap_count=int(support_counts.get("roadmap", 0)),
        unsupported_count=int(support_counts.get("unsupported", 0)),
        missing_oracle_count=int(summary.get("missing_oracle", 0)),
        missing_smoke_count=int(summary.get("missing_smoke", 0)),
        missing_toolchain_count=int(summary.get("missing_toolchain", 0)),
        missing_adapter_count=int(summary.get("missing_adapter", 0)),
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
        promoted_cells=promoted,
        blocked_cells=blocked,
        claim_boundary=tuple(str(b) for b in (blob.get("claim_boundary") or [])),
        forbidden_claims=tuple(str(f) for f in (blob.get("forbidden_claims") or [])),
        blocked_path_summary=_blocked_path_summary(blob),
        strongest_truthful_new_claim=str(blob.get("strongest_truthful_new_claim") or ""),
        evidence_index_count=int(evidence_health.get("evidence_index_count", 0)),
        evidence_index_entry_count_field=int(
            evidence_health.get("evidence_index_entry_count_field", 0)
        ),
        evidence_index_valid=bool(evidence_health.get("evidence_index_valid", False)),
        append_only_ledger_status=str(evidence_health.get("append_only_ledger_status", "")),
        append_only_ledger_chain_valid=bool(
            evidence_health.get("append_only_ledger_chain_valid", False)
        ),
        append_only_ledger_entry_count=int(
            evidence_health.get("append_only_ledger_entry_count", 0)
        ),
        count_drift_status=str(evidence_health.get("count_drift_status", "")),
        count_drift_expected=int(evidence_health.get("count_drift_expected", 0)),
        count_drift_actual=int(evidence_health.get("count_drift_actual", 0)),
        json_parse_status="passed",
        source_evidence_paths=tuple(str(p) for p in (blob.get("source_evidence_paths") or [])),
        machine_readable_paths=machine_paths,
        evidence_ref=str(_relative_to_repo(chosen)),
        captions=captions,
        fixture_caveats_present=fixture_hits,
        current_next_rung=str(blob.get("next_recommended_rung") or ""),
        notes=(),
    )


def _relative_to_repo(path: Path) -> str:
    try:
        return path.resolve().relative_to(_REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def load_batch_001(evidence_dir: Path | str | None = None) -> Universal100MatrixProbeBatchStatus:
    return load(evidence_dir, cfg=BATCH_001)


def load_batch_002(evidence_dir: Path | str | None = None) -> Universal100MatrixProbeBatchStatus:
    return load(evidence_dir, cfg=BATCH_002)


def load_batch_003(evidence_dir: Path | str | None = None) -> Universal100MatrixProbeBatchStatus:
    return load(evidence_dir, cfg=BATCH_003)


def load_batch_004(evidence_dir: Path | str | None = None) -> Universal100MatrixProbeBatchStatus:
    return load(evidence_dir, cfg=BATCH_004)


__all__ = [
    "load",
    "load_batch_001",
    "load_batch_002",
    "load_batch_003",
    "load_batch_004",
    "BATCH_001",
    "BATCH_002",
    "BATCH_003",
    "BATCH_004",
    "REQUIRED_PANEL_CAPTIONS",
    "SUPPORT_STATE_LADDER",
]
