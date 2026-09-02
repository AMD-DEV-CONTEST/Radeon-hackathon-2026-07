"""Universal 100 Support Map Delta Batch 002 status loader.

DETERMINEX_REACT_UNIVERSAL_100_SUPPORT_MAP_DELTA_BATCH_002_VISUAL_BINDING_LOCK_001.

load() reads the Codex Universal 100 Support Map Delta Batch 002
evidence and returns a render-safe view-model the React panel can
display. Delta = changes layered on top of the base support map.

The panel DISPLAYS evidence; it does NOT grant authority. Fixture-local
probe-driven delta promotions are not production / release / universal
support claims.

Hard rules enforced by load():

  * status != UNIVERSAL_100_SUPPORT_MAP_DELTA_BATCH_002_PASSED -> BLOCKED_MALFORMED
  * authority bag flag true -> BLOCKED_AUTHORITY_CONFUSION
  * broad_claims_granted true -> BLOCKED_BROAD_CLAIM
  * support_state_counts.release_supported > 0 without release-proof
    source path -> BLOCKED_RELEASE_OVERCLAIM
  * blocked_cells key absent -> BLOCKED_BLOCKED_CELLS_HIDDEN
  * forbidden broad-claim phrase as current claim outside refusal
    context -> BLOCKED_BROAD_CLAIM
  * promoted IMPLEMENTED claim with support_state < demo_proven
    -> BLOCKED_MALFORMED
  * any promoted cell with unknown support_state -> BLOCKED_MALFORMED
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
    SUPPORT_STATE_LADDER,
    _has_release_proof_reference,
    _walk_strings_for_forbidden,
)

_REPO_ROOT = _HERE.parent.parent.parent


class _DeltaConfig:
    """Per-batch configuration for the Support Map Delta loader."""

    def __init__(
        self,
        *,
        batch_label: str,
        evidence_dir_name: str,
        expected_status: str,
        decision_prefix: str,
        promoted_cells_field: str = "promoted_cells",
    ) -> None:
        self.batch_label = batch_label
        self.evidence_dir_name = evidence_dir_name
        self.expected_status = expected_status
        self.decision_prefix = decision_prefix
        self.promoted_cells_field = promoted_cells_field

    @property
    def evidence_dir(self) -> Path:
        return _REPO_ROOT / "assurance" / "evidence" / self.evidence_dir_name

    def token(self, suffix: str) -> str:
        return f"{self.decision_prefix}_{suffix}"


DELTA_BATCH_002 = _DeltaConfig(
    batch_label="Batch 002 delta",
    evidence_dir_name="universal_100_support_map_delta_batch_002",
    expected_status="UNIVERSAL_100_SUPPORT_MAP_DELTA_BATCH_002_PASSED",
    decision_prefix="REACT_UNIVERSAL_100_SUPPORT_MAP_DELTA_BATCH_002_BINDING",
)
DELTA_BATCH_003 = _DeltaConfig(
    batch_label="Batch 003 delta",
    evidence_dir_name="universal_100_support_map_delta_batch_003",
    expected_status="UNIVERSAL_100_SUPPORT_MAP_DELTA_BATCH_003_PASSED",
    decision_prefix="REACT_UNIVERSAL_100_SUPPORT_MAP_DELTA_BATCH_003_BINDING",
)
DELTA_BATCH_004 = _DeltaConfig(
    batch_label="Batch 004 delta",
    evidence_dir_name="universal_100_support_map_delta_batch_004",
    expected_status="UNIVERSAL_100_SUPPORT_MAP_DELTA_BATCH_004_PASSED",
    decision_prefix="REACT_UNIVERSAL_100_SUPPORT_MAP_DELTA_BATCH_004_BINDING",
)
DELTA_BATCH_005 = _DeltaConfig(
    batch_label="Batch 005 delta",
    evidence_dir_name="universal_100_support_map_delta_batch_005",
    expected_status="UNIVERSAL_100_SUPPORT_MAP_DELTA_BATCH_005_PASSED",
    decision_prefix="REACT_UNIVERSAL_100_SUPPORT_MAP_DELTA_BATCH_005_BINDING",
)
DELTA_BATCH_006 = _DeltaConfig(
    batch_label="Batch 006 delta",
    evidence_dir_name="universal_100_support_map_delta_batch_006",
    expected_status="UNIVERSAL_100_SUPPORT_MAP_DELTA_BATCH_006_PASSED",
    decision_prefix="REACT_UNIVERSAL_100_SUPPORT_MAP_DELTA_BATCH_006_BINDING",
)
DELTA_BATCH_007 = _DeltaConfig(
    batch_label="Batch 007 delta",
    evidence_dir_name="universal_100_support_map_delta_batch_007",
    expected_status="UNIVERSAL_100_SUPPORT_MAP_DELTA_BATCH_007_PASSED",
    decision_prefix="REACT_UNIVERSAL_100_SUPPORT_MAP_DELTA_BATCH_007_BINDING",
)
DELTA_BATCH_008 = _DeltaConfig(
    batch_label="Batch 008 delta",
    evidence_dir_name="universal_100_support_map_delta_batch_008",
    expected_status="UNIVERSAL_100_SUPPORT_MAP_DELTA_BATCH_008_PASSED",
    decision_prefix="REACT_UNIVERSAL_100_SUPPORT_MAP_DELTA_BATCH_008_BINDING",
)
DELTA_BATCH_009 = _DeltaConfig(
    batch_label="Batch 009 delta",
    evidence_dir_name="universal_100_support_map_delta_batch_009",
    expected_status="UNIVERSAL_100_SUPPORT_MAP_DELTA_BATCH_009_PASSED",
    decision_prefix="REACT_UNIVERSAL_100_SUPPORT_MAP_DELTA_BATCH_009_BINDING",
)
DELTA_BATCH_010 = _DeltaConfig(
    batch_label="Batch 010 delta",
    evidence_dir_name="universal_100_support_map_delta_batch_010",
    expected_status="UNIVERSAL_100_SUPPORT_MAP_DELTA_BATCH_010_PASSED",
    decision_prefix="REACT_UNIVERSAL_100_SUPPORT_MAP_DELTA_BATCH_010_BINDING",
)
DELTA_BATCH_011 = _DeltaConfig(
    batch_label="Batch 011 delta",
    evidence_dir_name="universal_100_support_map_delta_batch_011",
    expected_status="UNIVERSAL_100_SUPPORT_MAP_DELTA_BATCH_011_PASSED",
    decision_prefix="REACT_UNIVERSAL_100_SUPPORT_MAP_DELTA_BATCH_011_BINDING",
)
DELTA_BATCH_012 = _DeltaConfig(
    batch_label="Batch 012 delta",
    evidence_dir_name="universal_100_support_map_delta_batch_012",
    expected_status="UNIVERSAL_100_SUPPORT_MAP_DELTA_BATCH_012_PASSED",
    decision_prefix="REACT_UNIVERSAL_100_SUPPORT_MAP_DELTA_BATCH_012_BINDING",
)
DELTA_BATCH_013 = _DeltaConfig(
    batch_label="Batch 013 delta",
    evidence_dir_name="universal_100_support_map_delta_batch_013",
    expected_status="UNIVERSAL_100_SUPPORT_MAP_DELTA_BATCH_013_PASSED",
    decision_prefix="REACT_UNIVERSAL_100_SUPPORT_MAP_DELTA_BATCH_013_BINDING",
)
DELTA_BATCH_014 = _DeltaConfig(
    batch_label="Batch 014 delta",
    evidence_dir_name="universal_100_support_map_delta_batch_014",
    expected_status="UNIVERSAL_100_SUPPORT_MAP_DELTA_BATCH_014_PASSED",
    decision_prefix="REACT_UNIVERSAL_100_SUPPORT_MAP_DELTA_BATCH_014_BINDING",
    promoted_cells_field="support_map_delta",
)
DELTA_BATCH_015 = _DeltaConfig(
    batch_label="Batch 015 delta",
    evidence_dir_name="universal_100_support_map_delta_batch_015",
    expected_status="UNIVERSAL_100_SUPPORT_MAP_DELTA_BATCH_015_PASSED",
    decision_prefix="REACT_UNIVERSAL_100_SUPPORT_MAP_DELTA_BATCH_015_BINDING",
    promoted_cells_field="support_map_delta",
)
DELTA_BATCH_016 = _DeltaConfig(
    batch_label="Batch 016 delta",
    evidence_dir_name="universal_100_support_map_delta_batch_016",
    expected_status="UNIVERSAL_100_SUPPORT_MAP_DELTA_BATCH_016_PASSED",
    decision_prefix="REACT_UNIVERSAL_100_SUPPORT_MAP_DELTA_BATCH_016_BINDING",
    promoted_cells_field="support_map_delta",
)
DELTA_BATCH_017 = _DeltaConfig(
    batch_label="Batch 017 delta",
    evidence_dir_name="universal_100_support_map_delta_batch_017",
    expected_status="UNIVERSAL_100_SUPPORT_MAP_DELTA_BATCH_017_PASSED",
    decision_prefix="REACT_UNIVERSAL_100_SUPPORT_MAP_DELTA_BATCH_017_BINDING",
    promoted_cells_field="support_map_delta",
)
DELTA_BATCH_018 = _DeltaConfig(
    batch_label="Batch 018 delta",
    evidence_dir_name="universal_100_support_map_delta_batch_018",
    expected_status="UNIVERSAL_100_SUPPORT_MAP_DELTA_BATCH_018_PASSED",
    decision_prefix="REACT_UNIVERSAL_100_SUPPORT_MAP_DELTA_BATCH_018_BINDING",
    promoted_cells_field="support_map_delta",
)
DELTA_BATCH_019 = _DeltaConfig(
    batch_label="Batch 019 delta",
    evidence_dir_name="universal_100_support_map_delta_batch_019",
    expected_status="UNIVERSAL_100_SUPPORT_MAP_DELTA_BATCH_019_PASSED",
    decision_prefix="REACT_UNIVERSAL_100_SUPPORT_MAP_DELTA_BATCH_019_BINDING",
    promoted_cells_field="support_map_delta",
)


# Back-compat aliases (Batch 002 used these names verbatim).
_DEFAULT_EVIDENCE_DIR = DELTA_BATCH_002.evidence_dir
EXPECTED_STATUS = DELTA_BATCH_002.expected_status

REQUIRED_PANEL_CAPTIONS = (
    "This panel displays evidence; it does not grant authority.",
    "Support map delta is layered on top of the base map.",
    "Fixture-local probe-driven promotion is not production readiness.",
    "Universal 100 means universal intake/routing, not magic execution.",
    "No source mutation without authority.",
    "No release claim without release proof.",
    "Unsupported and blocked cells are routed by exact missing rung.",
)


REACT_UNIVERSAL_100_SUPPORT_MAP_DELTA_BATCH_002_BINDING_STATUS_TOKENS = (
    "REACT_UNIVERSAL_100_SUPPORT_MAP_DELTA_BATCH_002_BINDING_PASSED",
    "REACT_UNIVERSAL_100_SUPPORT_MAP_DELTA_BATCH_002_BINDING_AWAITING_EVIDENCE",
    "REACT_UNIVERSAL_100_SUPPORT_MAP_DELTA_BATCH_002_BINDING_BLOCKED_MALFORMED",
    "REACT_UNIVERSAL_100_SUPPORT_MAP_DELTA_BATCH_002_BINDING_BLOCKED_AUTHORITY_CONFUSION",
    "REACT_UNIVERSAL_100_SUPPORT_MAP_DELTA_BATCH_002_BINDING_BLOCKED_BROAD_CLAIM",
    "REACT_UNIVERSAL_100_SUPPORT_MAP_DELTA_BATCH_002_BINDING_BLOCKED_RELEASE_OVERCLAIM",
    "REACT_UNIVERSAL_100_SUPPORT_MAP_DELTA_BATCH_002_BINDING_BLOCKED_BLOCKED_CELLS_HIDDEN",
)


@dataclass(frozen=True)
class DeltaCellRow:
    cell_id: str
    claim_state: str
    support_state: str
    workflow: str
    language: str
    caveat: str


@dataclass(frozen=True)
class Universal100SupportMapDeltaStatus:
    decision: str
    target_surface: str
    target_workflow: str
    batch_label: str
    delta_sources: tuple[str, ...]
    promoted_cells: tuple[DeltaCellRow, ...]
    blocked_cells: tuple[DeltaCellRow, ...]
    claim_state_counts: dict[str, int]
    support_state_counts: dict[str, int]
    blockers_by_category: dict[str, int]
    release_supported_count: int
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
    claim_boundary: tuple[str, ...]
    forbidden_claims: tuple[str, ...]
    strongest_truthful_claim: str
    evidence_index_count: int
    evidence_index_valid: bool
    append_only_ledger_status: str
    append_only_ledger_chain_valid: bool
    append_only_ledger_entry_count: int
    count_drift_status: str
    count_drift_expected: int
    count_drift_actual: int
    evidence_ref: str
    captions: tuple[str, ...]
    current_next_rung: str
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["promoted_cells"] = [asdict(c) for c in self.promoted_cells]
        d["blocked_cells"] = [asdict(c) for c in self.blocked_cells]
        d["delta_sources"] = list(self.delta_sources)
        d["claim_boundary"] = list(self.claim_boundary)
        d["forbidden_claims"] = list(self.forbidden_claims)
        d["captions"] = list(self.captions)
        d["notes"] = list(self.notes)
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


def _cell_row(cell: dict) -> DeltaCellRow:
    return DeltaCellRow(
        cell_id=str(cell.get("cell_id") or "(unknown)"),
        claim_state=str(cell.get("claim_state") or "(unknown)"),
        support_state=str(cell.get("support_state") or "(unknown)"),
        workflow=str(cell.get("workflow") or ""),
        language=str(cell.get("language") or ""),
        caveat=str(cell.get("caveat") or ""),
    )


def _shell(
    *, decision: str, note: str, cfg: _DeltaConfig = DELTA_BATCH_002
) -> Universal100SupportMapDeltaStatus:
    return Universal100SupportMapDeltaStatus(
        decision=decision,
        target_surface="Universal 100 Support Map Delta",
        target_workflow="(awaiting evidence)" if "AWAITING" in decision else "(blocked)",
        batch_label=cfg.batch_label,
        delta_sources=(),
        promoted_cells=(),
        blocked_cells=(),
        claim_state_counts={},
        support_state_counts={},
        blockers_by_category={},
        release_supported_count=0,
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
        claim_boundary=(),
        forbidden_claims=(),
        strongest_truthful_claim="(awaiting evidence)" if "AWAITING" in decision else "(blocked)",
        evidence_index_count=0,
        evidence_index_valid=False,
        append_only_ledger_status="(awaiting)" if "AWAITING" in decision else "(blocked)",
        append_only_ledger_chain_valid=False,
        append_only_ledger_entry_count=0,
        count_drift_status="(awaiting)" if "AWAITING" in decision else "(blocked)",
        count_drift_expected=0,
        count_drift_actual=0,
        evidence_ref="",
        captions=REQUIRED_PANEL_CAPTIONS,
        current_next_rung="",
        notes=(note,),
    )


def _awaiting(note: str, cfg: _DeltaConfig = DELTA_BATCH_002) -> Universal100SupportMapDeltaStatus:
    return _shell(
        decision=cfg.token("AWAITING_EVIDENCE"),
        note=note,
        cfg=cfg,
    )


def _block(
    decision: str, note: str, cfg: _DeltaConfig = DELTA_BATCH_002
) -> Universal100SupportMapDeltaStatus:
    return _shell(decision=decision, note=note, cfg=cfg)


def load(
    evidence_dir: Path | str | None = None,
    *,
    cfg: _DeltaConfig = DELTA_BATCH_002,
) -> Universal100SupportMapDeltaStatus:
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
            cfg.token("BLOCKED_MALFORMED"),
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
                cfg.token("BLOCKED_AUTHORITY_CONFUSION"),
                f"authority flag {flag} is true",
                cfg=cfg,
            )
    if _auth("broad_claims_granted"):
        return _block(
            cfg.token("BLOCKED_BROAD_CLAIM"),
            "broad_claims_granted is true",
            cfg=cfg,
        )

    promoted_raw = blob.get(cfg.promoted_cells_field) or []
    blocked_raw = blob.get("blocked_cells")
    if blocked_raw is None:
        return _block(
            cfg.token("BLOCKED_BLOCKED_CELLS_HIDDEN"),
            "blocked_cells key absent",
            cfg=cfg,
        )

    promoted = tuple(_cell_row(c) for c in promoted_raw)
    blocked = tuple(_cell_row(c) for c in blocked_raw)

    rank = {s: i for i, s in enumerate(SUPPORT_STATE_LADDER)}
    for row in promoted:
        s = row.support_state.lower()
        c = row.claim_state.upper()
        if s not in rank:
            return _block(
                cfg.token("BLOCKED_MALFORMED"),
                f"promoted cell {row.cell_id} unknown support_state {s!r}",
                cfg=cfg,
            )
        if c == "IMPLEMENTED" and rank[s] < rank["demo_proven"]:
            return _block(
                cfg.token("BLOCKED_MALFORMED"),
                f"promoted cell {row.cell_id} IMPLEMENTED but support_state {s} < demo_proven",
                cfg=cfg,
            )

    support_counts = blob.get("support_state_counts") or {}
    release_supported = int(support_counts.get("release_supported", 0))
    if release_supported > 0 and not _has_release_proof_reference(blob):
        return _block(
            cfg.token("BLOCKED_RELEASE_OVERCLAIM"),
            f"release_supported={release_supported} without release-proof source path",
            cfg=cfg,
        )

    hits: set[str] = set()
    _walk_strings_for_forbidden(blob, hits)
    if hits:
        return _block(
            cfg.token("BLOCKED_BROAD_CLAIM"),
            f"forbidden broad-claim phrases as current claim: {sorted(hits)}",
            cfg=cfg,
        )

    eh = blob.get("evidence_health") or {}

    return Universal100SupportMapDeltaStatus(
        decision=cfg.token("PASSED"),
        target_surface="Universal 100 Support Map Delta",
        target_workflow="support map delta batch",
        batch_label=cfg.batch_label,
        delta_sources=tuple(str(s) for s in (blob.get("delta_sources") or [])),
        promoted_cells=promoted,
        blocked_cells=blocked,
        claim_state_counts={
            str(k): int(v) for k, v in (blob.get("claim_state_counts") or {}).items()
        },
        support_state_counts={str(k): int(v) for k, v in support_counts.items()},
        blockers_by_category={
            str(k): int(v) for k, v in (blob.get("blockers_by_category") or {}).items()
        },
        release_supported_count=release_supported,
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
        claim_boundary=tuple(str(b) for b in (blob.get("claim_boundary") or [])),
        forbidden_claims=tuple(str(f) for f in (blob.get("forbidden_claims") or [])),
        strongest_truthful_claim=str(blob.get("strongest_truthful_claim") or ""),
        evidence_index_count=int(eh.get("evidence_index_count", 0)),
        evidence_index_valid=bool(eh.get("evidence_index_valid", False)),
        append_only_ledger_status=str(eh.get("append_only_ledger_status", "")),
        append_only_ledger_chain_valid=bool(eh.get("append_only_ledger_chain_valid", False)),
        append_only_ledger_entry_count=int(eh.get("append_only_ledger_entry_count", 0)),
        count_drift_status=str(eh.get("count_drift_status", "")),
        count_drift_expected=int(eh.get("count_drift_expected", 0)),
        count_drift_actual=int(eh.get("count_drift_actual", 0)),
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


def load_delta_batch_002(
    evidence_dir: Path | str | None = None,
) -> Universal100SupportMapDeltaStatus:
    return load(evidence_dir, cfg=DELTA_BATCH_002)


def load_delta_batch_003(
    evidence_dir: Path | str | None = None,
) -> Universal100SupportMapDeltaStatus:
    return load(evidence_dir, cfg=DELTA_BATCH_003)


def load_delta_batch_004(
    evidence_dir: Path | str | None = None,
) -> Universal100SupportMapDeltaStatus:
    return load(evidence_dir, cfg=DELTA_BATCH_004)


def load_delta_batch_005(
    evidence_dir: Path | str | None = None,
) -> Universal100SupportMapDeltaStatus:
    return load(evidence_dir, cfg=DELTA_BATCH_005)


def load_delta_batch_006(
    evidence_dir: Path | str | None = None,
) -> Universal100SupportMapDeltaStatus:
    return load(evidence_dir, cfg=DELTA_BATCH_006)


def load_delta_batch_007(
    evidence_dir: Path | str | None = None,
) -> Universal100SupportMapDeltaStatus:
    return load(evidence_dir, cfg=DELTA_BATCH_007)


def load_delta_batch_008(
    evidence_dir: Path | str | None = None,
) -> Universal100SupportMapDeltaStatus:
    return load(evidence_dir, cfg=DELTA_BATCH_008)


def load_delta_batch_009(
    evidence_dir: Path | str | None = None,
) -> Universal100SupportMapDeltaStatus:
    return load(evidence_dir, cfg=DELTA_BATCH_009)


def load_delta_batch_010(
    evidence_dir: Path | str | None = None,
) -> Universal100SupportMapDeltaStatus:
    return load(evidence_dir, cfg=DELTA_BATCH_010)


def load_delta_batch_011(
    evidence_dir: Path | str | None = None,
) -> Universal100SupportMapDeltaStatus:
    return load(evidence_dir, cfg=DELTA_BATCH_011)


def load_delta_batch_012(
    evidence_dir: Path | str | None = None,
) -> Universal100SupportMapDeltaStatus:
    return load(evidence_dir, cfg=DELTA_BATCH_012)


def load_delta_batch_013(
    evidence_dir: Path | str | None = None,
) -> Universal100SupportMapDeltaStatus:
    return load(evidence_dir, cfg=DELTA_BATCH_013)


def load_delta_batch_014(
    evidence_dir: Path | str | None = None,
) -> Universal100SupportMapDeltaStatus:
    return load(evidence_dir, cfg=DELTA_BATCH_014)


def load_delta_batch_015(
    evidence_dir: Path | str | None = None,
) -> Universal100SupportMapDeltaStatus:
    return load(evidence_dir, cfg=DELTA_BATCH_015)


def load_delta_batch_016(
    evidence_dir: Path | str | None = None,
) -> Universal100SupportMapDeltaStatus:
    return load(evidence_dir, cfg=DELTA_BATCH_016)


def load_delta_batch_017(
    evidence_dir: Path | str | None = None,
) -> Universal100SupportMapDeltaStatus:
    return load(evidence_dir, cfg=DELTA_BATCH_017)


def load_delta_batch_018(
    evidence_dir: Path | str | None = None,
) -> Universal100SupportMapDeltaStatus:
    return load(evidence_dir, cfg=DELTA_BATCH_018)


def load_delta_batch_019(
    evidence_dir: Path | str | None = None,
) -> Universal100SupportMapDeltaStatus:
    return load(evidence_dir, cfg=DELTA_BATCH_019)


REACT_UNIVERSAL_100_SUPPORT_MAP_DELTA_BATCH_003_BINDING_STATUS_TOKENS = tuple(
    DELTA_BATCH_003.token(suffix)
    for suffix in (
        "PASSED",
        "AWAITING_EVIDENCE",
        "BLOCKED_MALFORMED",
        "BLOCKED_AUTHORITY_CONFUSION",
        "BLOCKED_BROAD_CLAIM",
        "BLOCKED_RELEASE_OVERCLAIM",
        "BLOCKED_BLOCKED_CELLS_HIDDEN",
    )
)
REACT_UNIVERSAL_100_SUPPORT_MAP_DELTA_BATCH_004_BINDING_STATUS_TOKENS = tuple(
    DELTA_BATCH_004.token(suffix)
    for suffix in (
        "PASSED",
        "AWAITING_EVIDENCE",
        "BLOCKED_MALFORMED",
        "BLOCKED_AUTHORITY_CONFUSION",
        "BLOCKED_BROAD_CLAIM",
        "BLOCKED_RELEASE_OVERCLAIM",
        "BLOCKED_BLOCKED_CELLS_HIDDEN",
    )
)


__all__ = [
    "load",
    "load_delta_batch_002",
    "load_delta_batch_003",
    "load_delta_batch_004",
    "DELTA_BATCH_002",
    "DELTA_BATCH_003",
    "DELTA_BATCH_004",
    "REACT_UNIVERSAL_100_SUPPORT_MAP_DELTA_BATCH_002_BINDING_STATUS_TOKENS",
    "REACT_UNIVERSAL_100_SUPPORT_MAP_DELTA_BATCH_003_BINDING_STATUS_TOKENS",
    "REACT_UNIVERSAL_100_SUPPORT_MAP_DELTA_BATCH_004_BINDING_STATUS_TOKENS",
    "REQUIRED_PANEL_CAPTIONS",
    "DeltaCellRow",
    "Universal100SupportMapDeltaStatus",
]
