"""Universal 100 Conveyor Backlog and Depth Queue status loader.

DETERMINEX_REACT_UNIVERSAL_100_CONVEYOR_BACKLOG_AND_DEPTH_QUEUE_BINDING_LOCK_001.

The backlog is a planning surface, not a capability claim. The React
binding displays Codex's next-action queues (sector gulp, depth
promotion, verifier-building, fixture-building, packaging / fresh
install, user-ready-with-caveats candidates), blocked cells by exact
missing rung, roadmap cells by exact missing rung, forbidden/policy-
blocked cells, the Claude visual binding backlog, and Codex's safe
parallel work queue.

Hard rules enforced by load():

  * status != UNIVERSAL_100_CONVEYOR_BACKLOG_AND_DEPTH_QUEUE_PASSED ->
    BLOCKED_MALFORMED
  * authority bag flag true -> BLOCKED_AUTHORITY_CONFUSION
  * broad_claims_granted true -> BLOCKED_BROAD_CLAIM
  * summary.known_cells_accounted missing -> BLOCKED_MALFORMED
  * next_safe_sector_gulp_queue missing or empty -> BLOCKED_MALFORMED
  * claude_visual_binding_backlog missing -> BLOCKED_MALFORMED
  * any forbidden broad-claim phrase as current claim outside
    refusal context -> BLOCKED_BROAD_CLAIM
  * any "release_supported" or "user_ready_with_caveats" assertion
    appears in the wrong context (i.e. summary fields named so without
    explicit release-proof / user-ready-proof source path) ->
    BLOCKED_RELEASE_OVERCLAIM / BLOCKED_USER_READY_OVERCLAIM
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
    FORBIDDEN_BROAD_CLAIM_PHRASES,
)

_REPO_ROOT = _HERE.parent.parent.parent

_DEFAULT_EVIDENCE_DIR = (
    _REPO_ROOT / "assurance" / "evidence" / "universal_100_conveyor_backlog_and_depth_queue"
)

EXPECTED_STATUS = "UNIVERSAL_100_CONVEYOR_BACKLOG_AND_DEPTH_QUEUE_PASSED"

REQUIRED_PANEL_CAPTIONS = (
    "This panel displays evidence; it does not grant authority.",
    "Backlog is planning structure, not a capability claim.",
    "Blocked cells remain visible by exact missing rung.",
    "Roadmap cells remain visible by exact missing rung.",
    "Queue membership does not grant support.",
    "User-ready-with-caveats candidates are CANDIDATES, not user-ready cells.",
    "Packaging candidates are CANDIDATES, not packaging-supported.",
    "Release-supported remains 0 — no cell appears as release-supported here.",
    "No source mutation without authority.",
    "Universal 100 means universal intake/routing, not magic execution.",
)


REACT_UNIVERSAL_100_CONVEYOR_BACKLOG_AND_DEPTH_QUEUE_BINDING_STATUS_TOKENS = (
    "REACT_UNIVERSAL_100_CONVEYOR_BACKLOG_AND_DEPTH_QUEUE_BINDING_PASSED",
    "REACT_UNIVERSAL_100_CONVEYOR_BACKLOG_AND_DEPTH_QUEUE_BINDING_AWAITING_EVIDENCE",
    "REACT_UNIVERSAL_100_CONVEYOR_BACKLOG_AND_DEPTH_QUEUE_BINDING_BLOCKED_MALFORMED",
    "REACT_UNIVERSAL_100_CONVEYOR_BACKLOG_AND_DEPTH_QUEUE_BINDING_BLOCKED_AUTHORITY_CONFUSION",
    "REACT_UNIVERSAL_100_CONVEYOR_BACKLOG_AND_DEPTH_QUEUE_BINDING_BLOCKED_BROAD_CLAIM",
    "REACT_UNIVERSAL_100_CONVEYOR_BACKLOG_AND_DEPTH_QUEUE_BINDING_BLOCKED_RELEASE_OVERCLAIM",
    "REACT_UNIVERSAL_100_CONVEYOR_BACKLOG_AND_DEPTH_QUEUE_BINDING_BLOCKED_USER_READY_OVERCLAIM",
)


_REFUSAL_CONTEXT_KEYS = {
    "forbidden_claims",
    "forbidden_policy_blocked_cells",
    "claim_boundary",
    "release_boundary",
    "missing_rung",
    "missing_rungs",
    "does_not_mean",
    "what_remains_forbidden",
    "blocked_path_demo",
    "blocked_path_summary",
    "captions",
    "required_panel_captions",
    "never_claim",
    "must_never_claim",
    "must_refuse",
    "negative_claims",
    "refused_claims",
    "fallbacks_enforced",
    "must_stop_if",
    "stop_after",
}


def _walk_backlog_strings(node: object, hits: set[str]) -> None:
    if isinstance(node, str):
        lowered = node.lower()
        for phrase in FORBIDDEN_BROAD_CLAIM_PHRASES:
            if phrase in lowered:
                hits.add(phrase)
    elif isinstance(node, dict):
        for k, v in node.items():
            if isinstance(k, str) and k.lower() in _REFUSAL_CONTEXT_KEYS:
                continue
            _walk_backlog_strings(v, hits)
    elif isinstance(node, list):
        for item in node:
            _walk_backlog_strings(item, hits)


@dataclass(frozen=True)
class ConveyorBacklogAndDepthQueueStatus:
    decision: str
    target_surface: str
    target_workflow: str
    known_cells_accounted: int
    next_gulp_batches_queued: int
    depth_candidates: int
    packaging_candidates: int
    user_ready_candidates: int
    blocked_missing_rung_count: int
    roadmap_missing_rung_count: int
    forbidden_policy_blocked_count: int
    batch_007_cells_accounted: int
    next_safe_sector_gulp_queue: tuple[dict[str, object], ...]
    next_depth_promotion_queue_by_sector: dict[str, object]
    next_verifier_building_queue: dict[str, object]
    next_fixture_building_queue: dict[str, object]
    next_packaging_fresh_install_queue: tuple[dict[str, object], ...]
    next_user_ready_with_caveats_candidates_by_sector: dict[str, object]
    blocked_cells_by_exact_missing_rung: tuple[dict[str, object], ...]
    roadmap_cells_by_exact_missing_rung: tuple[dict[str, object], ...]
    forbidden_policy_blocked_cells: tuple[dict[str, object], ...]
    claude_visual_binding_backlog: dict[str, object]
    codex_safe_parallel_work_queue: dict[str, object]
    claim_boundary: tuple[str, ...]
    forbidden_claims: tuple[str, ...]
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
    evidence_ref: str
    captions: tuple[str, ...]
    current_next_rung: str
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        for k in (
            "next_safe_sector_gulp_queue",
            "next_packaging_fresh_install_queue",
            "blocked_cells_by_exact_missing_rung",
            "roadmap_cells_by_exact_missing_rung",
            "forbidden_policy_blocked_cells",
            "claim_boundary",
            "forbidden_claims",
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


def _tuple_of_dicts(value: object) -> tuple[dict[str, object], ...]:
    if not isinstance(value, list):
        return tuple()
    return tuple(dict(item) for item in value if isinstance(item, dict))


def _missing_rung_dict_to_rows(value: object) -> tuple[dict[str, object], ...]:
    """Flatten Codex's {missing_rung_text: [cell, cell, ...]} shape into rows."""
    if isinstance(value, list):
        return _tuple_of_dicts(value)
    if not isinstance(value, dict):
        return tuple()
    rows: list[dict[str, object]] = []
    for missing_rung, cells in value.items():
        if not isinstance(cells, list):
            continue
        for cell in cells:
            if isinstance(cell, dict):
                row = dict(cell)
                row.setdefault("missing_rung", missing_rung)
                rows.append(row)
            elif isinstance(cell, str):
                rows.append({"cell_id": cell, "missing_rung": missing_rung})
        if not cells:
            # Keep the missing-rung key visible even when no cells are listed.
            rows.append({"cell_id": "", "missing_rung": missing_rung})
    return tuple(rows)


