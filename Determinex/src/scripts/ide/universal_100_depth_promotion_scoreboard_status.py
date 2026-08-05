"""Universal 100 Depth Promotion Scoreboard status loader.

DETERMINEX_REACT_UNIVERSAL_100_DEPTH_PROMOTION_SCOREBOARD_BINDING_LOCK_001.

load() reads Codex's depth-promotion scoreboard evidence and returns
a render-safe view-model the React panel can display. The scoreboard
reports the post-wave state: 40-family Level 1 coverage, families with
any evidence before vs after the wave, families by highest support
depth, cells by support depth, release/user_ready aggregates, and
blockers remaining by category.

The panel DISPLAYS evidence; it does NOT grant authority. Coverage
reporting is routing/accounting, NOT promotion. Family evidence is
NOT full family support. Release-supported remains 0.

Hard rules enforced by load():

  * status != UNIVERSAL_100_DEPTH_PROMOTION_SCOREBOARD_PASSED ->
    BLOCKED_MALFORMED
  * authority bag flag true -> BLOCKED_AUTHORITY_CONFUSION
  * broad_claims_granted true -> BLOCKED_BROAD_CLAIM
  * families_total != 40 -> BLOCKED_TAXONOMY_OVERCLAIM
  * families_level_1_covered != families_total -> BLOCKED_LEVEL_1_NOT_40
  * release_supported_families > 0 or release_supported_cells > 0 without
    release-proof reference -> BLOCKED_RELEASE_OVERCLAIM
  * families_by_highest_support_depth absent -> BLOCKED_MALFORMED
  * cells_by_support_depth absent -> BLOCKED_MALFORMED
  * blockers_remaining_by_category absent -> BLOCKED_MALFORMED
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
    _has_release_proof_reference,
    _walk_strings_for_forbidden,
)

_REPO_ROOT = _HERE.parent.parent.parent
_EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "universal_100_depth_promotion_scoreboard"
EXPECTED_STATUS = "UNIVERSAL_100_DEPTH_PROMOTION_SCOREBOARD_PASSED"
LOCK_ID = "DETERMINEX_UNIVERSAL_100_DEPTH_PROMOTION_SCOREBOARD_LOCK_001"
EXPECTED_FAMILIES_TOTAL = 40

DECISION_PREFIX = "REACT_UNIVERSAL_100_DEPTH_PROMOTION_SCOREBOARD_BINDING"


def _token(suffix: str) -> str:
    return f"{DECISION_PREFIX}_{suffix}"


def _as_int(v) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


REQUIRED_PANEL_CAPTIONS = (
    "This panel displays evidence; it does not grant authority.",
    "Depth promotion raises proof depth; it does not create universal support.",
    "Coverage reporting is routing/accounting, not promotion.",
    "Determinex's roadmap is universal by intake, routing, blocker accounting, and proof discipline.",
    "Universal roadmap does not mean every edge case is supported today.",
    "Every edge case must be supported, blocked by exact missing rung, forbidden, or roadmap.",
    "Family evidence is not full family support.",
    "Scaffold-supported is not working-app proof.",
    "Build-supported is not release support.",
    "Smoke-supported is not production proof.",
    "User-ready-with-caveats is limited to exactly proven cells.",
    "Release-supported remains 0.",
    "Unknown/novel routing is not arbitrary app support.",
    "Roadmap-only families remain visible.",
    "Blockers remain visible by category.",
)


@dataclass(frozen=True)
class Universal100DepthPromotionScoreboardStatus:
    decision: str
    target_surface: str
    target_workflow: str
    lock_id: str
    families_total: int
    families_level_1_covered: int
    families_with_any_evidence_before: int
    families_with_any_evidence_after: int
    families_with_no_evidence_after: int
    families_by_highest_support_depth: dict[str, int]
    cells_by_support_depth: dict[str, int]
    release_supported_cells: int
    release_supported_families: int
    user_ready_with_caveats_cells: int
    user_ready_with_caveats_families: int
    packaging_supported_cells: int
    packaging_supported_families: int
    fresh_install_verified_cells: int
    fresh_install_verified_families: int
    blockers_remaining_by_category: dict[str, int]
    families_improved_this_wave: tuple[str, ...]
    next_depth_promotion_queue: tuple[str, ...]
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
    source_records: tuple[str, ...]
    evidence_ref: str
    captions: tuple[str, ...]
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        for k in (
            "families_improved_this_wave",
            "next_depth_promotion_queue",
            "claim_boundary",
            "forbidden_claims",
            "source_records",
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


def _shell(*, decision: str, note: str) -> Universal100DepthPromotionScoreboardStatus:
    return Universal100DepthPromotionScoreboardStatus(
        decision=decision,
        target_surface="Universal 100 Depth Promotion Scoreboard",
        target_workflow="(awaiting evidence)" if "AWAITING" in decision else "(blocked)",
        lock_id=LOCK_ID,
        families_total=0,
        families_level_1_covered=0,
        families_with_any_evidence_before=0,
        families_with_any_evidence_after=0,
        families_with_no_evidence_after=0,
        families_by_highest_support_depth={},
        cells_by_support_depth={},
        release_supported_cells=0,
        release_supported_families=0,
        user_ready_with_caveats_cells=0,
        user_ready_with_caveats_families=0,
        packaging_supported_cells=0,
        packaging_supported_families=0,
        fresh_install_verified_cells=0,
        fresh_install_verified_families=0,
        blockers_remaining_by_category={},
        families_improved_this_wave=(),
        next_depth_promotion_queue=(),
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
        source_records=(),
        evidence_ref="",
        captions=REQUIRED_PANEL_CAPTIONS,
        notes=(note,),
    )


def _awaiting(note: str) -> Universal100DepthPromotionScoreboardStatus:
    return _shell(decision=_token("AWAITING_EVIDENCE"), note=note)


def _block(decision: str, note: str) -> Universal100DepthPromotionScoreboardStatus:
    return _shell(decision=decision, note=note)


def load(
    evidence_dir: Path | str | None = None,
) -> Universal100DepthPromotionScoreboardStatus:
    ed = Path(evidence_dir) if evidence_dir else _EVIDENCE_DIR
    chosen = _locate_latest_evidence(ed)
    if chosen is None:
        return _awaiting(f"no evidence file under {ed}")
    try:
        blob = json.loads(chosen.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return _awaiting(f"could not read evidence: {exc}")

    if blob.get("status") != EXPECTED_STATUS:
        return _block(
            _token("BLOCKED_MALFORMED"),
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
                _token("BLOCKED_AUTHORITY_CONFUSION"),
                f"authority flag {flag} is true",
            )
    if _auth("broad_claims_granted"):
        return _block(
            _token("BLOCKED_BROAD_CLAIM"),
            "broad_claims_granted is true",
        )

    families_total = _as_int(blob.get("families_total", 0))
    if families_total != EXPECTED_FAMILIES_TOTAL:
        return _block(
            _token("BLOCKED_TAXONOMY_OVERCLAIM"),
            f"families_total={families_total} (expected {EXPECTED_FAMILIES_TOTAL})",
        )

    families_level_1 = _as_int(blob.get("families_level_1_covered", 0))
    if families_level_1 != families_total:
        return _block(
            _token("BLOCKED_LEVEL_1_NOT_40"),
            f"families_level_1_covered={families_level_1} != families_total={families_total}",
        )

    release_supported_families = _as_int(blob.get("release_supported_families", 0))
    release_supported_cells = _as_int(blob.get("release_supported_cells", 0))
    if (
        release_supported_families > 0 or release_supported_cells > 0
    ) and not _has_release_proof_reference(blob):
        return _block(
            _token("BLOCKED_RELEASE_OVERCLAIM"),
            f"release_supported_families={release_supported_families} / "
            f"release_supported_cells={release_supported_cells} without release-proof reference",
        )

    families_by_depth_raw = blob.get("families_by_highest_support_depth")
    if not isinstance(families_by_depth_raw, dict):
        return _block(_token("BLOCKED_MALFORMED"), "families_by_highest_support_depth absent")
    cells_by_depth_raw = blob.get("cells_by_support_depth")
    if not isinstance(cells_by_depth_raw, dict):
        return _block(_token("BLOCKED_MALFORMED"), "cells_by_support_depth absent")
    blockers_by_cat_raw = blob.get("blockers_remaining_by_category")
    if not isinstance(blockers_by_cat_raw, dict):
        return _block(_token("BLOCKED_MALFORMED"), "blockers_remaining_by_category absent")

    hits: set[str] = set()
    _walk_strings_for_forbidden(blob, hits)
    if hits:
        return _block(
            _token("BLOCKED_BROAD_CLAIM"),
            f"forbidden broad-claim phrases: {sorted(hits)}",
        )

    return Universal100DepthPromotionScoreboardStatus(
        decision=_token("PASSED"),
        target_surface="Universal 100 Depth Promotion Scoreboard",
        target_workflow=str(
            blob.get("target_workflow") or "universal 100 depth promotion scoreboard"
        ),
        lock_id=LOCK_ID,
        families_total=families_total,
        families_level_1_covered=families_level_1,
        families_with_any_evidence_before=_as_int(blob.get("families_with_any_evidence_before", 0)),
        families_with_any_evidence_after=_as_int(blob.get("families_with_any_evidence_after", 0)),
        families_with_no_evidence_after=_as_int(blob.get("families_with_no_evidence_after", 0)),
        families_by_highest_support_depth={
            str(k): _as_int(v) for k, v in families_by_depth_raw.items()
        },
        cells_by_support_depth={str(k): _as_int(v) for k, v in cells_by_depth_raw.items()},
        release_supported_cells=release_supported_cells,
        release_supported_families=release_supported_families,
        user_ready_with_caveats_cells=_as_int(blob.get("user_ready_with_caveats_cells", 0)),
        user_ready_with_caveats_families=_as_int(blob.get("user_ready_with_caveats_families", 0)),
        packaging_supported_cells=_as_int(blob.get("packaging_supported_cells", 0)),
        packaging_supported_families=_as_int(blob.get("packaging_supported_families", 0)),
        fresh_install_verified_cells=_as_int(blob.get("fresh_install_verified_cells", 0)),
        fresh_install_verified_families=_as_int(blob.get("fresh_install_verified_families", 0)),
        blockers_remaining_by_category={str(k): _as_int(v) for k, v in blockers_by_cat_raw.items()},
        families_improved_this_wave=tuple(
            str(x) for x in (blob.get("families_improved_this_wave") or [])
        ),
        next_depth_promotion_queue=tuple(
            str(x) for x in (blob.get("next_depth_promotion_queue") or [])
        ),
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
        source_records=tuple(str(s) for s in (blob.get("source_records") or [])),
        evidence_ref=_relative_to_repo(chosen),
        captions=REQUIRED_PANEL_CAPTIONS,
        notes=(),
    )


def _relative_to_repo(path: Path) -> str:
    try:
        return path.resolve().relative_to(_REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


__all__ = [
    "load",
    "Universal100DepthPromotionScoreboardStatus",
    "REQUIRED_PANEL_CAPTIONS",
    "EXPECTED_STATUS",
    "LOCK_ID",
    "EXPECTED_FAMILIES_TOTAL",
]
