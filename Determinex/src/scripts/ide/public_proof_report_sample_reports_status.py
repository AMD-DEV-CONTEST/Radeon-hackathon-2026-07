"""Public Proof Report Sample Reports status loader.

DETERMINEX_REACT_PUBLIC_PROOF_REPORT_SAMPLE_REPORTS_BINDING_LOCK_001.

load() reads the Codex public proof report sample-reports evidence and
returns a render-safe view-model the React panel can display. The 5
sample reports exercise the export contract across all archetype
report shapes (supported, blocked-by-missing-rung, authority-gated,
unknown/novel, refused/contained).

The panel DISPLAYS evidence; it does NOT grant authority. Sample
reports are evidence-shape examples, NOT promises of runtime support,
release readiness, or universal coverage.

Hard rules enforced by load():

  * sample-report artifact absent / unparseable -> AWAITING_EVIDENCE
  * status != PUBLIC_PROOF_REPORT_EXPORT_PASSED -> BLOCKED_MALFORMED
  * sample_reports list length != 5 -> BLOCKED_SAMPLE_COUNT_MISMATCH
  * sample_reports_count field != 5 -> BLOCKED_SAMPLE_COUNT_MISMATCH
  * any sample's authority_state has a truthy authority flag ->
    BLOCKED_AUTHORITY_CONFUSION
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
_EVIDENCE_FILE = (
    _REPO_ROOT
    / "assurance"
    / "evidence"
    / "public_proof_report_export"
    / "proof_report_sample_reports_20260529.json"
)
EXPECTED_STATUS = "PUBLIC_PROOF_REPORT_EXPORT_PASSED"
LOCK_ID = "DETERMINEX_REACT_PUBLIC_PROOF_REPORT_SAMPLE_REPORTS_BINDING_LOCK_001"
EXPECTED_SAMPLE_COUNT = 5
EXPECTED_ROUTE_OUTCOMES = (
    "fixture_local_supported_flow",
    "blocked_by_missing_rung",
    "blocked_by_missing_authority",
    "unknown_novel_request",
    "refused_or_contained_unsafe_request",
)
SOURCE_TRUTH_LOCK_ID = "DETERMINEX_PUBLIC_PROOF_REPORT_EXPORT_LOCK_001"
SOURCE_TRUTH_COMMIT = "ed8a50ff2"

DECISION_PREFIX = "REACT_PUBLIC_PROOF_REPORT_SAMPLE_REPORTS_BINDING"


def _token(suffix: str) -> str:
    return f"{DECISION_PREFIX}_{suffix}"


def _as_int(v) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


REQUIRED_PANEL_CAPTIONS = (
    "This panel displays evidence; it does not grant authority.",
    "Sample reports are evidence-shape examples; they are not promises "
    "of runtime support, release readiness, or universal coverage.",
    "Each sample carries its own authority_state; all authority flags remain false.",
    "Release-supported remains 0 cells / 0 families.",
    "Universal support is not claimed.",
    "Unknown/novel sample remains NOT_CLAIMED, blocked by CONCRETE_FIXTURE_REQUIRED.",
    "Refused/contained sample remains refused; no execution authorized.",
)


@dataclass(frozen=True)
class SampleReportRow:
    detected_request_class: str
    user_request_summary: str
    actions_attempted: tuple[str, ...]
    actions_skipped: tuple[str, ...]
    checks_run: tuple[str, ...]
    checks_passed: tuple[str, ...]
    checks_failed: tuple[str, ...]
    evidence_artifacts: tuple[str, ...]
    blockers: tuple[str, ...]
    missing_rungs: tuple[str, ...]
    user_claims_allowed: tuple[str, ...]
    user_claims_forbidden: tuple[str, ...]
    next_safe_steps: tuple[str, ...]
    support_depth_before: str
    support_depth_after: str
    commercial_license_notice: str
    privacy_training_notice: str


@dataclass(frozen=True)
class PublicProofReportSampleReportsStatus:
    decision: str
    target_surface: str
    target_workflow: str
    lock_id: str
    source_truth_lock_id: str
    source_truth_commit: str
    artifact_path: str
    sample_reports_count: int
    sample_reports: tuple[SampleReportRow, ...]
    detected_request_classes: tuple[str, ...]
    release_supported_cells: int
    release_supported_families: int
    source_mutation_authorized: bool
    real_user_source_mutation_authorized: bool
    proof_execution_authority_granted: bool
    training_eligible: bool
    broad_claims_granted: bool
    evidence_ref: str
    captions: tuple[str, ...]
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["sample_reports"] = [asdict(s) for s in self.sample_reports]
        for k in ("detected_request_classes", "captions", "notes"):
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


def _sample_row(s: dict) -> SampleReportRow:
    def _list(k: str) -> tuple[str, ...]:
        return tuple(str(x) for x in (s.get(k) or []))

    return SampleReportRow(
        detected_request_class=str(s.get("detected_request_class") or ""),
        user_request_summary=str(s.get("user_request_summary") or ""),
        actions_attempted=_list("actions_attempted"),
        actions_skipped=_list("actions_skipped"),
        checks_run=_list("checks_run"),
        checks_passed=_list("checks_passed"),
        checks_failed=_list("checks_failed"),
        evidence_artifacts=_list("evidence_artifacts"),
        blockers=_list("blockers"),
        missing_rungs=_list("missing_rungs"),
        user_claims_allowed=_list("user_claims_allowed"),
        user_claims_forbidden=_list("user_claims_forbidden"),
        next_safe_steps=_list("next_safe_steps"),
        support_depth_before=str(s.get("support_depth_before") or ""),
        support_depth_after=str(s.get("support_depth_after") or ""),
        commercial_license_notice=str(s.get("commercial_license_notice") or ""),
        privacy_training_notice=str(s.get("privacy_training_notice") or ""),
    )


def _shell(*, decision: str, note: str) -> PublicProofReportSampleReportsStatus:
    return PublicProofReportSampleReportsStatus(
        decision=decision,
        target_surface="Public Proof Report Sample Reports",
        target_workflow="(awaiting evidence)" if "AWAITING" in decision else "(blocked)",
        lock_id=LOCK_ID,
        source_truth_lock_id=SOURCE_TRUTH_LOCK_ID,
        source_truth_commit=SOURCE_TRUTH_COMMIT,
        artifact_path="",
        sample_reports_count=0,
        sample_reports=(),
        detected_request_classes=(),
        release_supported_cells=0,
        release_supported_families=0,
        source_mutation_authorized=False,
        real_user_source_mutation_authorized=False,
        proof_execution_authority_granted=False,
        training_eligible=False,
        broad_claims_granted=False,
        evidence_ref="",
        captions=REQUIRED_PANEL_CAPTIONS,
        notes=(note,),
    )


def _awaiting(note: str) -> PublicProofReportSampleReportsStatus:
    return _shell(decision=_token("AWAITING_EVIDENCE"), note=note)


def _block(decision: str, note: str) -> PublicProofReportSampleReportsStatus:
    return _shell(decision=decision, note=note)


def _relative_to_repo(path: Path) -> str:
    try:
        return path.resolve().relative_to(_REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def load(
    sample_reports_path: Path | str | None = None,
) -> PublicProofReportSampleReportsStatus:
    chosen = Path(sample_reports_path) if sample_reports_path else _EVIDENCE_FILE
    if not chosen.is_file():
        return _awaiting(f"sample reports artifact absent at {chosen}")
    try:
        blob = json.loads(chosen.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return _awaiting(f"could not read sample reports artifact: {exc}")

    if blob.get("status") != EXPECTED_STATUS:
        return _block(
            _token("BLOCKED_MALFORMED"),
            f"sample-report artifact status={blob.get('status')!r} (expected {EXPECTED_STATUS})",
        )

    samples_raw = blob.get("sample_reports")
    if not isinstance(samples_raw, list) or len(samples_raw) != EXPECTED_SAMPLE_COUNT:
        return _block(
            _token("BLOCKED_SAMPLE_COUNT_MISMATCH"),
            f"sample_reports length="
            f"{len(samples_raw) if isinstance(samples_raw, list) else 'absent'} "
            f"(expected {EXPECTED_SAMPLE_COUNT})",
        )
    count_field = _as_int(blob.get("sample_reports_count", 0))
    if count_field != EXPECTED_SAMPLE_COUNT:
        return _block(
            _token("BLOCKED_SAMPLE_COUNT_MISMATCH"),
            f"sample_reports_count={count_field} (expected {EXPECTED_SAMPLE_COUNT})",
        )

    for i, s in enumerate(samples_raw):
        if not isinstance(s, dict):
            return _block(
                _token("BLOCKED_MALFORMED"),
                f"sample_reports[{i}] is not a dict",
            )
        astate = s.get("authority_state") or {}
        for flag in (
            "release_ready",
            "training_eligible",
            "training_rows_written",
            "source_mutation_authorized",
            "real_user_source_mutation_authorized",
            "approval_authority_granted",
            "proof_execution_authority_granted",
            "broad_claims_granted",
            "release_deploy_workflow_created",
        ):
            if astate.get(flag) is True:
                return _block(
                    _token("BLOCKED_AUTHORITY_CONFUSION"),
                    f"sample_reports[{i}].authority_state.{flag} is true",
                )

    hits: set[str] = set()
    _walk_strings_for_forbidden(blob, hits)
    if hits:
        return _block(
            _token("BLOCKED_BROAD_CLAIM"),
            f"forbidden broad-claim phrases: {sorted(hits)}",
        )

    samples = tuple(_sample_row(s) for s in samples_raw)
    classes = tuple(s.detected_request_class for s in samples)

    return PublicProofReportSampleReportsStatus(
        decision=_token("PASSED"),
        target_surface="Public Proof Report Sample Reports",
        target_workflow="public proof report sample reports",
        lock_id=LOCK_ID,
        source_truth_lock_id=SOURCE_TRUTH_LOCK_ID,
        source_truth_commit=SOURCE_TRUTH_COMMIT,
        artifact_path=_relative_to_repo(chosen),
        sample_reports_count=count_field,
        sample_reports=samples,
        detected_request_classes=classes,
        release_supported_cells=0,
        release_supported_families=0,
        source_mutation_authorized=False,
        real_user_source_mutation_authorized=False,
        proof_execution_authority_granted=False,
        training_eligible=False,
        broad_claims_granted=False,
        evidence_ref=_relative_to_repo(chosen),
        captions=REQUIRED_PANEL_CAPTIONS,
        notes=(),
    )


__all__ = [
    "load",
    "SampleReportRow",
    "PublicProofReportSampleReportsStatus",
    "REQUIRED_PANEL_CAPTIONS",
    "EXPECTED_STATUS",
    "LOCK_ID",
    "EXPECTED_SAMPLE_COUNT",
    "EXPECTED_ROUTE_OUTCOMES",
    "SOURCE_TRUTH_LOCK_ID",
    "SOURCE_TRUTH_COMMIT",
]
