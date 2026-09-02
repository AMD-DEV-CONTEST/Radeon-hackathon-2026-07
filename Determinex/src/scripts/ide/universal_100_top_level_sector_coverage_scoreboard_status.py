"""Universal 100 Top-Level Sector Coverage Scoreboard status loader.

DETERMINEX_REACT_UNIVERSAL_100_TOP_LEVEL_SECTOR_COVERAGE_SCOREBOARD_BINDING_LOCK_001.

load() reads Codex's coverage-scoreboard evidence and returns a render-
safe view-model the React panel can display. The scoreboard reports
families_total / families_level_1_covered / families with each depth of
support (build / scaffold / smoke / test / repair / maintain / teach /
packaging / fresh_install / release / user_ready_with_caveats), the
remaining blockers by category, and the next top-level targets.

The panel DISPLAYS evidence; it does NOT grant authority. Coverage
reporting is routing/accounting, not promotion. Level 1 coverage is
identification/classification/routing, NOT universal execution. 40/40
routed does NOT mean 40/40 supported.

Hard rules enforced by load():

  * status != UNIVERSAL_100_TOP_LEVEL_SECTOR_COVERAGE_SCOREBOARD_PASSED
    -> BLOCKED_MALFORMED
  * authority bag flag true -> BLOCKED_AUTHORITY_CONFUSION
  * broad_claims_granted true -> BLOCKED_BROAD_CLAIM
  * families_total != 40 -> BLOCKED_TAXONOMY_OVERCLAIM
  * families_level_1_covered != families_total -> BLOCKED_LEVEL_1_NOT_40
  * families_with_release_supported > 0 without release-proof reference
    -> BLOCKED_RELEASE_OVERCLAIM
  * release_supported_count > 0 without release-proof reference ->
    BLOCKED_RELEASE_OVERCLAIM
  * blockers_remaining_by_category absent -> BLOCKED_MALFORMED
  * support_depth_counts absent -> BLOCKED_MALFORMED
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
_EVIDENCE_DIR = (
    _REPO_ROOT / "assurance" / "evidence" / "universal_100_top_level_sector_coverage_scoreboard"
)
EXPECTED_STATUS = "UNIVERSAL_100_TOP_LEVEL_SECTOR_COVERAGE_SCOREBOARD_PASSED"
LOCK_ID = "DETERMINEX_UNIVERSAL_100_TOP_LEVEL_SECTOR_COVERAGE_SCOREBOARD_LOCK_001"
EXPECTED_FAMILIES_TOTAL = 40

DECISION_PREFIX = "REACT_UNIVERSAL_100_TOP_LEVEL_SECTOR_COVERAGE_SCOREBOARD_BINDING"


def _token(suffix: str) -> str:
    return f"{DECISION_PREFIX}_{suffix}"


REQUIRED_PANEL_CAPTIONS = (
    "This panel displays evidence; it does not grant authority.",
    "Coverage reporting is routing/accounting, not promotion.",
    "Universal 100 Level 1 means top-level identification/classification/"
    "routing, not universal execution.",
    "40 / 40 routed does not mean 40 / 40 supported.",
    "Scaffold-supported is not working-app proof.",
    "Smoke-supported is not production proof.",
    "Build-supported is not test-supported.",
    "Release-supported remains 0.",
    "Roadmap-only families remain visible.",
    "Blockers remain visible by category.",
    "No source mutation without authority.",
)


@dataclass(frozen=True)
class Universal100TopLevelSectorCoverageScoreboardStatus:
    decision: str
    target_surface: str
    target_workflow: str
    lock_id: str
    families_total: int
    families_level_1_covered: int
    families_with_any_evidence: int
    families_with_build_support: int
    families_with_scaffold_support: int
    families_with_smoke_support: int
    families_with_test_support: int
    families_with_repair_support: int
    families_with_maintain_support: int
    families_with_teach_support: int
    families_with_packaging_supported: int
    families_with_fresh_install_verified: int
    families_with_release_supported: int
    families_with_user_ready_with_caveats: int
    release_supported_count: int
    user_ready_with_caveats_count: int
    roadmap_only_families_remaining: int
    support_depth_counts: dict[str, int]
    blockers_remaining_by_category: dict[str, int]
    blockers_closed_this_wave: tuple[str, ...]
    blockers_partially_closed_this_wave: tuple[str, ...]
    blockers_converted_to_operator_action: tuple[str, ...]
    next_top_level_targets: tuple[str, ...]
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
            "blockers_closed_this_wave",
            "blockers_partially_closed_this_wave",
            "blockers_converted_to_operator_action",
            "next_top_level_targets",
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


def _shell(*, decision: str, note: str) -> Universal100TopLevelSectorCoverageScoreboardStatus:
    return Universal100TopLevelSectorCoverageScoreboardStatus(
        decision=decision,
        target_surface="Universal 100 Top-Level Sector Coverage Scoreboard",
        target_workflow="(awaiting evidence)" if "AWAITING" in decision else "(blocked)",
        lock_id=LOCK_ID,
        families_total=0,
        families_level_1_covered=0,
        families_with_any_evidence=0,
        families_with_build_support=0,
        families_with_scaffold_support=0,
        families_with_smoke_support=0,
        families_with_test_support=0,
        families_with_repair_support=0,
        families_with_maintain_support=0,
        families_with_teach_support=0,
        families_with_packaging_supported=0,
        families_with_fresh_install_verified=0,
        families_with_release_supported=0,
        families_with_user_ready_with_caveats=0,
        release_supported_count=0,
        user_ready_with_caveats_count=0,
        roadmap_only_families_remaining=0,
        support_depth_counts={},
        blockers_remaining_by_category={},
        blockers_closed_this_wave=(),
        blockers_partially_closed_this_wave=(),
        blockers_converted_to_operator_action=(),
        next_top_level_targets=(),
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


def _awaiting(note: str) -> Universal100TopLevelSectorCoverageScoreboardStatus:
    return _shell(decision=_token("AWAITING_EVIDENCE"), note=note)


def _block(decision: str, note: str) -> Universal100TopLevelSectorCoverageScoreboardStatus:
    return _shell(decision=decision, note=note)


def load(
    evidence_dir: Path | str | None = None,
) -> Universal100TopLevelSectorCoverageScoreboardStatus:
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

    families_total = int(blob.get("families_total", 0))
    if families_total != EXPECTED_FAMILIES_TOTAL:
        return _block(
            _token("BLOCKED_TAXONOMY_OVERCLAIM"),
            f"families_total={families_total} (expected {EXPECTED_FAMILIES_TOTAL})",
        )

    families_level_1 = int(blob.get("families_level_1_covered", 0))
    if families_level_1 != families_total:
        return _block(
            _token("BLOCKED_LEVEL_1_NOT_40"),
            f"families_level_1_covered={families_level_1} != families_total={families_total}",
        )

    families_with_release = int(blob.get("families_with_release_supported", 0))
    if families_with_release > 0 and not _has_release_proof_reference(blob):
        return _block(
            _token("BLOCKED_RELEASE_OVERCLAIM"),
            f"families_with_release_supported={families_with_release} without release-proof source path",
        )
    release_supported_count = int(blob.get("release_supported_count", 0))
    if release_supported_count > 0 and not _has_release_proof_reference(blob):
        return _block(
            _token("BLOCKED_RELEASE_OVERCLAIM"),
            f"release_supported_count={release_supported_count} without release-proof source path",
        )

    blockers_remaining_by_category = blob.get("blockers_remaining_by_category")
    if not isinstance(blockers_remaining_by_category, dict):
        return _block(
            _token("BLOCKED_MALFORMED"),
            "blockers_remaining_by_category absent",
        )
    support_depth_counts = blob.get("support_depth_counts")
    if not isinstance(support_depth_counts, dict):
        return _block(
            _token("BLOCKED_MALFORMED"),
            "support_depth_counts absent",
        )

    hits: set[str] = set()
    _walk_strings_for_forbidden(blob, hits)
    if hits:
        return _block(
            _token("BLOCKED_BROAD_CLAIM"),
            f"forbidden broad-claim phrases: {sorted(hits)}",
        )

    return Universal100TopLevelSectorCoverageScoreboardStatus(
        decision=_token("PASSED"),
        target_surface="Universal 100 Top-Level Sector Coverage Scoreboard",
        target_workflow=str(
            blob.get("target_workflow")
            or "universal 100 top-level sector coverage scoreboard update"
        ),
        lock_id=LOCK_ID,
        families_total=families_total,
        families_level_1_covered=families_level_1,
        families_with_any_evidence=int(blob.get("families_with_any_evidence", 0)),
        families_with_build_support=int(blob.get("families_with_build_support", 0)),
        families_with_scaffold_support=int(blob.get("families_with_scaffold_support", 0)),
        families_with_smoke_support=int(blob.get("families_with_smoke_support", 0)),
        families_with_test_support=int(blob.get("families_with_test_support", 0)),
        families_with_repair_support=int(blob.get("families_with_repair_support", 0)),
        families_with_maintain_support=int(blob.get("families_with_maintain_support", 0)),
        families_with_teach_support=int(blob.get("families_with_teach_support", 0)),
        families_with_packaging_supported=int(blob.get("families_with_packaging_supported", 0)),
        families_with_fresh_install_verified=int(
            blob.get("families_with_fresh_install_verified", 0)
        ),
        families_with_release_supported=families_with_release,
        families_with_user_ready_with_caveats=int(
            blob.get("families_with_user_ready_with_caveats", 0)
        ),
        release_supported_count=release_supported_count,
        user_ready_with_caveats_count=int(blob.get("user_ready_with_caveats_count", 0)),
        roadmap_only_families_remaining=int(blob.get("roadmap_only_families_remaining", 0)),
        support_depth_counts={str(k): int(v) for k, v in support_depth_counts.items()},
        blockers_remaining_by_category={
            str(k): int(v) for k, v in blockers_remaining_by_category.items()
        },
        blockers_closed_this_wave=tuple(
            str(x) for x in (blob.get("blockers_closed_this_wave") or [])
        ),
        blockers_partially_closed_this_wave=tuple(
            str(x) for x in (blob.get("blockers_partially_closed_this_wave") or [])
        ),
        blockers_converted_to_operator_action=tuple(
            str(x) for x in (blob.get("blockers_converted_to_operator_action") or [])
        ),
        next_top_level_targets=tuple(str(x) for x in (blob.get("next_top_level_targets") or [])),
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


REACT_UNIVERSAL_100_TOP_LEVEL_SECTOR_COVERAGE_SCOREBOARD_BINDING_STATUS_TOKENS = tuple(
    _token(suffix)
    for suffix in (
        "PASSED",
        "AWAITING_EVIDENCE",
        "BLOCKED_MALFORMED",
        "BLOCKED_AUTHORITY_CONFUSION",
        "BLOCKED_BROAD_CLAIM",
        "BLOCKED_RELEASE_OVERCLAIM",
        "BLOCKED_TAXONOMY_OVERCLAIM",
        "BLOCKED_LEVEL_1_NOT_40",
    )
)


__all__ = [
    "load",
    "Universal100TopLevelSectorCoverageScoreboardStatus",
    "REQUIRED_PANEL_CAPTIONS",
    "EXPECTED_STATUS",
    "LOCK_ID",
    "EXPECTED_FAMILIES_TOTAL",
    "REACT_UNIVERSAL_100_TOP_LEVEL_SECTOR_COVERAGE_SCOREBOARD_BINDING_STATUS_TOKENS",
]
