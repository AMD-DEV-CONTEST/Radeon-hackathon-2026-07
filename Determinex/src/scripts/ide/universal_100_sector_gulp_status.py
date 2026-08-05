"""Universal 100 Sector Gulp status loader (parametrized for Batches 005, 006, …).

DETERMINEX_REACT_UNIVERSAL_100_SECTOR_GULP_BATCH_NNN_BINDING_LOCK_001.

load() reads the Codex sector gulp evidence (sector-conveyor era) and
returns a render-safe view-model the React Sector Gulp panel can
display. Each gulp batch covers one-to-many sectors; each cell carries
a tagged/classified/routed lifecycle plus its support state.

The panel DISPLAYS fixture-local probe evidence; it does NOT grant
authority. Fixture-local proof is NOT production readiness. Smoke-
supported is NOT release-supported. Fully supported with caveats is
NOT release-supported.

Hard rules enforced by load():

  * status != UNIVERSAL_100_SECTOR_GULP_BATCH_NNN_PASSED -> BLOCKED_MALFORMED
  * sectors_gulped missing or empty -> BLOCKED_MALFORMED
  * authority bag flag true -> BLOCKED_AUTHORITY_CONFUSION
  * broad_claims_granted true -> BLOCKED_BROAD_CLAIM
  * summary.release_supported > 0 without release-proof source path
    -> BLOCKED_RELEASE_OVERCLAIM
  * blocked_cells key absent (even when zero) -> BLOCKED_BLOCKED_CELLS_HIDDEN
  * required fixture-local caveat missing from claim_boundary/captions
    -> BLOCKED_FIXTURE_CAVEAT_MISSING
  * forbidden broad-claim phrase as current state outside refusal
    context -> BLOCKED_BROAD_CLAIM
  * promoted IMPLEMENTED claim with support_state < demo_proven
    -> BLOCKED_MALFORMED
  * any promoted cell that names FULLY_SUPPORTED_WITH_CAVEATS lifecycle
    state without naming user-ready/release-gate evidence path
    -> BLOCKED_RELEASE_OVERCLAIM
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


class _GulpConfig:
    """Per-batch sector-gulp configuration."""

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


GULP_BATCH_005 = _GulpConfig(
    batch_label="Batch 005",
    batch_lock_id="DETERMINEX_UNIVERSAL_100_SECTOR_GULP_BATCH_005_LOCK_001",
    evidence_dir_name="universal_100_sector_gulp_batch_005",
    expected_status="UNIVERSAL_100_SECTOR_GULP_BATCH_005_PASSED",
    decision_prefix="REACT_UNIVERSAL_100_SECTOR_GULP_BATCH_005_BINDING",
)
GULP_BATCH_006 = _GulpConfig(
    batch_label="Batch 006",
    batch_lock_id="DETERMINEX_UNIVERSAL_100_SECTOR_GULP_BATCH_006_LOCK_001",
    evidence_dir_name="universal_100_sector_gulp_batch_006",
    expected_status="UNIVERSAL_100_SECTOR_GULP_BATCH_006_PASSED",
    decision_prefix="REACT_UNIVERSAL_100_SECTOR_GULP_BATCH_006_BINDING",
)
GULP_BATCH_007 = _GulpConfig(
    batch_label="Batch 007",
    batch_lock_id="DETERMINEX_UNIVERSAL_100_SECTOR_GULP_BATCH_007_LOCK_001",
    evidence_dir_name="universal_100_sector_gulp_batch_007",
    expected_status="UNIVERSAL_100_SECTOR_GULP_BATCH_007_PASSED",
    decision_prefix="REACT_UNIVERSAL_100_SECTOR_GULP_BATCH_007_BINDING",
)
GULP_BATCH_008 = _GulpConfig(
    batch_label="Batch 008",
    batch_lock_id="DETERMINEX_UNIVERSAL_100_SECTOR_GULP_BATCH_008_LOCK_001",
    evidence_dir_name="universal_100_sector_gulp_batch_008",
    expected_status="UNIVERSAL_100_SECTOR_GULP_BATCH_008_PASSED",
    decision_prefix="REACT_UNIVERSAL_100_SECTOR_GULP_BATCH_008_BINDING",
)
GULP_BATCH_009 = _GulpConfig(
    batch_label="Batch 009",
    batch_lock_id="DETERMINEX_UNIVERSAL_100_SECTOR_GULP_BATCH_009_LOCK_001",
    evidence_dir_name="universal_100_sector_gulp_batch_009",
    expected_status="UNIVERSAL_100_SECTOR_GULP_BATCH_009_PASSED",
    decision_prefix="REACT_UNIVERSAL_100_SECTOR_GULP_BATCH_009_BINDING",
)
GULP_BATCH_010 = _GulpConfig(
    batch_label="Batch 010",
    batch_lock_id="DETERMINEX_UNIVERSAL_100_SECTOR_GULP_BATCH_010_LOCK_001",
    evidence_dir_name="universal_100_sector_gulp_batch_010",
    expected_status="UNIVERSAL_100_SECTOR_GULP_BATCH_010_PASSED",
    decision_prefix="REACT_UNIVERSAL_100_SECTOR_GULP_BATCH_010_BINDING",
)
GULP_BATCH_011 = _GulpConfig(
    batch_label="Batch 011",
    batch_lock_id="DETERMINEX_UNIVERSAL_100_SECTOR_GULP_BATCH_011_LOCK_001",
    evidence_dir_name="universal_100_sector_gulp_batch_011",
    expected_status="UNIVERSAL_100_SECTOR_GULP_BATCH_011_PASSED",
    decision_prefix="REACT_UNIVERSAL_100_SECTOR_GULP_BATCH_011_BINDING",
)
GULP_BATCH_012 = _GulpConfig(
    batch_label="Batch 012",
    batch_lock_id="DETERMINEX_UNIVERSAL_100_SECTOR_GULP_BATCH_012_LOCK_001",
    evidence_dir_name="universal_100_sector_gulp_batch_012",
    expected_status="UNIVERSAL_100_SECTOR_GULP_BATCH_012_PASSED",
    decision_prefix="REACT_UNIVERSAL_100_SECTOR_GULP_BATCH_012_BINDING",
)
GULP_BATCH_013 = _GulpConfig(
    batch_label="Batch 013",
    batch_lock_id="DETERMINEX_UNIVERSAL_100_SECTOR_GULP_BATCH_013_LOCK_001",
    evidence_dir_name="universal_100_sector_gulp_batch_013",
    expected_status="UNIVERSAL_100_SECTOR_GULP_BATCH_013_PASSED",
    decision_prefix="REACT_UNIVERSAL_100_SECTOR_GULP_BATCH_013_BINDING",
)


REQUIRED_PANEL_CAPTIONS = (
    "This panel displays evidence; it does not grant authority.",
    "Fixture-local proof is not production readiness.",
    "Smoke-supported is not release-supported.",
    "Fully supported with caveats is not release-supported.",
    "No source mutation without authority.",
    "No working-app claim without build/test/smoke evidence.",
    "Universal 100 means universal intake/routing, not magic execution.",
    "Blocked cells are visible by exact missing rung.",
)

REQUIRED_FIXTURE_CAVEATS = ("fixture-local",)

FORBIDDEN_BROAD_CLAIM_PHRASES = (
    "all apps supported",
    "all languages supported",
    "all platforms supported",
    "production-ready",
    "release ready: true",
    "release_ready: true",
    "training_eligible: true",
    "source_mutation_authorized: true",
    "approval_authority_granted: true",
    "broad_claims_granted: true",
    "universal execution",
    "magic generation",
)


@dataclass(frozen=True)
class GulpCellRow:
    cell_id: str
    sector_id: str
    claim_state: str
    support_state: str
    lifecycle_state: str
    workflow: str
    language: str
    app_class: str
    platform: str
    framework_runtime: str
    classification: str
    route: str
    verifier_oracle: str
    promoted: bool
    blocked: bool
    blocker: str
    missing_rung: str
    setup_caveats: tuple[str, ...]
    fixture_path: str
    fixture_workspace_hash: str


@dataclass(frozen=True)
class Universal100SectorGulpStatus:
    decision: str
    target_surface: str
    target_workflow: str
    batch_label: str
    batch_lock_id: str
    sectors_gulped: tuple[str, ...]
    cells_tagged: int
    cells_classified: int
    cells_routed: int
    cells_probed: int
    cells_promoted: int
    cells_blocked: int
    release_supported_count: int
    claim_state_counts: dict[str, int]
    support_state_counts: dict[str, int]
    lifecycle_state_counts: dict[str, int]
    blocker_counts: dict[str, int]
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
    promoted_cells: tuple[GulpCellRow, ...]
    blocked_cells: tuple[GulpCellRow, ...]
    claim_boundary: tuple[str, ...]
    forbidden_claims: tuple[str, ...]
    strongest_truthful_new_claim: str
    sector_readiness: tuple[dict[str, object], ...]
    sector_registry_ref: str
    sector_state_ladder_ref: str
    evidence_ref: str
    captions: tuple[str, ...]
    fixture_caveats_present: tuple[str, ...]
    current_next_rung: str
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["promoted_cells"] = [asdict(c) for c in self.promoted_cells]
        d["blocked_cells"] = [asdict(c) for c in self.blocked_cells]
        for k in (
            "sectors_gulped",
            "claim_boundary",
            "forbidden_claims",
            "captions",
            "fixture_caveats_present",
            "notes",
        ):
            d[k] = list(getattr(self, k))
        d["sector_readiness"] = [dict(r) for r in self.sector_readiness]
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


def _cell_row(cell: dict, *, promoted: bool, blocked: bool) -> GulpCellRow:
    return GulpCellRow(
        cell_id=str(cell.get("cell_id") or "(unknown)"),
        sector_id=str(cell.get("sector_id") or ""),
        claim_state=str(cell.get("claim_state") or "(unknown)"),
        support_state=str(cell.get("support_state") or "(unknown)"),
        lifecycle_state=str(cell.get("lifecycle_state") or ""),
        workflow=str(cell.get("workflow") or ""),
        language=str(cell.get("language") or ""),
        app_class=str(cell.get("app_class") or ""),
        platform=str(cell.get("platform") or ""),
        framework_runtime=str(cell.get("framework_runtime") or ""),
        classification=str(cell.get("classification") or ""),
        route=str(cell.get("route") or ""),
        verifier_oracle=str(cell.get("verifier_oracle") or ""),
        promoted=promoted,
        blocked=blocked,
        blocker=str(cell.get("blocker") or ""),
        missing_rung=str(cell.get("missing_rung") or ""),
        setup_caveats=tuple(str(x) for x in (cell.get("setup_caveats") or [])),
        fixture_path=str(cell.get("fixture_path") or ""),
        fixture_workspace_hash=str(cell.get("fixture_workspace_hash") or ""),
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
    *, decision: str, note: str, cfg: _GulpConfig = GULP_BATCH_005
) -> Universal100SectorGulpStatus:
    return Universal100SectorGulpStatus(
        decision=decision,
        target_surface="Universal 100 Sector Gulp",
        target_workflow="(awaiting evidence)" if "AWAITING" in decision else "(blocked)",
        batch_label=cfg.batch_label,
        batch_lock_id=cfg.batch_lock_id,
        sectors_gulped=tuple(),
        cells_tagged=0,
        cells_classified=0,
        cells_routed=0,
        cells_probed=0,
        cells_promoted=0,
        cells_blocked=0,
        release_supported_count=0,
        claim_state_counts={},
        support_state_counts={},
        lifecycle_state_counts={},
        blocker_counts={},
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
        promoted_cells=tuple(),
        blocked_cells=tuple(),
        claim_boundary=tuple(),
        forbidden_claims=tuple(),
        strongest_truthful_new_claim="(awaiting evidence)"
        if "AWAITING" in decision
        else "(blocked)",
        sector_readiness=tuple(),
        sector_registry_ref="",
        sector_state_ladder_ref="",
        evidence_ref="",
        captions=REQUIRED_PANEL_CAPTIONS,
        fixture_caveats_present=tuple(),
        current_next_rung="",
        notes=(note,),
    )


def _awaiting(note: str, cfg: _GulpConfig = GULP_BATCH_005) -> Universal100SectorGulpStatus:
    return _shell(decision=cfg.token("AWAITING_EVIDENCE"), note=note, cfg=cfg)


def _block(
    decision: str, note: str, cfg: _GulpConfig = GULP_BATCH_005
) -> Universal100SectorGulpStatus:
    return _shell(decision=decision, note=note, cfg=cfg)


def load(
    evidence_dir: Path | str | None = None,
    *,
    cfg: _GulpConfig = GULP_BATCH_005,
) -> Universal100SectorGulpStatus:
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

    sectors_raw = blob.get("sectors_gulped")
    if not isinstance(sectors_raw, list) or not sectors_raw:
        return _block(
            cfg.token("BLOCKED_MALFORMED"),
            "sectors_gulped missing or empty",
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

    summary = blob.get("summary") or {}
    if "cells_probed" not in summary:
        return _block(cfg.token("BLOCKED_MALFORMED"), "summary.cells_probed missing", cfg=cfg)

    blocked_raw = blob.get("blocked_cells")
    if blocked_raw is None:
        return _block(
            cfg.token("BLOCKED_BLOCKED_CELLS_HIDDEN"),
            "blocked_cells key absent — blocked cells must remain visible",
            cfg=cfg,
        )

    promoted_raw = blob.get("promoted_cells") or []
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
        # FULLY_SUPPORTED_WITH_CAVEATS lifecycle requires user-ready / release proof.
        if (
            row.lifecycle_state == "FULLY_SUPPORTED_WITH_CAVEATS"
            and not _has_release_proof_reference(blob)
        ):
            return _block(
                cfg.token("BLOCKED_RELEASE_OVERCLAIM"),
                f"promoted cell {row.cell_id} claims FULLY_SUPPORTED_WITH_CAVEATS without release-proof source path",
                cfg=cfg,
            )

    release_supported = int(summary.get("release_supported", 0))
    if release_supported > 0 and not _has_release_proof_reference(blob):
        return _block(
            cfg.token("BLOCKED_RELEASE_OVERCLAIM"),
            f"summary.release_supported={release_supported} without release-proof source path",
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

    cells_tagged = int(blob.get("cells_tagged", summary.get("cells_probed", 0)))
    cells_classified = int(blob.get("cells_classified", summary.get("cells_probed", 0)))
    cells_routed = int(blob.get("cells_routed", summary.get("cells_probed", 0)))

    sector_readiness = tuple(
        dict(r) for r in (blob.get("sector_readiness") or []) if isinstance(r, dict)
    )

    return Universal100SectorGulpStatus(
        decision=cfg.token("PASSED"),
        target_surface="Universal 100 Sector Gulp",
        target_workflow="sector gulp batch",
        batch_label=cfg.batch_label,
        batch_lock_id=cfg.batch_lock_id,
        sectors_gulped=tuple(str(s) for s in sectors_raw),
        cells_tagged=cells_tagged,
        cells_classified=cells_classified,
        cells_routed=cells_routed,
        cells_probed=int(summary.get("cells_probed", 0)),
        cells_promoted=int(summary.get("cells_promoted", len(promoted))),
        cells_blocked=int(summary.get("cells_blocked", len(blocked))),
        release_supported_count=release_supported,
        claim_state_counts={
            str(k): int(v) for k, v in (summary.get("claim_state_counts") or {}).items()
        },
        support_state_counts={
            str(k): int(v) for k, v in (summary.get("support_state_counts") or {}).items()
        },
        lifecycle_state_counts={
            str(k): int(v) for k, v in (summary.get("lifecycle_state_counts") or {}).items()
        },
        blocker_counts={str(k): int(v) for k, v in (summary.get("blocker_counts") or {}).items()},
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
        claim_boundary=tuple(str(x) for x in (blob.get("claim_boundary") or [])),
        forbidden_claims=tuple(str(x) for x in (blob.get("forbidden_claims") or [])),
        strongest_truthful_new_claim=str(blob.get("strongest_truthful_new_claim") or ""),
        sector_readiness=sector_readiness,
        sector_registry_ref=str(blob.get("sector_registry_ref") or ""),
        sector_state_ladder_ref=str(blob.get("sector_state_ladder_ref") or ""),
        evidence_ref=_relative_to_repo(chosen),
        captions=REQUIRED_PANEL_CAPTIONS,
        fixture_caveats_present=fixture_hits,
        current_next_rung=str(blob.get("next_recommended_rung") or ""),
        notes=(),
    )


def load_batch_005(evidence_dir: Path | str | None = None) -> Universal100SectorGulpStatus:
    return load(evidence_dir, cfg=GULP_BATCH_005)


def load_batch_006(evidence_dir: Path | str | None = None) -> Universal100SectorGulpStatus:
    return load(evidence_dir, cfg=GULP_BATCH_006)


def load_batch_007(evidence_dir: Path | str | None = None) -> Universal100SectorGulpStatus:
    return load(evidence_dir, cfg=GULP_BATCH_007)


def load_batch_008(evidence_dir: Path | str | None = None) -> Universal100SectorGulpStatus:
    return load(evidence_dir, cfg=GULP_BATCH_008)


def load_batch_009(evidence_dir: Path | str | None = None) -> Universal100SectorGulpStatus:
    return load(evidence_dir, cfg=GULP_BATCH_009)


def load_batch_010(evidence_dir: Path | str | None = None) -> Universal100SectorGulpStatus:
    return load(evidence_dir, cfg=GULP_BATCH_010)


def load_batch_011(evidence_dir: Path | str | None = None) -> Universal100SectorGulpStatus:
    return load(evidence_dir, cfg=GULP_BATCH_011)


def load_batch_012(evidence_dir: Path | str | None = None) -> Universal100SectorGulpStatus:
    return load(evidence_dir, cfg=GULP_BATCH_012)


def load_batch_013(evidence_dir: Path | str | None = None) -> Universal100SectorGulpStatus:
    return load(evidence_dir, cfg=GULP_BATCH_013)


def _relative_to_repo(path: Path) -> str:
    try:
        return path.resolve().relative_to(_REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


__all__ = [
    "load",
    "load_batch_005",
    "load_batch_006",
    "load_batch_007",
    "load_batch_008",
    "load_batch_009",
    "load_batch_010",
    "GULP_BATCH_005",
    "GULP_BATCH_006",
    "GULP_BATCH_007",
    "GULP_BATCH_008",
    "GULP_BATCH_009",
    "GULP_BATCH_010",
    "REQUIRED_PANEL_CAPTIONS",
    "REQUIRED_FIXTURE_CAVEATS",
    "GulpCellRow",
    "Universal100SectorGulpStatus",
]
