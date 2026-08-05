"""Universal 100 Depth Promotion Wave 001 status loader.

DETERMINEX_REACT_UNIVERSAL_100_DEPTH_PROMOTION_WAVE_001_BINDING_LOCK_001.

load() reads Codex's depth-promotion wave 001 aggregate evidence and
returns a render-safe view-model the React panel can display. The wave
aggregates depth-promotion batches 017/018/019 + their support map
deltas. Wave-level aggregation does NOT promote any cell to release
or user-ready support.

Hard rules enforced by load():

  * status != UNIVERSAL_100_DEPTH_PROMOTION_WAVE_001_PASSED ->
    BLOCKED_MALFORMED
  * authority bag flag true -> BLOCKED_AUTHORITY_CONFUSION
  * broad_claims_granted true -> BLOCKED_BROAD_CLAIM
  * release_supported > 0 without release-proof reference ->
    BLOCKED_RELEASE_OVERCLAIM
  * user_ready_with_caveats > 0 without user-ready proof reference ->
    BLOCKED_USER_READY_OVERCLAIM
  * blocked_cells key absent -> BLOCKED_BLOCKED_CELLS_HIDDEN
  * batches dict missing 017/018/019 -> BLOCKED_MALFORMED
  * deltas dict missing 017/018/019 -> BLOCKED_MALFORMED
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
_EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "universal_100_depth_promotion_wave_001"
EXPECTED_STATUS = "UNIVERSAL_100_DEPTH_PROMOTION_WAVE_001_PASSED"
LOCK_ID = "DETERMINEX_UNIVERSAL_100_DEPTH_PROMOTION_WAVE_001_LOCK_001"
REQUIRED_BATCH_KEYS = ("017", "018", "019")

DECISION_PREFIX = "REACT_UNIVERSAL_100_DEPTH_PROMOTION_WAVE_001_BINDING"


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
    "Wave aggregates batches; it does not promote cells.",
    "Determinex's roadmap is universal by intake, routing, blocker accounting, and proof discipline.",
    "Universal roadmap does not mean every edge case is supported today.",
    "Every edge case must be supported, blocked by exact missing rung, forbidden, or roadmap.",
    "Family evidence is not full family support.",
    "Scaffold-supported is not working-app proof.",
    "Build-supported is not release support.",
    "Smoke-supported is not production proof.",
    "Unknown/novel routing is not arbitrary app support.",
    "Release-supported remains 0.",
    "Blocked cells remain visible by exact missing rung.",
)


@dataclass(frozen=True)
class WaveBatchEntry:
    batch_id: str
    lock_id: str
    cells_probed: int
    cells_promoted: int
    cells_blocked: int


@dataclass(frozen=True)
class WaveDeltaEntry:
    batch_id: str
    lock_id: str
    support_map_delta_count: int


@dataclass(frozen=True)
class WaveBlockedCellRow:
    cell_id: str
    sector_id: str
    family: str
    missing_rung: str
    category: str
    claim_boundary: str


@dataclass(frozen=True)
class Universal100DepthPromotionWave001Status:
    decision: str
    target_surface: str
    target_workflow: str
    lock_id: str
    cells_probed: int
    cells_promoted: int
    cells_blocked: int
    release_supported: int
    user_ready_with_caveats: int
    families_with_any_evidence_before: int
    families_improved: tuple[str, ...]
    batches: tuple[WaveBatchEntry, ...]
    deltas: tuple[WaveDeltaEntry, ...]
    blocked_cells: tuple[WaveBlockedCellRow, ...]
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
        d["batches"] = [asdict(b) for b in self.batches]
        d["deltas"] = [asdict(p) for p in self.deltas]
        d["blocked_cells"] = [asdict(c) for c in self.blocked_cells]
        for k in (
            "families_improved",
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


def _blocked_cell_row(c: dict) -> WaveBlockedCellRow:
    return WaveBlockedCellRow(
        cell_id=str(c.get("cell_id") or ""),
        sector_id=str(c.get("sector_id") or ""),
        family=str(c.get("family") or ""),
        missing_rung=str(c.get("missing_rung") or ""),
        category=str(c.get("category") or ""),
        claim_boundary=str(c.get("claim_boundary") or ""),
    )


def _has_user_ready_proof_reference(blob: dict) -> bool:
    paths = blob.get("source_evidence_paths") or []
    for p in paths:
        s = str(p).lower()
        if "user_ready" in s or "fresh_install_verified" in s:
            return True
    return False


def _shell(*, decision: str, note: str) -> Universal100DepthPromotionWave001Status:
    return Universal100DepthPromotionWave001Status(
        decision=decision,
        target_surface="Universal 100 Depth Promotion Wave 001",
        target_workflow="(awaiting evidence)" if "AWAITING" in decision else "(blocked)",
        lock_id=LOCK_ID,
        cells_probed=0,
        cells_promoted=0,
        cells_blocked=0,
        release_supported=0,
        user_ready_with_caveats=0,
        families_with_any_evidence_before=0,
        families_improved=(),
        batches=(),
        deltas=(),
        blocked_cells=(),
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


def _awaiting(note: str) -> Universal100DepthPromotionWave001Status:
    return _shell(decision=_token("AWAITING_EVIDENCE"), note=note)


def _block(decision: str, note: str) -> Universal100DepthPromotionWave001Status:
    return _shell(decision=decision, note=note)


def load(
    evidence_dir: Path | str | None = None,
) -> Universal100DepthPromotionWave001Status:
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

    blocked_raw = blob.get("blocked_cells")
    if blocked_raw is None:
        return _block(
            _token("BLOCKED_BLOCKED_CELLS_HIDDEN"),
            "blocked_cells key absent — blocked cells must remain visible",
        )

    batches_raw = blob.get("batches")
    if not isinstance(batches_raw, dict):
        return _block(_token("BLOCKED_MALFORMED"), "batches dict absent")
    for k in REQUIRED_BATCH_KEYS:
        if k not in batches_raw:
            return _block(_token("BLOCKED_MALFORMED"), f"batches[{k!r}] absent")
    deltas_raw = blob.get("deltas")
    if not isinstance(deltas_raw, dict):
        return _block(_token("BLOCKED_MALFORMED"), "deltas dict absent")
    for k in REQUIRED_BATCH_KEYS:
        if k not in deltas_raw:
            return _block(_token("BLOCKED_MALFORMED"), f"deltas[{k!r}] absent")

    release_supported = _as_int(blob.get("release_supported", 0))
    if release_supported > 0 and not _has_release_proof_reference(blob):
        return _block(
            _token("BLOCKED_RELEASE_OVERCLAIM"),
            f"release_supported={release_supported} without release-proof source path",
        )

    user_ready_with_caveats = _as_int(blob.get("user_ready_with_caveats", 0))
    if user_ready_with_caveats > 0 and not _has_user_ready_proof_reference(blob):
        return _block(
            _token("BLOCKED_USER_READY_OVERCLAIM"),
            f"user_ready_with_caveats={user_ready_with_caveats} without user-ready proof reference",
        )

    hits: set[str] = set()
    _walk_strings_for_forbidden(blob, hits)
    if hits:
        return _block(
            _token("BLOCKED_BROAD_CLAIM"),
            f"forbidden broad-claim phrases: {sorted(hits)}",
        )

    batches = tuple(
        WaveBatchEntry(
            batch_id=str(k),
            lock_id=str((batches_raw[k] or {}).get("lock_id") or ""),
            cells_probed=_as_int((batches_raw[k] or {}).get("cells_probed", 0)),
            cells_promoted=_as_int((batches_raw[k] or {}).get("cells_promoted", 0)),
            cells_blocked=_as_int((batches_raw[k] or {}).get("cells_blocked", 0)),
        )
        for k in REQUIRED_BATCH_KEYS
    )
    deltas = tuple(
        WaveDeltaEntry(
            batch_id=str(k),
            lock_id=str((deltas_raw[k] or {}).get("lock_id") or ""),
            support_map_delta_count=_as_int(
                (deltas_raw[k] or {}).get("support_map_delta_count", 0)
            ),
        )
        for k in REQUIRED_BATCH_KEYS
    )
    blocked_cells = tuple(_blocked_cell_row(c) for c in blocked_raw if isinstance(c, dict))

    return Universal100DepthPromotionWave001Status(
        decision=_token("PASSED"),
        target_surface="Universal 100 Depth Promotion Wave 001",
        target_workflow=str(
            blob.get("target_workflow") or "universal 100 depth promotion wave 001"
        ),
        lock_id=LOCK_ID,
        cells_probed=_as_int(blob.get("cells_probed", 0)),
        cells_promoted=_as_int(blob.get("cells_promoted", 0)),
        cells_blocked=_as_int(blob.get("cells_blocked", 0)),
        release_supported=release_supported,
        user_ready_with_caveats=user_ready_with_caveats,
        families_with_any_evidence_before=_as_int(blob.get("families_with_any_evidence_before", 0)),
        families_improved=tuple(str(f) for f in (blob.get("families_improved") or [])),
        batches=batches,
        deltas=deltas,
        blocked_cells=blocked_cells,
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
    "WaveBatchEntry",
    "WaveDeltaEntry",
    "WaveBlockedCellRow",
    "Universal100DepthPromotionWave001Status",
    "REQUIRED_PANEL_CAPTIONS",
    "EXPECTED_STATUS",
    "LOCK_ID",
    "REQUIRED_BATCH_KEYS",
]
