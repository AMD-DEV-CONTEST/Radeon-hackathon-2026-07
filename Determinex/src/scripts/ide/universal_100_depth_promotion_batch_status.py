"""Universal 100 Depth Promotion Batch status loader (017/018/019).

DETERMINEX_REACT_UNIVERSAL_100_DEPTH_PROMOTION_BATCH_NNN_BINDING_LOCK_001.

load() reads Codex's depth-promotion batch evidence and returns a render-
safe view-model the React panel can display. Depth-promotion batches
raise support depth one rung at a time within bounded fixture-local
probes — they do NOT create universal support and they do NOT promote
to release.

The panel DISPLAYS evidence; it does NOT grant authority. Depth
promotion is bounded fixture-local probe proof. Scaffold-supported is
not working-app proof. Build-supported is not release support.

Hard rules enforced by load():

  * status != UNIVERSAL_100_DEPTH_PROMOTION_BATCH_NNN_PASSED ->
    BLOCKED_MALFORMED
  * authority bag flag true -> BLOCKED_AUTHORITY_CONFUSION
  * broad_claims_granted true -> BLOCKED_BROAD_CLAIM
  * release_supported > 0 without release-proof reference ->
    BLOCKED_RELEASE_OVERCLAIM
  * user_ready_with_caveats > 0 without user-ready proof reference ->
    BLOCKED_USER_READY_OVERCLAIM
  * blocked_cells key absent -> BLOCKED_BLOCKED_CELLS_HIDDEN
  * promoted_cells key absent -> BLOCKED_MALFORMED
  * depth_promotion_plan key absent -> BLOCKED_MALFORMED
  * promoted cell unknown support_state -> BLOCKED_MALFORMED
  * promoted cell IMPLEMENTED claim but support_state < demo_proven ->
    BLOCKED_MALFORMED
  * fixture-local caveat missing -> BLOCKED_FIXTURE_CAVEAT_MISSING
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
    SUPPORT_STATE_LADDER,
    _has_release_proof_reference,
    _walk_strings_for_forbidden,
)

_REPO_ROOT = _HERE.parent.parent.parent


def _as_int(v) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


class _DepthBatchConfig:
    """Per-batch depth-promotion configuration."""

    def __init__(
        self,
        *,
        batch_label: str,
        batch_lock_id: str,
        evidence_dir_name: str,
        expected_status: str,
        decision_prefix: str,
        expected_sectors: tuple[str, ...],
    ) -> None:
        self.batch_label = batch_label
        self.batch_lock_id = batch_lock_id
        self.evidence_dir_name = evidence_dir_name
        self.expected_status = expected_status
        self.decision_prefix = decision_prefix
        self.expected_sectors = expected_sectors

    @property
    def evidence_dir(self) -> Path:
        return _REPO_ROOT / "assurance" / "evidence" / self.evidence_dir_name

    def token(self, suffix: str) -> str:
        return f"{self.decision_prefix}_{suffix}"


DEPTH_PROMOTION_BATCH_017 = _DepthBatchConfig(
    batch_label="Depth Promotion Batch 017",
    batch_lock_id="DETERMINEX_UNIVERSAL_100_DEPTH_PROMOTION_BATCH_017_LOCK_001",
    evidence_dir_name="universal_100_depth_promotion_batch_017",
    expected_status="UNIVERSAL_100_DEPTH_PROMOTION_BATCH_017_PASSED",
    decision_prefix="REACT_UNIVERSAL_100_DEPTH_PROMOTION_BATCH_017_BINDING",
    expected_sectors=(
        "infrastructure_as_code_sector",
        "data_science_notebooks_sector",
        "ml_inference_apps_sector",
    ),
)
DEPTH_PROMOTION_BATCH_018 = _DepthBatchConfig(
    batch_label="Depth Promotion Batch 018",
    batch_lock_id="DETERMINEX_UNIVERSAL_100_DEPTH_PROMOTION_BATCH_018_LOCK_001",
    evidence_dir_name="universal_100_depth_promotion_batch_018",
    expected_status="UNIVERSAL_100_DEPTH_PROMOTION_BATCH_018_PASSED",
    decision_prefix="REACT_UNIVERSAL_100_DEPTH_PROMOTION_BATCH_018_BINDING",
    expected_sectors=(
        "swift_ios_sector",
        "kotlin_android_sector",
        "mobile_cross_platform_sector",
    ),
)
DEPTH_PROMOTION_BATCH_019 = _DepthBatchConfig(
    batch_label="Depth Promotion Batch 019",
    batch_lock_id="DETERMINEX_UNIVERSAL_100_DEPTH_PROMOTION_BATCH_019_LOCK_001",
    evidence_dir_name="universal_100_depth_promotion_batch_019",
    expected_status="UNIVERSAL_100_DEPTH_PROMOTION_BATCH_019_PASSED",
    decision_prefix="REACT_UNIVERSAL_100_DEPTH_PROMOTION_BATCH_019_BINDING",
    expected_sectors=(
        "c_c_sector",
        "embedded_iot_sector",
        "unknown_novel_app_class_catch_all_sector",
    ),
)


REQUIRED_PANEL_CAPTIONS = (
    "This panel displays evidence; it does not grant authority.",
    "Depth promotion raises proof depth; it does not create universal support.",
    "Determinex's roadmap is universal by intake, routing, blocker accounting, and proof discipline.",
    "Universal roadmap does not mean every edge case is supported today.",
    "Every edge case must be supported, blocked by exact missing rung, forbidden, or roadmap.",
    "Family evidence is not full family support.",
    "Scaffold-supported is not working-app proof.",
    "Build-supported is not release support.",
    "Smoke-supported is not production proof.",
    "Unknown/novel routing is not arbitrary app support.",
    "Fixture-local proof is not production readiness.",
    "Blocked cells remain visible by exact missing rung.",
    "No source mutation without authority.",
)

REQUIRED_FIXTURE_CAVEATS = ("fixture-local",)


@dataclass(frozen=True)
class DepthPromotionCellRow:
    cell_id: str
    sector_id: str
    family: str
    batch: str
    claim_state: str
    support_state: str
    claim_boundary: str
    missing_rung: str
    setup_caveats: tuple[str, ...]
    fixture_path: str
    fixture_workspace_hash: str
    evidence_paths: tuple[str, ...]
    promoted: bool
    blocked: bool


@dataclass(frozen=True)
class DepthPromotionProbeRow:
    cell_id: str
    sector_id: str
    outcome: str
    note: str


@dataclass(frozen=True)
class DepthPromotionPlanRow:
    sector_id: str
    family: str
    current_depth: str
    target_depth: str
    safe_next_rung: str
    can_attempt_local_proof_now: bool


@dataclass(frozen=True)
class Universal100DepthPromotionBatchStatus:
    decision: str
    target_surface: str
    target_workflow: str
    batch_label: str
    batch_lock_id: str
    cells_probed: int
    cells_promoted: int
    cells_blocked: int
    release_supported: int
    user_ready_with_caveats: int
    families_improved: tuple[str, ...]
    expected_sectors: tuple[str, ...]
    claim_state_counts: dict[str, int]
    support_state_counts: dict[str, int]
    missing_rung_counts: dict[str, int]
    promoted_cells: tuple[DepthPromotionCellRow, ...]
    blocked_cells: tuple[DepthPromotionCellRow, ...]
    probe_results: tuple[DepthPromotionProbeRow, ...]
    depth_promotion_plan: tuple[DepthPromotionPlanRow, ...]
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
    strongest_truthful_new_claim: str
    evidence_ref: str
    captions: tuple[str, ...]
    fixture_caveats_present: tuple[str, ...]
    current_next_rung: str
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["promoted_cells"] = [asdict(c) for c in self.promoted_cells]
        d["blocked_cells"] = [asdict(c) for c in self.blocked_cells]
        d["probe_results"] = [asdict(p) for p in self.probe_results]
        d["depth_promotion_plan"] = [asdict(p) for p in self.depth_promotion_plan]
        for k in (
            "families_improved",
            "expected_sectors",
            "claim_boundary",
            "forbidden_claims",
            "captions",
            "fixture_caveats_present",
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


def _cell_row(cell: dict, *, promoted: bool, blocked: bool) -> DepthPromotionCellRow:
    return DepthPromotionCellRow(
        cell_id=str(cell.get("cell_id") or "(unknown)"),
        sector_id=str(cell.get("sector_id") or ""),
        family=str(cell.get("family") or ""),
        batch=str(cell.get("batch") or ""),
        claim_state=str(cell.get("claim_state") or "(unknown)"),
        support_state=str(cell.get("support_state") or "(unknown)"),
        claim_boundary=str(cell.get("claim_boundary") or ""),
        missing_rung=str(cell.get("missing_rung") or ""),
        setup_caveats=tuple(str(x) for x in (cell.get("setup_caveats") or [])),
        fixture_path=str(cell.get("fixture_path") or ""),
        fixture_workspace_hash=str(cell.get("fixture_workspace_hash") or ""),
        evidence_paths=tuple(str(p) for p in (cell.get("evidence_paths") or [])),
        promoted=promoted,
        blocked=blocked,
    )


def _probe_row(p: dict) -> DepthPromotionProbeRow:
    return DepthPromotionProbeRow(
        cell_id=str(p.get("cell_id") or ""),
        sector_id=str(p.get("sector_id") or ""),
        outcome=str(p.get("outcome") or p.get("result") or ""),
        note=str(p.get("note") or p.get("message") or ""),
    )


def _plan_row(p: dict) -> DepthPromotionPlanRow:
    return DepthPromotionPlanRow(
        sector_id=str(p.get("sector_id") or ""),
        family=str(p.get("family") or ""),
        current_depth=str(p.get("current_depth") or p.get("current_highest_support_depth") or ""),
        target_depth=str(p.get("target_depth") or p.get("target_support_depth") or ""),
        safe_next_rung=str(p.get("safe_next_rung") or p.get("easiest_next_rung") or ""),
        can_attempt_local_proof_now=bool(
            p.get("can_attempt_local_proof_now")
            or p.get("safe_local_proof_can_be_attempted_now")
            or False
        ),
    )


def _fixture_caveat_hits(blob: dict, captions: tuple[str, ...]) -> tuple[str, ...]:
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


def _shell(
    *,
    decision: str,
    note: str,
    cfg: _DepthBatchConfig = DEPTH_PROMOTION_BATCH_017,
) -> Universal100DepthPromotionBatchStatus:
    return Universal100DepthPromotionBatchStatus(
        decision=decision,
        target_surface="Universal 100 Depth Promotion Batch",
        target_workflow="(awaiting evidence)" if "AWAITING" in decision else "(blocked)",
        batch_label=cfg.batch_label,
        batch_lock_id=cfg.batch_lock_id,
        cells_probed=0,
        cells_promoted=0,
        cells_blocked=0,
        release_supported=0,
        user_ready_with_caveats=0,
        families_improved=(),
        expected_sectors=cfg.expected_sectors,
        claim_state_counts={},
        support_state_counts={},
        missing_rung_counts={},
        promoted_cells=(),
        blocked_cells=(),
        probe_results=(),
        depth_promotion_plan=(),
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
        strongest_truthful_new_claim="(awaiting evidence)"
        if "AWAITING" in decision
        else "(blocked)",
        evidence_ref="",
        captions=REQUIRED_PANEL_CAPTIONS,
        fixture_caveats_present=(),
        current_next_rung="",
        notes=(note,),
    )


def _awaiting(
    note: str, cfg: _DepthBatchConfig = DEPTH_PROMOTION_BATCH_017
) -> Universal100DepthPromotionBatchStatus:
    return _shell(decision=cfg.token("AWAITING_EVIDENCE"), note=note, cfg=cfg)


def _block(
    decision: str, note: str, cfg: _DepthBatchConfig = DEPTH_PROMOTION_BATCH_017
) -> Universal100DepthPromotionBatchStatus:
    return _shell(decision=decision, note=note, cfg=cfg)


def _has_user_ready_proof_reference(blob: dict) -> bool:
    paths = blob.get("source_evidence_paths") or []
    for p in paths:
        s = str(p).lower()
        if "user_ready" in s or "fresh_install_verified" in s:
            return True
    return False


def load(
    evidence_dir: Path | str | None = None,
    *,
    cfg: _DepthBatchConfig = DEPTH_PROMOTION_BATCH_017,
) -> Universal100DepthPromotionBatchStatus:
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

    blocked_raw = blob.get("blocked_cells")
    if blocked_raw is None:
        return _block(
            cfg.token("BLOCKED_BLOCKED_CELLS_HIDDEN"),
            "blocked_cells key absent — blocked cells must remain visible",
            cfg=cfg,
        )
    promoted_raw = blob.get("promoted_cells")
    if promoted_raw is None:
        return _block(
            cfg.token("BLOCKED_MALFORMED"),
            "promoted_cells key absent",
            cfg=cfg,
        )
    plan_raw = blob.get("depth_promotion_plan")
    if plan_raw is None:
        return _block(
            cfg.token("BLOCKED_MALFORMED"),
            "depth_promotion_plan key absent",
            cfg=cfg,
        )

    promoted = tuple(_cell_row(c, promoted=True, blocked=False) for c in promoted_raw)
    blocked = tuple(_cell_row(c, promoted=False, blocked=True) for c in blocked_raw)

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

    release_supported = _as_int(blob.get("release_supported", 0))
    if release_supported > 0 and not _has_release_proof_reference(blob):
        return _block(
            cfg.token("BLOCKED_RELEASE_OVERCLAIM"),
            f"release_supported={release_supported} without release-proof source path",
            cfg=cfg,
        )

    user_ready_with_caveats = _as_int(blob.get("user_ready_with_caveats", 0))
    if user_ready_with_caveats > 0 and not _has_user_ready_proof_reference(blob):
        return _block(
            cfg.token("BLOCKED_USER_READY_OVERCLAIM"),
            f"user_ready_with_caveats={user_ready_with_caveats} without user-ready proof reference",
            cfg=cfg,
        )

    fixture_hits = _fixture_caveat_hits(blob, REQUIRED_PANEL_CAPTIONS)
    if not fixture_hits:
        return _block(
            cfg.token("BLOCKED_FIXTURE_CAVEAT_MISSING"),
            f"required fixture caveats missing: {REQUIRED_FIXTURE_CAVEATS}",
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

    probe_results = tuple(
        _probe_row(p) for p in (blob.get("probe_results") or []) if isinstance(p, dict)
    )
    plan = tuple(_plan_row(p) for p in plan_raw if isinstance(p, dict))

    return Universal100DepthPromotionBatchStatus(
        decision=cfg.token("PASSED"),
        target_surface="Universal 100 Depth Promotion Batch",
        target_workflow=str(blob.get("target_workflow") or "universal 100 depth promotion batch"),
        batch_label=cfg.batch_label,
        batch_lock_id=cfg.batch_lock_id,
        cells_probed=_as_int(blob.get("cells_probed", 0)),
        cells_promoted=_as_int(blob.get("cells_promoted", len(promoted))),
        cells_blocked=_as_int(blob.get("cells_blocked", len(blocked))),
        release_supported=release_supported,
        user_ready_with_caveats=user_ready_with_caveats,
        families_improved=tuple(str(f) for f in (blob.get("families_improved") or [])),
        expected_sectors=cfg.expected_sectors,
        claim_state_counts={
            str(k): _as_int(v) for k, v in (blob.get("claim_state_counts") or {}).items()
        },
        support_state_counts={
            str(k): _as_int(v) for k, v in (blob.get("support_state_counts") or {}).items()
        },
        missing_rung_counts={
            str(k): _as_int(v) for k, v in (blob.get("missing_rung_counts") or {}).items()
        },
        promoted_cells=promoted,
        blocked_cells=blocked,
        probe_results=probe_results,
        depth_promotion_plan=plan,
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
        claim_boundary=tuple(str(x) for x in (blob.get("claim_boundary") or [])),
        forbidden_claims=tuple(str(x) for x in (blob.get("forbidden_claims") or [])),
        strongest_truthful_new_claim=str(blob.get("strongest_truthful_new_claim") or ""),
        evidence_ref=_relative_to_repo(chosen),
        captions=REQUIRED_PANEL_CAPTIONS,
        fixture_caveats_present=fixture_hits,
        current_next_rung=str(blob.get("next_recommended_rung") or ""),
        notes=(),
    )


def _relative_to_repo(path: Path) -> str:
    try:
        return path.resolve().relative_to(_REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def load_depth_promotion_batch_017(
    evidence_dir: Path | str | None = None,
) -> Universal100DepthPromotionBatchStatus:
    return load(evidence_dir, cfg=DEPTH_PROMOTION_BATCH_017)


def load_depth_promotion_batch_018(
    evidence_dir: Path | str | None = None,
) -> Universal100DepthPromotionBatchStatus:
    return load(evidence_dir, cfg=DEPTH_PROMOTION_BATCH_018)


def load_depth_promotion_batch_019(
    evidence_dir: Path | str | None = None,
) -> Universal100DepthPromotionBatchStatus:
    return load(evidence_dir, cfg=DEPTH_PROMOTION_BATCH_019)


__all__ = [
    "load",
    "load_depth_promotion_batch_017",
    "load_depth_promotion_batch_018",
    "load_depth_promotion_batch_019",
    "DEPTH_PROMOTION_BATCH_017",
    "DEPTH_PROMOTION_BATCH_018",
    "DEPTH_PROMOTION_BATCH_019",
    "REQUIRED_PANEL_CAPTIONS",
    "REQUIRED_FIXTURE_CAVEATS",
    "DepthPromotionCellRow",
    "DepthPromotionProbeRow",
    "DepthPromotionPlanRow",
    "Universal100DepthPromotionBatchStatus",
]