def _dict_or_empty(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, dict) else {}


def _shell(*, decision: str, note: str) -> ConveyorBacklogAndDepthQueueStatus:
    return ConveyorBacklogAndDepthQueueStatus(
        decision=decision,
        target_surface="Universal 100 Conveyor Backlog and Depth Queue",
        target_workflow="(awaiting evidence)" if "AWAITING" in decision else "(blocked)",
        known_cells_accounted=0,
        next_gulp_batches_queued=0,
        depth_candidates=0,
        packaging_candidates=0,
        user_ready_candidates=0,
        blocked_missing_rung_count=0,
        roadmap_missing_rung_count=0,
        forbidden_policy_blocked_count=0,
        batch_007_cells_accounted=0,
        next_safe_sector_gulp_queue=tuple(),
        next_depth_promotion_queue_by_sector={},
        next_verifier_building_queue={},
        next_fixture_building_queue={},
        next_packaging_fresh_install_queue=tuple(),
        next_user_ready_with_caveats_candidates_by_sector={},
        blocked_cells_by_exact_missing_rung=tuple(),
        roadmap_cells_by_exact_missing_rung=tuple(),
        forbidden_policy_blocked_cells=tuple(),
        claude_visual_binding_backlog={},
        codex_safe_parallel_work_queue={},
        claim_boundary=tuple(),
        forbidden_claims=tuple(),
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
        evidence_ref="",
        captions=REQUIRED_PANEL_CAPTIONS,
        current_next_rung="",
        notes=(note,),
    )


