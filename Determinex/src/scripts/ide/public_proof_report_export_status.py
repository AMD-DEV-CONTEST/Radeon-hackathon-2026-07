"""Public Proof Report Export status loader.

DETERMINEX_REACT_PUBLIC_PROOF_REPORT_EXPORT_BINDING_LOCK_001.

load() reads the Codex public proof report export evidence and returns
a render-safe view-model the React panel can display. Surfaces the
proof report contract (25 fields, 11 forbidden claims) plus the 5
sample reports and 7 route outcomes.

The panel DISPLAYS evidence; it does NOT grant authority. The proof
report export is an evidence/reporting contract; it is NOT release
readiness, runtime execution proof, or universal support.

Hard rules enforced by load():

  * status != PUBLIC_PROOF_REPORT_EXPORT_PASSED -> BLOCKED_MALFORMED
  * authority bag flag true -> BLOCKED_AUTHORITY_CONFUSION
  * broad_claims_granted true -> BLOCKED_BROAD_CLAIM
  * proof_report_fields_count != 25 -> BLOCKED_FIELD_COUNT_MISMATCH
  * contract.fields length != 25 -> BLOCKED_FIELD_COUNT_MISMATCH
  * sample_reports_count != 5 -> BLOCKED_SAMPLE_COUNT_MISMATCH
  * route_outcomes_count != 7 -> BLOCKED_ROUTE_COUNT_MISMATCH
  * forbidden_report_claims_blocked_count != 11 ->
    BLOCKED_FORBIDDEN_COUNT_MISMATCH
  * contract.forbidden_report_claims length != 11 ->
    BLOCKED_FORBIDDEN_COUNT_MISMATCH
  * release_supported_cells / release_supported_families != 0 ->
    BLOCKED_RELEASE_OVERCLAIM
  * exportability_boundary.proof_report_export_is_not_release_readiness
    != True -> BLOCKED_BROAD_CLAIM
  * exportability_boundary.report_schema_does_not_equal_runtime_proof
    != True -> BLOCKED_BROAD_CLAIM
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
_EVIDENCE_DIR = _REPO_ROOT / "assurance" / "evidence" / "public_proof_report_export"
EXPECTED_STATUS = "PUBLIC_PROOF_REPORT_EXPORT_PASSED"
LOCK_ID = "DETERMINEX_REACT_PUBLIC_PROOF_REPORT_EXPORT_BINDING_LOCK_001"
EXPECTED_FIELDS_COUNT = 25
EXPECTED_SAMPLE_COUNT = 5
EXPECTED_ROUTE_COUNT = 7
EXPECTED_FORBIDDEN_COUNT = 11
SOURCE_TRUTH_LOCK_ID = "DETERMINEX_PUBLIC_PROOF_REPORT_EXPORT_LOCK_001"
SOURCE_TRUTH_COMMIT = "ed8a50ff2"

DECISION_PREFIX = "REACT_PUBLIC_PROOF_REPORT_EXPORT_BINDING"


def _token(suffix: str) -> str:
    return f"{DECISION_PREFIX}_{suffix}"


def _as_int(v) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


REQUIRED_PANEL_CAPTIONS = (
    "This panel displays evidence; it does not grant authority.",
    "Proof report export is an evidence/reporting contract. It is not "
    "release readiness, runtime execution proof, or universal support.",
    "Release-supported remains 0 cells / 0 families.",
    "Universal support is not claimed.",
    "Report schema does not equal runtime proof.",
    "Forbidden report claims remain blocked or flagged.",
    "Unknown/novel routing is not arbitrary app support.",
)


@dataclass(frozen=True)
class ContractFieldRow:
    field_name: str
    required: bool


@dataclass(frozen=True)
class PublicProofReportExportStatus:
    decision: str
    target_surface: str
    target_workflow: str
    lock_id: str
    source_truth_lock_id: str
    source_truth_commit: str
    artifact_path: str
    status_artifact_path: str
    contract_path: str
    sample_reports_path: str
    claim_boundary_path: str
    docs_path: str
    proof_report_fields_count: int
    sample_reports_count: int
    route_outcomes_count: int
    forbidden_report_claims_blocked_count: int
    contract_fields: tuple[ContractFieldRow, ...]
    allowed_report_claims: tuple[str, ...]
    forbidden_report_claims: tuple[str, ...]
    release_supported_cells: int
    release_supported_families: int
    release_support_unchanged_at_zero: bool
    proof_report_export_is_release_readiness: bool
    report_schema_is_runtime_execution_proof: bool
    proof_report_export_is_not_release_readiness: bool
    report_schema_does_not_equal_runtime_proof: bool
    source_mutation_authorized: bool
    real_user_source_mutation_authorized: bool
    proof_execution_authority_granted: bool
    training_eligible: bool
    broad_claims_granted: bool
    unknown_novel_cell_id: str
    unknown_novel_claim_state: str
    unknown_novel_missing_rung_key: str
    unknown_novel_route_status: str
    unknown_novel_blocker_remains_concrete_fixture_required: bool
    validation_passed: bool
    validation_errors: tuple[str, ...]
    evidence_ref: str
    captions: tuple[str, ...]
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["contract_fields"] = [asdict(c) for c in self.contract_fields]
        for k in (
            "allowed_report_claims",
            "forbidden_report_claims",
            "validation_errors",
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


def _shell(*, decision: str, note: str) -> PublicProofReportExportStatus:
    return PublicProofReportExportStatus(
        decision=decision,
        target_surface="Public Proof Report Export",
        target_workflow="(awaiting evidence)" if "AWAITING" in decision else "(blocked)",
        lock_id=LOCK_ID,
        source_truth_lock_id=SOURCE_TRUTH_LOCK_ID,
        source_truth_commit=SOURCE_TRUTH_COMMIT,
        artifact_path="",
        status_artifact_path="",
        contract_path="",
        sample_reports_path="",
        claim_boundary_path="",
        docs_path="docs/DETERMINEX_PUBLIC_PROOF_REPORT_EXPORT.md",
        proof_report_fields_count=0,
        sample_reports_count=0,
        route_outcomes_count=0,
        forbidden_report_claims_blocked_count=0,
        contract_fields=(),
        allowed_report_claims=(),
        forbidden_report_claims=(),
        release_supported_cells=0,
        release_supported_families=0,
        release_support_unchanged_at_zero=False,
        proof_report_export_is_release_readiness=False,
        report_schema_is_runtime_execution_proof=False,
        proof_report_export_is_not_release_readiness=False,
        report_schema_does_not_equal_runtime_proof=False,
        source_mutation_authorized=False,
        real_user_source_mutation_authorized=False,
        proof_execution_authority_granted=False,
        training_eligible=False,
        broad_claims_granted=False,
        unknown_novel_cell_id="",
        unknown_novel_claim_state="",
        unknown_novel_missing_rung_key="",
        unknown_novel_route_status="",
        unknown_novel_blocker_remains_concrete_fixture_required=False,
        validation_passed=False,
        validation_errors=(),
        evidence_ref="",
        captions=REQUIRED_PANEL_CAPTIONS,
        notes=(note,),
    )


def _awaiting(note: str) -> PublicProofReportExportStatus:
    return _shell(decision=_token("AWAITING_EVIDENCE"), note=note)


def _block(decision: str, note: str) -> PublicProofReportExportStatus:
    return _shell(decision=decision, note=note)


def _relative_to_repo(path: Path) -> str:
    try:
        return path.resolve().relative_to(_REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def load(
    evidence_dir: Path | str | None = None,
) -> PublicProofReportExportStatus:
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

    contract = blob.get("proof_report_export_contract") or {}
    contract_fields_raw = contract.get("fields") or []
    if (
        not isinstance(contract_fields_raw, list)
        or len(contract_fields_raw) != EXPECTED_FIELDS_COUNT
    ):
        return _block(
            _token("BLOCKED_FIELD_COUNT_MISMATCH"),
            f"contract.fields length="
            f"{len(contract_fields_raw) if isinstance(contract_fields_raw, list) else 'absent'} "
            f"(expected {EXPECTED_FIELDS_COUNT})",
        )
    fields_count = _as_int(blob.get("proof_report_fields_count", 0))
    if fields_count != EXPECTED_FIELDS_COUNT:
        return _block(
            _token("BLOCKED_FIELD_COUNT_MISMATCH"),
            f"proof_report_fields_count={fields_count} (expected {EXPECTED_FIELDS_COUNT})",
        )

    samples_count = _as_int(blob.get("sample_reports_count", 0))
    if samples_count != EXPECTED_SAMPLE_COUNT:
        return _block(
            _token("BLOCKED_SAMPLE_COUNT_MISMATCH"),
            f"sample_reports_count={samples_count} (expected {EXPECTED_SAMPLE_COUNT})",
        )

    routes_count = _as_int(blob.get("route_outcomes_count", 0))
    if routes_count != EXPECTED_ROUTE_COUNT:
        return _block(
            _token("BLOCKED_ROUTE_COUNT_MISMATCH"),
            f"route_outcomes_count={routes_count} (expected {EXPECTED_ROUTE_COUNT})",
        )

    forbidden_count = _as_int(blob.get("forbidden_report_claims_blocked_count", 0))
    if forbidden_count != EXPECTED_FORBIDDEN_COUNT:
        return _block(
            _token("BLOCKED_FORBIDDEN_COUNT_MISMATCH"),
            f"forbidden_report_claims_blocked_count={forbidden_count} (expected {EXPECTED_FORBIDDEN_COUNT})",
        )
    forbidden_raw = contract.get("forbidden_report_claims") or []
    if not isinstance(forbidden_raw, list) or len(forbidden_raw) != EXPECTED_FORBIDDEN_COUNT:
        return _block(
            _token("BLOCKED_FORBIDDEN_COUNT_MISMATCH"),
            f"contract.forbidden_report_claims length="
            f"{len(forbidden_raw) if isinstance(forbidden_raw, list) else 'absent'} "
            f"(expected {EXPECTED_FORBIDDEN_COUNT})",
        )

    release_support_status = blob.get("release_support_status") or {}
    release_cells = _as_int(release_support_status.get("release_supported_cells", 0))
    release_families = _as_int(release_support_status.get("release_supported_families", 0))
    if release_cells != 0 or release_families != 0:
        return _block(
            _token("BLOCKED_RELEASE_OVERCLAIM"),
            f"release_supported_cells={release_cells}, release_supported_families={release_families}",
        )

    exportability = blob.get("exportability_boundary") or {}
    if exportability.get("proof_report_export_is_not_release_readiness") is not True:
        return _block(
            _token("BLOCKED_BROAD_CLAIM"),
            "exportability_boundary.proof_report_export_is_not_release_readiness is not True",
        )
    if exportability.get("report_schema_does_not_equal_runtime_proof") is not True:
        return _block(
            _token("BLOCKED_BROAD_CLAIM"),
            "exportability_boundary.report_schema_does_not_equal_runtime_proof is not True",
        )

    authority_boundary = blob.get("authority_boundary") or {}
    if authority_boundary.get("proof_report_export_is_release_readiness") is not False:
        return _block(
            _token("BLOCKED_BROAD_CLAIM"),
            "authority_boundary.proof_report_export_is_release_readiness must be False",
        )
    if authority_boundary.get("report_schema_is_runtime_execution_proof") is not False:
        return _block(
            _token("BLOCKED_BROAD_CLAIM"),
            "authority_boundary.report_schema_is_runtime_execution_proof must be False",
        )

    hits: set[str] = set()
    _walk_strings_for_forbidden(blob, hits)
    if hits:
        return _block(
            _token("BLOCKED_BROAD_CLAIM"),
            f"forbidden broad-claim phrases: {sorted(hits)}",
        )

    contract_fields = tuple(
        ContractFieldRow(
            field_name=str(f.get("field") or ""),
            required=bool(f.get("required", True)),
        )
        for f in contract_fields_raw
        if isinstance(f, dict)
    )
    allowed_raw = contract.get("allowed_report_claims") or []
    unknown = blob.get("unknown_novel_route_status") or {}
    validation = blob.get("validation") or {}

    return PublicProofReportExportStatus(
        decision=_token("PASSED"),
        target_surface="Public Proof Report Export",
        target_workflow=str(blob.get("target_workflow") or "public proof report export"),
        lock_id=LOCK_ID,
        source_truth_lock_id=SOURCE_TRUTH_LOCK_ID,
        source_truth_commit=SOURCE_TRUTH_COMMIT,
        artifact_path=_relative_to_repo(chosen),
        status_artifact_path=str(blob.get("status_artifact_path") or ""),
        contract_path=str(blob.get("proof_report_contract_path") or ""),
        sample_reports_path=str(blob.get("sample_report_path") or ""),
        claim_boundary_path=str(blob.get("claim_boundary_path") or ""),
        docs_path="docs/DETERMINEX_PUBLIC_PROOF_REPORT_EXPORT.md",
        proof_report_fields_count=fields_count,
        sample_reports_count=samples_count,
        route_outcomes_count=routes_count,
        forbidden_report_claims_blocked_count=forbidden_count,
        contract_fields=contract_fields,
        allowed_report_claims=tuple(str(x) for x in allowed_raw),
        forbidden_report_claims=tuple(str(x) for x in forbidden_raw),
        release_supported_cells=release_cells,
        release_supported_families=release_families,
        release_support_unchanged_at_zero=bool(
            release_support_status.get("release_support_unchanged_at_zero", False)
        ),
        proof_report_export_is_release_readiness=False,
        report_schema_is_runtime_execution_proof=False,
        proof_report_export_is_not_release_readiness=True,
        report_schema_does_not_equal_runtime_proof=True,
        source_mutation_authorized=False,
        real_user_source_mutation_authorized=False,
        proof_execution_authority_granted=False,
        training_eligible=False,
        broad_claims_granted=False,
        unknown_novel_cell_id=str(unknown.get("cell_id") or ""),
        unknown_novel_claim_state=str(unknown.get("claim_state") or ""),
        unknown_novel_missing_rung_key=str(unknown.get("missing_rung_key") or ""),
        unknown_novel_route_status=str(unknown.get("route_status") or ""),
        unknown_novel_blocker_remains_concrete_fixture_required=bool(
            unknown.get("unknown_novel_blocker_remains_concrete_fixture_required", False)
        ),
        validation_passed=bool(validation.get("passed", False)),
        validation_errors=tuple(str(e) for e in (validation.get("errors") or [])),
        evidence_ref=_relative_to_repo(chosen),
        captions=REQUIRED_PANEL_CAPTIONS,
        notes=(),
    )


__all__ = [
    "load",
    "ContractFieldRow",
    "PublicProofReportExportStatus",
    "REQUIRED_PANEL_CAPTIONS",
    "EXPECTED_STATUS",
    "LOCK_ID",
    "EXPECTED_FIELDS_COUNT",
    "EXPECTED_SAMPLE_COUNT",
    "EXPECTED_ROUTE_COUNT",
    "EXPECTED_FORBIDDEN_COUNT",
    "SOURCE_TRUTH_LOCK_ID",
    "SOURCE_TRUTH_COMMIT",
]
