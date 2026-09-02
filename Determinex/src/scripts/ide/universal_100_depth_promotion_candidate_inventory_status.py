"""Universal 100 Depth Promotion Candidate Inventory status loader.

DETERMINEX_REACT_UNIVERSAL_100_DEPTH_PROMOTION_CANDIDATE_INVENTORY_BINDING_LOCK_001.

load() reads Codex's depth-promotion candidate inventory and returns a
render-safe view-model the React panel can display. The inventory lists
all 40 top-level sector families, each annotated with current highest
support depth, whether any cell evidence exists, the easiest next rung
toward promotion, the missing dependency/rung blocking promotion, and
whether local safe proof can be attempted now.

The panel DISPLAYS evidence; it does NOT grant authority. The inventory
classifies candidates and easiest-next rungs only; it does NOT promote
support and it does NOT remove forbidden shortcuts. Universal roadmap
means routing/intake/proof discipline, NOT current blanket support.

Hard rules enforced by load():

  * status != UNIVERSAL_100_DEPTH_PROMOTION_CANDIDATE_INVENTORY_PASSED ->
    BLOCKED_MALFORMED
  * authority bag flag true -> BLOCKED_AUTHORITY_CONFUSION
  * broad_claims_granted true -> BLOCKED_BROAD_CLAIM
  * family_count != 40 -> BLOCKED_TAXONOMY_OVERCLAIM
  * candidates list absent or length != family_count ->
    BLOCKED_MALFORMED
  * candidate missing sector_id / sector_family /
    current_highest_support_depth / easiest_next_rung /
    missing_dependency_or_rung -> BLOCKED_MALFORMED
  * batch_targets dict missing 017/018/019 -> BLOCKED_MALFORMED
  * families_by_highest_support_depth absent -> BLOCKED_MALFORMED
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
_EVIDENCE_DIR = (
    _REPO_ROOT / "assurance" / "evidence" / "universal_100_depth_promotion_candidate_inventory"
)
EXPECTED_STATUS = "UNIVERSAL_100_DEPTH_PROMOTION_CANDIDATE_INVENTORY_PASSED"
LOCK_ID = "DETERMINEX_UNIVERSAL_100_DEPTH_PROMOTION_CANDIDATE_INVENTORY_LOCK_001"
EXPECTED_FAMILY_COUNT = 40
REQUIRED_BATCH_KEYS = ("017", "018", "019")

DECISION_PREFIX = "REACT_UNIVERSAL_100_DEPTH_PROMOTION_CANDIDATE_INVENTORY_BINDING"


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
    "Determinex's roadmap is universal by intake, routing, blocker accounting, and proof discipline.",
    "Universal roadmap does not mean every edge case is supported today.",
    "Every edge case must be supported, blocked by exact missing rung, forbidden, or roadmap.",
    "Family evidence is not full family support.",
    "Scaffold-supported is not working-app proof.",
    "Build-supported is not release support.",
    "Smoke-supported is not production proof.",
    "Unknown/novel routing is not arbitrary app support.",
    "Inventory classifies candidates; it does not promote support.",
    "Local safe proof attempt is not closure.",
)

_CANDIDATE_REQUIRED_KEYS = (
    "sector_id",
    "sector_family",
    "current_highest_support_depth",
    "easiest_next_rung",
    "missing_dependency_or_rung",
)


@dataclass(frozen=True)
class CandidateRow:
    sector_id: str
    sector_family: str
    current_highest_support_depth: str
    has_any_evidence: bool
    easiest_next_rung: str
    missing_dependency_or_rung: tuple[str, ...]
    safe_local_proof_can_be_attempted_now: bool
    cells_accounted: int


@dataclass(frozen=True)
class Universal100DepthPromotionCandidateInventoryStatus:
    decision: str
    target_surface: str
    target_workflow: str
    lock_id: str
    family_count: int
    families_with_any_evidence: int
    families_with_no_evidence: int
    families_by_highest_support_depth: dict[str, int]
    candidates: tuple[CandidateRow, ...]
    batch_targets: dict[str, tuple[str, ...]]
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
        d["candidates"] = [asdict(c) for c in self.candidates]
        d["batch_targets"] = {k: list(v) for k, v in self.batch_targets.items()}
        for k in ("claim_boundary", "forbidden_claims", "source_records", "captions", "notes"):
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


def _candidate_row(c: dict) -> CandidateRow:
    raw_missing = c.get("missing_dependency_or_rung")
    if isinstance(raw_missing, list):
        missing = tuple(str(x) for x in raw_missing)
    elif raw_missing is None:
        missing = ()
    else:
        missing = (str(raw_missing),)
    return CandidateRow(
        sector_id=str(c.get("sector_id") or ""),
        sector_family=str(c.get("sector_family") or ""),
        current_highest_support_depth=str(c.get("current_highest_support_depth") or ""),
        has_any_evidence=bool(c.get("has_any_evidence") or False),
        easiest_next_rung=str(c.get("easiest_next_rung") or ""),
        missing_dependency_or_rung=missing,
        safe_local_proof_can_be_attempted_now=bool(
            c.get("safe_local_proof_can_be_attempted_now") or False
        ),
        cells_accounted=_as_int(c.get("cells_accounted", 0)),
    )


def _shell(*, decision: str, note: str) -> Universal100DepthPromotionCandidateInventoryStatus:
    return Universal100DepthPromotionCandidateInventoryStatus(
        decision=decision,
        target_surface="Universal 100 Depth Promotion Candidate Inventory",
        target_workflow="(awaiting evidence)" if "AWAITING" in decision else "(blocked)",
        lock_id=LOCK_ID,
        family_count=0,
        families_with_any_evidence=0,
        families_with_no_evidence=0,
        families_by_highest_support_depth={},
        candidates=(),
        batch_targets={},
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


def _awaiting(note: str) -> Universal100DepthPromotionCandidateInventoryStatus:
    return _shell(decision=_token("AWAITING_EVIDENCE"), note=note)


def _block(decision: str, note: str) -> Universal100DepthPromotionCandidateInventoryStatus:
    return _shell(decision=decision, note=note)


def load(
    evidence_dir: Path | str | None = None,
) -> Universal100DepthPromotionCandidateInventoryStatus:
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

    family_count = _as_int(blob.get("family_count", 0))
    if family_count != EXPECTED_FAMILY_COUNT:
        return _block(
            _token("BLOCKED_TAXONOMY_OVERCLAIM"),
            f"family_count={family_count} (expected {EXPECTED_FAMILY_COUNT})",
        )

    candidates_raw = blob.get("candidates")
    if not isinstance(candidates_raw, list):
        return _block(_token("BLOCKED_MALFORMED"), "candidates list absent")
    if len(candidates_raw) != family_count:
        return _block(
            _token("BLOCKED_MALFORMED"),
            f"candidates length={len(candidates_raw)} != family_count={family_count}",
        )

    for i, c in enumerate(candidates_raw):
        if not isinstance(c, dict):
            return _block(_token("BLOCKED_MALFORMED"), f"candidate index {i} is not a dict")
        for k in _CANDIDATE_REQUIRED_KEYS:
            if c.get(k) is None or c.get(k) == "":
                return _block(
                    _token("BLOCKED_MALFORMED"),
                    f"candidate index {i} ({c.get('sector_id')!r}) missing key {k!r}",
                )

    batch_targets_raw = blob.get("batch_targets")
    if not isinstance(batch_targets_raw, dict):
        return _block(_token("BLOCKED_MALFORMED"), "batch_targets absent")
    for k in REQUIRED_BATCH_KEYS:
        if k not in batch_targets_raw or not isinstance(batch_targets_raw[k], list):
            return _block(
                _token("BLOCKED_MALFORMED"),
                f"batch_targets[{k!r}] absent or not a list",
            )

    families_by_depth_raw = blob.get("families_by_highest_support_depth")
    if not isinstance(families_by_depth_raw, dict):
        return _block(_token("BLOCKED_MALFORMED"), "families_by_highest_support_depth absent")

    hits: set[str] = set()
    _walk_strings_for_forbidden(blob, hits)
    if hits:
        return _block(
            _token("BLOCKED_BROAD_CLAIM"),
            f"forbidden broad-claim phrases: {sorted(hits)}",
        )

    candidates = tuple(_candidate_row(c) for c in candidates_raw)
    batch_targets = {k: tuple(str(s) for s in batch_targets_raw[k]) for k in REQUIRED_BATCH_KEYS}

    return Universal100DepthPromotionCandidateInventoryStatus(
        decision=_token("PASSED"),
        target_surface="Universal 100 Depth Promotion Candidate Inventory",
        target_workflow=str(
            blob.get("target_workflow") or "universal 100 depth promotion candidate inventory"
        ),
        lock_id=LOCK_ID,
        family_count=family_count,
        families_with_any_evidence=_as_int(blob.get("families_with_any_evidence", 0)),
        families_with_no_evidence=_as_int(blob.get("families_with_no_evidence", 0)),
        families_by_highest_support_depth={
            str(k): _as_int(v) for k, v in families_by_depth_raw.items()
        },
        candidates=candidates,
        batch_targets=batch_targets,
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
    "CandidateRow",
    "Universal100DepthPromotionCandidateInventoryStatus",
    "REQUIRED_PANEL_CAPTIONS",
    "EXPECTED_STATUS",
    "LOCK_ID",
    "EXPECTED_FAMILY_COUNT",
    "REQUIRED_BATCH_KEYS",
]
