"""Public Unknown / Novel Route status loader.

DETERMINEX_REACT_PUBLIC_UNKNOWN_NOVEL_ROUTE_BINDING_LOCK_001.

load() reads Codex's unknown/novel intake-route preservation evidence
(from the edge-case roadmap status + flagship cert + export run) and
returns a render-safe view-model the React panel can display.

The panel DISPLAYS the route: unknown_novel_intake_route is accepted
into routing/blocker-accounting but NOT_CLAIMED, blocked by
CONCRETE_FIXTURE_REQUIRED. Novel intake is routed, not hallucinated;
not treated as supported until fixture+verifier+evidence+promotion
gates pass.

Hard rules enforced by load():

  * edge-case status artifact absent / unparseable -> AWAITING_EVIDENCE
  * status != UNIVERSAL_100_EDGE_CASE_EXPANSION_ROADMAP_PASSED ->
    BLOCKED_MALFORMED
  * cell_id != "unknown_novel_intake_route" -> BLOCKED_ROUTE_MISMATCH
  * claim_state != "NOT_CLAIMED" -> BLOCKED_NOVEL_OVERCLAIM
  * missing_rung_key != "CONCRETE_FIXTURE_REQUIRED" ->
    BLOCKED_BLOCKER_MISMATCH
  * route_status != "routed" -> BLOCKED_ROUTE_MISMATCH
  * support_claimed True / promoted True / release_supported True ->
    BLOCKED_NOVEL_OVERCLAIM
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


_REPO_ROOT = _HERE.parent.parent.parent
_EDGE_DIR = _REPO_ROOT / "assurance" / "evidence" / "universal_100_edge_case_expansion_roadmap"
_EDGE_STATUS = _EDGE_DIR / "edge_case_status_20260529.json"
_FLAGSHIP_DIR = (
    _REPO_ROOT / "assurance" / "evidence" / "public_tidal_wave_flagship_flow_certification"
)
_EXPORT_DIR = _REPO_ROOT / "assurance" / "evidence" / "public_proof_report_export"

LOCK_ID = "DETERMINEX_REACT_PUBLIC_UNKNOWN_NOVEL_ROUTE_BINDING_LOCK_001"
EXPECTED_CELL_ID = "unknown_novel_intake_route"
EXPECTED_CLAIM_STATE = "NOT_CLAIMED"
EXPECTED_MISSING_RUNG_KEY = "CONCRETE_FIXTURE_REQUIRED"
EXPECTED_ROUTE_STATUS = "routed"

DECISION_PREFIX = "REACT_PUBLIC_UNKNOWN_NOVEL_ROUTE_BINDING"


def _token(suffix: str) -> str:
    return f"{DECISION_PREFIX}_{suffix}"


REQUIRED_PANEL_CAPTIONS = (
    "This panel displays evidence; it does not grant authority.",
    "Unknown and novel requests are accepted into routing and "
    "blocker accounting. They are not treated as supported until "
    "fixture, verifier, evidence, and promotion gates pass.",
    "Unknown/novel intake remains NOT_CLAIMED.",
    "Blocker remains CONCRETE_FIXTURE_REQUIRED.",
    "Universal support is not claimed.",
    "Novel cases are routed, not hallucinated.",
    "Release-supported remains 0 cells / 0 families.",
)


@dataclass(frozen=True)
class PublicUnknownNovelRouteStatus:
    decision: str
    target_surface: str
    target_workflow: str
    lock_id: str
    cell_id: str
    claim_state: str
    missing_rung_key: str
    missing_rung_text: str
    route_status: str
    support_claimed: bool
    promoted: bool
    release_supported: bool
    next_required_action: str
    edge_case_evidence_ref: str
    flagship_evidence_ref: str
    export_evidence_ref: str
    captions: tuple[str, ...]
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        for k in ("captions", "notes"):
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


def _shell(*, decision: str, note: str) -> PublicUnknownNovelRouteStatus:
    return PublicUnknownNovelRouteStatus(
        decision=decision,
        target_surface="Public Unknown / Novel Route",
        target_workflow="(awaiting evidence)" if "AWAITING" in decision else "(blocked)",
        lock_id=LOCK_ID,
        cell_id="",
        claim_state="",
        missing_rung_key="",
        missing_rung_text="",
        route_status="",
        support_claimed=False,
        promoted=False,
        release_supported=False,
        next_required_action="",
        edge_case_evidence_ref="",
        flagship_evidence_ref="",
        export_evidence_ref="",
        captions=REQUIRED_PANEL_CAPTIONS,
        notes=(note,),
    )


def _awaiting(note: str) -> PublicUnknownNovelRouteStatus:
    return _shell(decision=_token("AWAITING_EVIDENCE"), note=note)


def _block(decision: str, note: str) -> PublicUnknownNovelRouteStatus:
    return _shell(decision=decision, note=note)


def _relative_to_repo(path: Path) -> str:
    try:
        return path.resolve().relative_to(_REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def load(
    edge_status_path: Path | str | None = None,
    flagship_dir: Path | str | None = None,
    export_dir: Path | str | None = None,
    edge_run_dir: Path | str | None = None,
) -> PublicUnknownNovelRouteStatus:
    edge_status_p = Path(edge_status_path) if edge_status_path else _EDGE_STATUS
    if not edge_status_p.is_file():
        return _awaiting(f"edge-case status artifact absent at {edge_status_p}")
    try:
        sblob = json.loads(edge_status_p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return _awaiting(f"could not parse edge-case status: {exc}")
    if sblob.get("lock_status") != "UNIVERSAL_100_EDGE_CASE_EXPANSION_ROADMAP_PASSED":
        return _block(
            _token("BLOCKED_MALFORMED"),
            f"edge-case status lock_status={sblob.get('lock_status')!r}",
        )

    edir = Path(edge_run_dir) if edge_run_dir else _EDGE_DIR
    edge_chosen = _locate_latest_evidence(edir)
    if edge_chosen is None:
        return _awaiting(f"edge-case run artifact absent at {edir}")
    try:
        eblob = json.loads(edge_chosen.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return _awaiting(f"could not parse edge-case run: {exc}")
    if eblob.get("status") != "UNIVERSAL_100_EDGE_CASE_EXPANSION_ROADMAP_PASSED":
        return _block(
            _token("BLOCKED_MALFORMED"),
            f"edge-case run status={eblob.get('status')!r}",
        )

    unknown_run = eblob.get("unknown_novel_request_routing") or {}
    unknown_status = sblob.get("unknown_novel_route_status") or {}

    cell_id = str(unknown_run.get("cell_id") or unknown_status.get("cell_id") or "")
    if cell_id != EXPECTED_CELL_ID:
        return _block(
            _token("BLOCKED_ROUTE_MISMATCH"),
            f"cell_id={cell_id!r} (expected {EXPECTED_CELL_ID!r})",
        )
    claim_state = str(unknown_run.get("claim_state") or unknown_status.get("claim_state") or "")
    if claim_state != EXPECTED_CLAIM_STATE:
        return _block(
            _token("BLOCKED_NOVEL_OVERCLAIM"),
            f"claim_state={claim_state!r} (expected {EXPECTED_CLAIM_STATE!r})",
        )
    missing_rung_key = str(
        unknown_run.get("missing_rung_key") or unknown_status.get("missing_rung_key") or ""
    )
    if missing_rung_key != EXPECTED_MISSING_RUNG_KEY:
        return _block(
            _token("BLOCKED_BLOCKER_MISMATCH"),
            f"missing_rung_key={missing_rung_key!r} (expected {EXPECTED_MISSING_RUNG_KEY!r})",
        )
    route_status = str(unknown_run.get("route_status") or unknown_status.get("route_status") or "")
    if route_status != EXPECTED_ROUTE_STATUS:
        return _block(
            _token("BLOCKED_ROUTE_MISMATCH"),
            f"route_status={route_status!r} (expected {EXPECTED_ROUTE_STATUS!r})",
        )
    support_claimed = bool(
        unknown_run.get("promoted") or unknown_status.get("support_claimed") or False
    )
    promoted = bool(unknown_run.get("promoted", False))
    release_supported = bool(unknown_run.get("release_supported", False))
    if support_claimed or promoted or release_supported:
        return _block(
            _token("BLOCKED_NOVEL_OVERCLAIM"),
            f"support_claimed={support_claimed} promoted={promoted} release_supported={release_supported}",
        )

    fchosen = _locate_latest_evidence(_FLAGSHIP_DIR if flagship_dir is None else Path(flagship_dir))
    echosen = _locate_latest_evidence(_EXPORT_DIR if export_dir is None else Path(export_dir))

    return PublicUnknownNovelRouteStatus(
        decision=_token("PASSED"),
        target_surface="Public Unknown / Novel Route",
        target_workflow="public unknown / novel route",
        lock_id=LOCK_ID,
        cell_id=cell_id,
        claim_state=claim_state,
        missing_rung_key=missing_rung_key,
        missing_rung_text=str(unknown_run.get("missing_rung") or ""),
        route_status=route_status,
        support_claimed=False,
        promoted=False,
        release_supported=False,
        next_required_action=str(unknown_run.get("next_required_action") or ""),
        edge_case_evidence_ref=_relative_to_repo(edge_chosen),
        flagship_evidence_ref=_relative_to_repo(fchosen) if fchosen else "",
        export_evidence_ref=_relative_to_repo(echosen) if echosen else "",
        captions=REQUIRED_PANEL_CAPTIONS,
        notes=(),
    )


__all__ = [
    "load",
    "PublicUnknownNovelRouteStatus",
    "REQUIRED_PANEL_CAPTIONS",
    "LOCK_ID",
    "EXPECTED_CELL_ID",
    "EXPECTED_CLAIM_STATE",
    "EXPECTED_MISSING_RUNG_KEY",
    "EXPECTED_ROUTE_STATUS",
]
