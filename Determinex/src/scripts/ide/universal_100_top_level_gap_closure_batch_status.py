"""Universal 100 Top-Level Gap Closure Batch status loader (014/015/016).

DETERMINEX_REACT_UNIVERSAL_100_TOP_LEVEL_GAP_CLOSURE_BATCH_NNN_BINDING_LOCK_001.

load() reads Codex's gap-closure batch evidence and returns a render-safe
view-model the React panel can display. Gap-closure batches differ from
the regular sector gulps: they target the inventoried blockers (one
batch per family-cluster), drive probes against them, and record which
blockers were closed / partially closed / remain.

The panel DISPLAYS evidence; it does NOT grant authority. Fixture-local
gap-closure proof is NOT production readiness. Partially-closed blocker
proof is NOT full closure. Operator-action conversion is NOT closure.

Hard rules enforced by load():

  * status != UNIVERSAL_100_TOP_LEVEL_GAP_CLOSURE_BATCH_NNN_PASSED ->
    BLOCKED_MALFORMED
  * authority bag flag true -> BLOCKED_AUTHORITY_CONFUSION
  * broad_claims_granted true -> BLOCKED_BROAD_CLAIM
  * release_supported > 0 without release-proof reference ->
    BLOCKED_RELEASE_OVERCLAIM
  * user_ready_with_caveats > 0 without user-ready proof reference ->
    BLOCKED_USER_READY_OVERCLAIM
  * blocked_cells key absent -> BLOCKED_BLOCKED_CELLS_HIDDEN
  * promoted_cells key absent -> BLOCKED_MALFORMED
  * blockers_attempted / blockers_closed / blockers_partially_closed /
    blockers_remaining keys absent -> BLOCKED_MALFORMED
  * promoted cell with unknown support_state -> BLOCKED_MALFORMED
  * promoted cell IMPLEMENTED claim but support_state < demo_proven ->
    BLOCKED_MALFORMED (claim_state IMPLEMENTED_WITH_CAVEATS / PARTIAL is
    allowed at lower rungs because gap closure is bounded probe proof)
  * fixture-local caveat missing from claim_boundary / forbidden_claims /
    captions -> BLOCKED_FIXTURE_CAVEAT_MISSING
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


class _GapClosureBatchConfig:
    """Per-batch configuration for the gap-closure batch loader."""

    def __init__(
        self,
        *,
        batch_label: str,
        batch_lock_id: str,
        evidence_dir_name: str,
        expected_status: str,
        decision_prefix: str,
    ) -> None:
        self.batch_label = batch_label
        self.batch_lock_id = batch_lock_id
        self.evidence_dir_name = evidence_dir_name
        self.expected_status = expected_status
        self.decision_prefix = decision_prefix

    @property
    def evidence_dir(self) -> Path:
        return _REPO_ROOT / "assurance" / "evidence" / self.evidence_dir_name

    def token(self, suffix: str) -> str:
        return f"{self.decision_prefix}_{suffix}"


GAP_CLOSURE_BATCH_014 = _GapClosureBatchConfig(
    batch_label="Gap-Closure Batch 014",
    batch_lock_id="DETERMINEX_UNIVERSAL_100_TOP_LEVEL_GAP_CLOSURE_BATCH_014_LOCK_001",
    evidence_dir_name="universal_100_top_level_gap_closure_batch_014",
    expected_status="UNIVERSAL_100_TOP_LEVEL_GAP_CLOSURE_BATCH_014_PASSED",
    decision_prefix="REACT_UNIVERSAL_100_TOP_LEVEL_GAP_CLOSURE_BATCH_014_BINDING",
)
GAP_CLOSURE_BATCH_015 = _GapClosureBatchConfig(
    batch_label="Gap-Closure Batch 015",
    batch_lock_id="DETERMINEX_UNIVERSAL_100_TOP_LEVEL_GAP_CLOSURE_BATCH_015_LOCK_001",
    evidence_dir_name="universal_100_top_level_gap_closure_batch_015",
    expected_status="UNIVERSAL_100_TOP_LEVEL_GAP_CLOSURE_BATCH_015_PASSED",
    decision_prefix="REACT_UNIVERSAL_100_TOP_LEVEL_GAP_CLOSURE_BATCH_015_BINDING",
)
GAP_CLOSURE_BATCH_016 = _GapClosureBatchConfig(
    batch_label="Gap-Closure Batch 016",
    batch_lock_id="DETERMINEX_UNIVERSAL_100_TOP_LEVEL_GAP_CLOSURE_BATCH_016_LOCK_001",
    evidence_dir_name="universal_100_top_level_gap_closure_batch_016",
    expected_status="UNIVERSAL_100_TOP_LEVEL_GAP_CLOSURE_BATCH_016_PASSED",
    decision_prefix="REACT_UNIVERSAL_100_TOP_LEVEL_GAP_CLOSURE_BATCH_016_BINDING",
)


REQUIRED_PANEL_CAPTIONS = (
    "This panel displays evidence; it does not grant authority.",
    "Gap closure is bounded fixture-local probe proof.",
    "Partially-closed blocker proof is not full closure.",
    "Operator-action conversion is not closure.",
    "Fixture-local proof is not production readiness.",
    "Scaffold-supported is not working-app proof.",
    "Build-supported is not test-supported.",
    "Universal 100 means routing/accounting, not universal execution.",
    "No release claim without release proof.",
    "Blocked cells remain visible by exact missing rung.",
    "No source mutation without authority.",
)

REQUIRED_FIXTURE_CAVEATS = ("fixture-local",)


@dataclass(frozen=True)
class GapClosureCellRow:
    cell_id: str
    sector_id: str
    family: str
    blocker_id: str
    blocker_status: str
    category: str
    claim_state: str
    support_state: str
    claim_boundary: str
    missing_rung: str
    local_resolvability: str
    setup_caveats: tuple[str, ...]
    fixture_path: str
    fixture_workspace_hash: str
    evidence_paths: tuple[str, ...]
    promoted: bool
    blocked: bool


@dataclass(frozen=True)
class GapClosureProbeRow:
    blocker_id: str
    probe_id: str
    outcome: str
    note: str


@dataclass(frozen=True)
class Universal100TopLevelGapClosureBatchStatus:
    decision: str
    target_surface: str
    target_workflow: str
    batch_label: str
    batch_lock_id: str
    cells_promoted: int
    cells_blocked: int
    release_supported: int
    user_ready_with_caveats: int
    claim_state_counts: dict[str, int]
    support_state_counts: dict[str, int]
    missing_rung_counts: dict[str, int]
    blockers_attempted: tuple[str, ...]
    blockers_closed: tuple[str, ...]
    blockers_partially_closed: tuple[str, ...]
    blockers_remaining: tuple[str, ...]
    promoted_cells: tuple[GapClosureCellRow, ...]
    blocked_cells: tuple[GapClosureCellRow, ...]
    probe_results: tuple[GapClosureProbeRow, ...]
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
        for k in (
            "blockers_attempted",
            "blockers_closed",
            "blockers_partially_closed",
            "blockers_remaining",
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


def _cell_row(cell: dict, *, promoted: bool, blocked: bool) -> GapClosureCellRow:
    return GapClosureCellRow(
        cell_id=str(cell.get("cell_id") or "(unknown)"),
        sector_id=str(cell.get("sector_id") or ""),
        family=str(cell.get("family") or ""),
        blocker_id=str(cell.get("blocker_id") or ""),
        blocker_status=str(cell.get("blocker_status") or ""),
        category=str(cell.get("category") or ""),
        claim_state=str(cell.get("claim_state") or "(unknown)"),
        support_state=str(cell.get("support_state") or "(unknown)"),
        claim_boundary=str(cell.get("claim_boundary") or ""),
        missing_rung=str(cell.get("missing_rung") or ""),
        local_resolvability=str(cell.get("local_resolvability") or ""),
        setup_caveats=tuple(str(x) for x in (cell.get("setup_caveats") or [])),
        fixture_path=str(cell.get("fixture_path") or ""),
        fixture_workspace_hash=str(cell.get("fixture_workspace_hash") or ""),
        evidence_paths=tuple(str(p) for p in (cell.get("evidence_paths") or [])),
        promoted=promoted,
        blocked=blocked,
    )


def _probe_row(p: dict) -> GapClosureProbeRow:
    return GapClosureProbeRow(
        blocker_id=str(p.get("blocker_id") or ""),
        probe_id=str(p.get("probe_id") or p.get("name") or ""),
        outcome=str(p.get("outcome") or p.get("result") or ""),
        note=str(p.get("note") or p.get("message") or ""),
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
    cfg: _GapClosureBatchConfig = GAP_CLOSURE_BATCH_014,
) -> Universal100TopLevelGapClosureBatchStatus:
    return Universal100TopLevelGapClosureBatchStatus(
        decision=decision,
        target_surface="Universal 100 Top-Level Gap Closure Batch",
        target_workflow="(awaiting evidence)" if "AWAITING" in decision else "(blocked)",
        batch_label=cfg.batch_label,
        batch_lock_id=cfg.batch_lock_id,
        cells_promoted=0,
        cells_blocked=0,
        release_supported=0,
        user_ready_with_caveats=0,
        claim_state_counts={},
        support_state_counts={},
        missing_rung_counts={},
        blockers_attempted=(),
        blockers_closed=(),
        blockers_partially_closed=(),
        blockers_remaining=(),
        promoted_cells=(),
        blocked_cells=(),
        probe_results=(),
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
    note: str, cfg: _GapClosureBatchConfig = GAP_CLOSURE_BATCH_014
) -> Universal100TopLevelGapClosureBatchStatus:
    return _shell(decision=cfg.token("AWAITING_EVIDENCE"), note=note, cfg=cfg)


def _block(
    decision: str, note: str, cfg: _GapClosureBatchConfig = GAP_CLOSURE_BATCH_014
) -> Universal100TopLevelGapClosureBatchStatus:
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
    cfg: _GapClosureBatchConfig = GAP_CLOSURE_BATCH_014,
) -> Universal100TopLevelGapClosureBatchStatus:
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

    for k in (
        "blockers_attempted",
        "blockers_closed",
        "blockers_partially_closed",
        "blockers_remaining",
    ):
        if k not in blob:
            return _block(
                cfg.token("BLOCKED_MALFORMED"),
                f"{k} key absent",
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

    release_supported = int(blob.get("release_supported", 0))
    if release_supported > 0 and not _has_release_proof_reference(blob):
        return _block(
            cfg.token("BLOCKED_RELEASE_OVERCLAIM"),
            f"release_supported={release_supported} without release-proof source path",
            cfg=cfg,
        )

    user_ready_with_caveats = int(blob.get("user_ready_with_caveats", 0))
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

    return Universal100TopLevelGapClosureBatchStatus(
        decision=cfg.token("PASSED"),
        target_surface="Universal 100 Top-Level Gap Closure Batch",
        target_workflow=str(
            blob.get("target_workflow") or "universal 100 top-level gap closure batch"
        ),
        batch_label=cfg.batch_label,
        batch_lock_id=cfg.batch_lock_id,
        cells_promoted=int(blob.get("cells_promoted", len(promoted))),
        cells_blocked=int(blob.get("cells_blocked", len(blocked))),
        release_supported=release_supported,
        user_ready_with_caveats=user_ready_with_caveats,
        claim_state_counts={
            str(k): int(v) for k, v in (blob.get("claim_state_counts") or {}).items()
        },
        support_state_counts={
            str(k): int(v) for k, v in (blob.get("support_state_counts") or {}).items()
        },
        missing_rung_counts={
            str(k): int(v) for k, v in (blob.get("missing_rung_counts") or {}).items()
        },
        blockers_attempted=tuple(str(b) for b in (blob.get("blockers_attempted") or [])),
        blockers_closed=tuple(str(b) for b in (blob.get("blockers_closed") or [])),
        blockers_partially_closed=tuple(
            str(b) for b in (blob.get("blockers_partially_closed") or [])
        ),
        blockers_remaining=tuple(str(b) for b in (blob.get("blockers_remaining") or [])),
        promoted_cells=promoted,
        blocked_cells=blocked,
        probe_results=probe_results,
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


def load_gap_closure_batch_014(
    evidence_dir: Path | str | None = None,
) -> Universal100TopLevelGapClosureBatchStatus:
    return load(evidence_dir, cfg=GAP_CLOSURE_BATCH_014)


def load_gap_closure_batch_015(
    evidence_dir: Path | str | None = None,
) -> Universal100TopLevelGapClosureBatchStatus:
    return load(evidence_dir, cfg=GAP_CLOSURE_BATCH_015)


def load_gap_closure_batch_016(
    evidence_dir: Path | str | None = None,
) -> Universal100TopLevelGapClosureBatchStatus:
    return load(evidence_dir, cfg=GAP_CLOSURE_BATCH_016)


__all__ = [
    "load",
    "load_gap_closure_batch_014",
    "load_gap_closure_batch_015",
    "load_gap_closure_batch_016",
    "GAP_CLOSURE_BATCH_014",
    "GAP_CLOSURE_BATCH_015",
    "GAP_CLOSURE_BATCH_016",
    "REQUIRED_PANEL_CAPTIONS",
    "REQUIRED_FIXTURE_CAVEATS",
    "GapClosureCellRow",
    "GapClosureProbeRow",
    "Universal100TopLevelGapClosureBatchStatus",
]