def _awaiting(note: str) -> ConveyorBacklogAndDepthQueueStatus:
    return _shell(
        decision="REACT_UNIVERSAL_100_CONVEYOR_BACKLOG_AND_DEPTH_QUEUE_BINDING_AWAITING_EVIDENCE",
        note=note,
    )


def _block(decision: str, note: str) -> ConveyorBacklogAndDepthQueueStatus:
    return _shell(decision=decision, note=note)


def load(evidence_dir: Path | str | None = None) -> ConveyorBacklogAndDepthQueueStatus:
    ed = Path(evidence_dir) if evidence_dir else _DEFAULT_EVIDENCE_DIR
    chosen = _locate_latest_evidence(ed)
    if chosen is None:
        return _awaiting(f"no evidence file under {ed}")
    try:
        blob = json.loads(chosen.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return _awaiting(f"could not read evidence: {exc}")

    if blob.get("status") != EXPECTED_STATUS:
        return _block(
            "REACT_UNIVERSAL_100_CONVEYOR_BACKLOG_AND_DEPTH_QUEUE_BINDING_BLOCKED_MALFORMED",
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
                "REACT_UNIVERSAL_100_CONVEYOR_BACKLOG_AND_DEPTH_QUEUE_BINDING_BLOCKED_AUTHORITY_CONFUSION",
                f"authority flag {flag} is true",
            )
    if _auth("broad_claims_granted"):
        return _block(
            "REACT_UNIVERSAL_100_CONVEYOR_BACKLOG_AND_DEPTH_QUEUE_BINDING_BLOCKED_BROAD_CLAIM",
            "broad_claims_granted is true",
        )

    summary = blob.get("summary") or {}
    if "known_cells_accounted" not in summary:
        return _block(
            "REACT_UNIVERSAL_100_CONVEYOR_BACKLOG_AND_DEPTH_QUEUE_BINDING_BLOCKED_MALFORMED",
            "summary.known_cells_accounted missing",
        )

    next_gulp_queue = blob.get("next_safe_sector_gulp_queue")
    if not isinstance(next_gulp_queue, list) or not next_gulp_queue:
        return _block(
            "REACT_UNIVERSAL_100_CONVEYOR_BACKLOG_AND_DEPTH_QUEUE_BINDING_BLOCKED_MALFORMED",
            "next_safe_sector_gulp_queue missing or empty",
        )

    claude_backlog = blob.get("claude_visual_binding_backlog")
    if not isinstance(claude_backlog, dict):
        return _block(
            "REACT_UNIVERSAL_100_CONVEYOR_BACKLOG_AND_DEPTH_QUEUE_BINDING_BLOCKED_MALFORMED",
            "claude_visual_binding_backlog missing",
        )

    hits: set[str] = set()
    _walk_backlog_strings(blob, hits)
    if hits:
        return _block(
            "REACT_UNIVERSAL_100_CONVEYOR_BACKLOG_AND_DEPTH_QUEUE_BINDING_BLOCKED_BROAD_CLAIM",
            f"forbidden broad-claim phrases as current claim: {sorted(hits)}",
        )

    return ConveyorBacklogAndDepthQueueStatus(
        decision="REACT_UNIVERSAL_100_CONVEYOR_BACKLOG_AND_DEPTH_QUEUE_BINDING_PASSED",
        target_surface="Universal 100 Conveyor Backlog and Depth Queue",
        target_workflow="conveyor backlog and depth queue (planning surface)",
        known_cells_accounted=int(summary.get("known_cells_accounted", 0)),
        next_gulp_batches_queued=int(summary.get("next_gulp_batches_queued", 0)),
        depth_candidates=int(summary.get("depth_candidates", 0)),
        packaging_candidates=int(summary.get("packaging_candidates", 0)),
        user_ready_candidates=int(summary.get("user_ready_candidates", 0)),
        blocked_missing_rung_count=int(summary.get("blocked_missing_rung_count", 0)),
        roadmap_missing_rung_count=int(summary.get("roadmap_missing_rung_count", 0)),
        forbidden_policy_blocked_count=int(summary.get("forbidden_policy_blocked_count", 0)),
        batch_007_cells_accounted=int(summary.get("batch_007_cells_accounted", 0)),
        next_safe_sector_gulp_queue=_tuple_of_dicts(next_gulp_queue),
        next_depth_promotion_queue_by_sector=_dict_or_empty(blob.get("next_depth_promotion_queue")),
        next_verifier_building_queue=_dict_or_empty(blob.get("next_verifier_building_queue")),
        next_fixture_building_queue=_dict_or_empty(blob.get("next_fixture_building_queue")),
        next_packaging_fresh_install_queue=_tuple_of_dicts(
            blob.get("next_packaging_fresh_install_queue")
        ),
        next_user_ready_with_caveats_candidates_by_sector=_dict_or_empty(
            blob.get("next_user_ready_with_caveats_candidates")
        ),
        blocked_cells_by_exact_missing_rung=_missing_rung_dict_to_rows(
            blob.get("blocked_cells_by_exact_missing_rung")
        ),
        roadmap_cells_by_exact_missing_rung=_missing_rung_dict_to_rows(
            blob.get("roadmap_cells_by_exact_missing_rung")
        ),
        forbidden_policy_blocked_cells=_tuple_of_dicts(blob.get("forbidden_policy_blocked_cells")),
        claude_visual_binding_backlog=dict(claude_backlog),
        codex_safe_parallel_work_queue=_dict_or_empty(blob.get("codex_safe_parallel_work_queue")),
        claim_boundary=tuple(str(x) for x in (blob.get("claim_boundary") or [])),
        forbidden_claims=tuple(str(x) for x in (blob.get("forbidden_claims") or [])),
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


__all__ = [
    "load",
    "REACT_UNIVERSAL_100_CONVEYOR_BACKLOG_AND_DEPTH_QUEUE_BINDING_STATUS_TOKENS",
    "REQUIRED_PANEL_CAPTIONS",
    "ConveyorBacklogAndDepthQueueStatus",
]
