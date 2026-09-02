"""Public Tidal Wave Flagship Flow Certification status loader.

DETERMINEX_REACT_PUBLIC_TIDAL_WAVE_FLAGSHIP_FLOW_CERTIFICATION_BINDING_LOCK_001.

load() reads the Codex public flagship flow certification evidence and
returns a render-safe view-model the React panel can display. The
certification covers 10 flagship user journeys + false-claim scanner +
proof report model.

The panel DISPLAYS evidence; it does NOT grant authority. Flagship
certification is a journey/routing/blocker-accounting model, NOT
release support, production readiness, or universal support.

Hard rules enforced by load():

  * status != PUBLIC_TIDAL_WAVE_FLAGSHIP_FLOW_CERTIFICATION_PASSED ->
    BLOCKED_MALFORMED
  * authority bag flag true -> BLOCKED_AUTHORITY_CONFUSION
  * broad_claims_granted true -> BLOCKED_BROAD_CLAIM
  * flagship_flows_certified_count != 10 -> BLOCKED_FLAGSHIP_COUNT_MISMATCH
  * flagship_flows list length != 10 -> BLOCKED_MALFORMED
  * false_claim_scanner_model.blocked_or_flagged_phrases length != 9 ->
    BLOCKED_SCANNER_COUNT_MISMATCH
  * proof_report_model.fields length != 12 ->
    BLOCKED_PROOF_REPORT_FIELDS_COUNT_MISMATCH
  * authority_boundary.universal_support_claimed != False ->
    BLOCKED_BROAD_CLAIM
  * release_supported_cells / release_supported_families != 0 ->
    BLOCKED_RELEASE_OVERCLAIM
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
    _REPO_ROOT / "assurance" / "evidence" / "public_tidal_wave_flagship_flow_certification"
)
EXPECTED_STATUS = "PUBLIC_TIDAL_WAVE_FLAGSHIP_FLOW_CERTIFICATION_PASSED"
LOCK_ID = "DETERMINEX_REACT_PUBLIC_TIDAL_WAVE_FLAGSHIP_FLOW_CERTIFICATION_BINDING_LOCK_001"
EXPECTED_FLAGSHIP_FLOWS_COUNT = 10
EXPECTED_FALSE_CLAIM_PHRASES_COUNT = 9
EXPECTED_PROOF_REPORT_FIELDS_COUNT = 12
SOURCE_TRUTH_LOCK_ID = "DETERMINEX_PUBLIC_TIDAL_WAVE_FLAGSHIP_FLOW_CERTIFICATION_LOCK_001"
SOURCE_TRUTH_COMMIT = "ff1f047eb"

DECISION_PREFIX = "REACT_PUBLIC_TIDAL_WAVE_FLAGSHIP_FLOW_CERTIFICATION_BINDING"


def _token(suffix: str) -> str:
    return f"{DECISION_PREFIX}_{suffix}"


def _as_int(v) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


REQUIRED_PANEL_CAPTIONS = (
    "This panel displays evidence; it does not grant authority.",
    "Determinex's public flagship journey model is certified for routing, "
    "reporting, blocker accounting, and claim boundaries. This is not "
    "release support or production readiness.",
    "Release-supported remains 0 cells / 0 families.",
    "Universal support is not claimed.",
    "False-claim scanner blocks or flags forbidden broad claims.",
    "Authority remains locked down. No source mutation, training, "
    "proof-execution, or broad-claims authority granted.",
)


@dataclass(frozen=True)
class FlagshipFlowRow:
    flow_id: str
    name: str
    intake: tuple[str, ...]
    route: tuple[str, ...]
    blocker_handling: tuple[str, ...]
    proof_report_output: str
    claim_boundary: str


@dataclass(frozen=True)
class PublicTidalWaveFlagshipFlowCertificationStatus:
    decision: str
    target_surface: str
    target_workflow: str
    lock_id: str
    source_truth_lock_id: str
    source_truth_commit: str
    artifact_path: str
    status_artifact_path: str
    flagship_flows_certified_count: int
    flagship_flows: tuple[FlagshipFlowRow, ...]
    false_claim_phrases_count: int
    proof_report_fields_count: int
    release_supported_cells: int
    release_supported_families: int
    release_support_unchanged_at_zero: bool
    universal_support_claimed: bool
    universal_handling_certified_as_journey_model: bool
    source_mutation_authorized: bool
    real_user_source_mutation_authorized: bool
    proof_execution_authority_granted: bool
    training_eligible: bool
    broad_claims_granted: bool
    unknown_novel_cell_id: str
    unknown_novel_claim_state: str
    unknown_novel_missing_rung_key: str
    unknown_novel_route_status: str
    unknown_novel_support_claimed: bool
    validation_passed: bool
    validation_errors: tuple[str, ...]
    evidence_ref: str
    captions: tuple[str, ...]
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["flagship_flows"] = [asdict(f) for f in self.flagship_flows]
        for k in ("validation_errors", "captions", "notes"):
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


def _flow_row(f: dict) -> FlagshipFlowRow:
    return FlagshipFlowRow(
        flow_id=str(f.get("flow_id") or ""),
        name=str(f.get("name") or ""),
        intake=tuple(str(x) for x in (f.get("intake") or [])),
        route=tuple(str(x) for x in (f.get("route") or [])),
        blocker_handling=tuple(str(x) for x in (f.get("blocker_handling") or [])),
        proof_report_output=str(f.get("proof_report_output") or ""),
        claim_boundary=str(f.get("claim_boundary") or ""),
    )


def _shell(*, decision: str, note: str) -> PublicTidalWaveFlagshipFlowCertificationStatus:
    return PublicTidalWaveFlagshipFlowCertificationStatus(
        decision=decision,
        target_surface="Public Tidal Wave Flagship Flow Certification",
        target_workflow="(awaiting evidence)" if "AWAITING" in decision else "(blocked)",
        lock_id=LOCK_ID,
        source_truth_lock_id=SOURCE_TRUTH_LOCK_ID,
        source_truth_commit=SOURCE_TRUTH_COMMIT,
        artifact_path="",
        status_artifact_path="",
        flagship_flows_certified_count=0,
        flagship_flows=(),
        false_claim_phrases_count=0,
        proof_report_fields_count=0,
        release_supported_cells=0,
        release_supported_families=0,
        release_support_unchanged_at_zero=False,
        universal_support_claimed=False,
        universal_handling_certified_as_journey_model=False,
        source_mutation_authorized=False,
        real_user_source_mutation_authorized=False,
        proof_execution_authority_granted=False,
        training_eligible=False,
        broad_claims_granted=False,
        unknown_novel_cell_id="",
        unknown_novel_claim_state="",
        unknown_novel_missing_rung_key="",
        unknown_novel_route_status="",
        unknown_novel_support_claimed=False,
        validation_passed=False,
        validation_errors=(),
        evidence_ref="",
        captions=REQUIRED_PANEL_CAPTIONS,
        notes=(note,),
    )


def _awaiting(note: str) -> PublicTidalWaveFlagshipFlowCertificationStatus:
    return _shell(decision=_token("AWAITING_EVIDENCE"), note=note)


def _block(decision: str, note: str) -> PublicTidalWaveFlagshipFlowCertificationStatus:
    return _shell(decision=decision, note=note)


def _relative_to_repo(path: Path) -> str:
    try:
        return path.resolve().relative_to(_REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def load(
    evidence_dir: Path | str | None = None,
) -> PublicTidalWaveFlagshipFlowCertificationStatus:
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
        return _block(_token("BLOCKED_BROAD_CLAIM"), "broad_claims_granted is true")

    authority_boundary = blob.get("authority_boundary") or {}
    if authority_boundary.get("universal_support_claimed") is not False:
        return _block(
            _token("BLOCKED_BROAD_CLAIM"),
            f"authority_boundary.universal_support_claimed={authority_boundary.get('universal_support_claimed')!r}",
        )

    flagship_flows_raw = blob.get("flagship_flows")
    if (
        not isinstance(flagship_flows_raw, list)
        or len(flagship_flows_raw) != EXPECTED_FLAGSHIP_FLOWS_COUNT
    ):
        return _block(
            _token("BLOCKED_FLAGSHIP_COUNT_MISMATCH"),
            f"flagship_flows length={len(flagship_flows_raw) if isinstance(flagship_flows_raw, list) else 'absent'} (expected {EXPECTED_FLAGSHIP_FLOWS_COUNT})",
        )
    flagship_count = _as_int(blob.get("flagship_flows_certified_count", 0))
    if flagship_count != EXPECTED_FLAGSHIP_FLOWS_COUNT:
        return _block(
            _token("BLOCKED_FLAGSHIP_COUNT_MISMATCH"),
            f"flagship_flows_certified_count={flagship_count} (expected {EXPECTED_FLAGSHIP_FLOWS_COUNT})",
        )

    scanner = blob.get("false_claim_scanner_model") or {}
    phrases = scanner.get("blocked_or_flagged_phrases") or []
    if not isinstance(phrases, list) or len(phrases) != EXPECTED_FALSE_CLAIM_PHRASES_COUNT:
        return _block(
            _token("BLOCKED_SCANNER_COUNT_MISMATCH"),
            f"false_claim_scanner_model.blocked_or_flagged_phrases length="
            f"{len(phrases) if isinstance(phrases, list) else 'absent'} (expected "
            f"{EXPECTED_FALSE_CLAIM_PHRASES_COUNT})",
        )

    proof_report = blob.get("proof_report_model") or {}
    fields = proof_report.get("fields") or []
    if not isinstance(fields, list) or len(fields) != EXPECTED_PROOF_REPORT_FIELDS_COUNT:
        return _block(
            _token("BLOCKED_PROOF_REPORT_FIELDS_COUNT_MISMATCH"),
            f"proof_report_model.fields length={len(fields) if isinstance(fields, list) else 'absent'} "
            f"(expected {EXPECTED_PROOF_REPORT_FIELDS_COUNT})",
        )

    release_support_status = blob.get("release_support_status") or {}
    release_cells = _as_int(release_support_status.get("release_supported_cells", 0))
    release_families = _as_int(release_support_status.get("release_supported_families", 0))
    if release_cells != 0 or release_families != 0:
        return _block(
            _token("BLOCKED_RELEASE_OVERCLAIM"),
            f"release_supported_cells={release_cells}, release_supported_families={release_families}",
        )

    hits: set[str] = set()
    _walk_strings_for_forbidden(blob, hits)
    if hits:
        return _block(
            _token("BLOCKED_BROAD_CLAIM"),
            f"forbidden broad-claim phrases: {sorted(hits)}",
        )

    flagship_flows = tuple(_flow_row(f) for f in flagship_flows_raw if isinstance(f, dict))
    unknown = blob.get("unknown_novel_route_status") or {}
    validation = blob.get("validation") or {}

    return PublicTidalWaveFlagshipFlowCertificationStatus(
        decision=_token("PASSED"),
        target_surface="Public Tidal Wave Flagship Flow Certification",
        target_workflow=str(
            blob.get("target_workflow") or "public tidal wave flagship flow certification"
        ),
        lock_id=LOCK_ID,
        source_truth_lock_id=SOURCE_TRUTH_LOCK_ID,
        source_truth_commit=SOURCE_TRUTH_COMMIT,
        artifact_path=_relative_to_repo(chosen),
        status_artifact_path=str(blob.get("status_artifact_path") or ""),
        flagship_flows_certified_count=flagship_count,
        flagship_flows=flagship_flows,
        false_claim_phrases_count=len(phrases),
        proof_report_fields_count=len(fields),
        release_supported_cells=release_cells,
        release_supported_families=release_families,
        release_support_unchanged_at_zero=bool(
            release_support_status.get("release_support_unchanged_at_zero", False)
        ),
        universal_support_claimed=False,
        universal_handling_certified_as_journey_model=bool(
            authority_boundary.get("universal_handling_certified_as_journey_model", False)
        ),
        source_mutation_authorized=False,
        real_user_source_mutation_authorized=False,
        proof_execution_authority_granted=False,
        training_eligible=False,
        broad_claims_granted=False,
        unknown_novel_cell_id=str(unknown.get("cell_id") or ""),
        unknown_novel_claim_state=str(unknown.get("claim_state") or ""),
        unknown_novel_missing_rung_key=str(unknown.get("missing_rung_key") or ""),
        unknown_novel_route_status=str(unknown.get("route_status") or ""),
        unknown_novel_support_claimed=bool(unknown.get("support_claimed", False)),
        validation_passed=bool(validation.get("passed", False)),
        validation_errors=tuple(str(e) for e in (validation.get("errors") or [])),
        evidence_ref=_relative_to_repo(chosen),
        captions=REQUIRED_PANEL_CAPTIONS,
        notes=(),
    )


__all__ = [
    "load",
    "FlagshipFlowRow",
    "PublicTidalWaveFlagshipFlowCertificationStatus",
    "REQUIRED_PANEL_CAPTIONS",
    "EXPECTED_STATUS",
    "LOCK_ID",
    "EXPECTED_FLAGSHIP_FLOWS_COUNT",
    "EXPECTED_FALSE_CLAIM_PHRASES_COUNT",
    "EXPECTED_PROOF_REPORT_FIELDS_COUNT",
    "SOURCE_TRUTH_LOCK_ID",
    "SOURCE_TRUTH_COMMIT",
]
