from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_ROOT / "scripts"))

from corpus.programbench.artifact_source_escalation import (  # noqa: E402
    ArtifactSourceEscalationConfig,
    ArtifactSourceEscalationStatus,
    ProgramBenchArtifactSourceEscalation,
)
from corpus.programbench.artifact_source_escalation_record import (
    verify_artifact_source_escalation_record,  # noqa: E402
)
from corpus.programbench.infra_failure_triage import InfraFailureTriageStatus  # noqa: E402
from corpus.programbench.infra_failure_triage_record import (  # noqa: E402
    make_infra_failure_triage_record,
    write_infra_failure_triage_record,
)
from corpus.programbench.operator_artifact_admission_record import (  # noqa: E402
    make_operator_artifact_admission_record,
    write_operator_artifact_admission_record,
)

MISSING_IMAGE = "programbench/doxygen_1776_doxygen.966d98e:task_cleanroom"


def _target() -> dict:
    return {
        "tool": "doxygen__doxygen.966d98e",
        "candidate_id": "close_lock_v7_doxygen_richgo_20260527",
    }


def _triage_path(
    tmp_path: Path,
    *,
    failure_type: str = InfraFailureTriageStatus.MISSING_CLEANROOM_IMAGE.value,
    source_status: str = InfraFailureTriageStatus.IMAGE_RECOVERY_REQUIRES_OPERATOR.value,
) -> Path:
    record = make_infra_failure_triage_record(
        status=InfraFailureTriageStatus.INFRA_FAILURE_TRIAGED.value,
        source_record="real.json",
        packet_id="doxygen_real_bounded_rerun_20260527",
        target=_target(),
        failure_type=failure_type,
        missing_image=MISSING_IMAGE,
        local_image_status=InfraFailureTriageStatus.IMAGE_MISSING_LOCAL.value,
        source_status=source_status,
        provenance_status=InfraFailureTriageStatus.IMAGE_HYDRATION_BLOCKED_NO_PROVENANCE.value,
    )
    return write_infra_failure_triage_record(record, tmp_path / "triage")


def _escalator(tmp_path: Path):
    return ProgramBenchArtifactSourceEscalation(
        ArtifactSourceEscalationConfig(
            root=tmp_path,
            output_dir=tmp_path / "escalations",
            admission_roots=[tmp_path / "admissions"],
        )
    )


def _admission(tmp_path: Path, *, fixture: bool) -> Path:
    operator_id = "lock_fixture" if fixture else "ryan"
    source = (
        "fixture://programbench/doxygen/task_cleanroom"
        if fixture
        else "registry.internal/programbench/doxygen"
    )
    reason = "fixture admission" if fixture else "real operator supplied provenance"
    record = make_operator_artifact_admission_record(
        status="OPERATOR_ARTIFACT_ADMISSION_ACCEPTED",
        triage_record="triage.json",
        image_reference=MISSING_IMAGE,
        target=_target(),
        admission_statuses=[
            "OPERATOR_ARTIFACT_ADMISSION_ACCEPTED",
            "OPERATOR_ARTIFACT_HYDRATION_CANDIDATE",
            "OPERATOR_ARTIFACT_NOT_EXECUTABLE",
        ],
        operator_claim={
            "image_reference": MISSING_IMAGE,
            "digest": "sha256:" + "a" * 64,
            "operator_id": operator_id,
            "source_url_or_registry": source,
            "admission_reason": reason,
            "license_provenance_notes": reason,
        },
        hydration_candidate=True,
        executable=False,
    )
    return write_operator_artifact_admission_record(record, tmp_path / "admissions")


def test_missing_real_provenance_generates_operator_checklist(tmp_path):
    result = _escalator(tmp_path).escalate(_triage_path(tmp_path))

    record = result["record"]
    assert (
        record["status"] == ArtifactSourceEscalationStatus.ARTIFACT_SOURCE_ESCALATION_WRITTEN.value
    )
    assert (
        ArtifactSourceEscalationStatus.MISSING_REAL_PROVENANCE.value
        in record["escalation_statuses"]
    )
    assert any(MISSING_IMAGE in item for item in record["operator_checklist"])


def test_missing_triage_blocks_escalation(tmp_path):
    result = _escalator(tmp_path).escalate(tmp_path / "missing.triage.json")

    assert (
        result["record"]["status"]
        == ArtifactSourceEscalationStatus.ARTIFACT_SOURCE_ESCALATION_BLOCKED_NO_TRIAGE.value
    )


def test_non_missing_image_triage_blocks(tmp_path):
    result = _escalator(tmp_path).escalate(_triage_path(tmp_path, failure_type="MISSING_TASK_ROOT"))

    assert (
        result["record"]["status"]
        == ArtifactSourceEscalationStatus.ARTIFACT_SOURCE_ESCALATION_BLOCKED_NO_TRIAGE.value
    )


def test_triage_not_requiring_operator_recovery_blocks(tmp_path):
    result = _escalator(tmp_path).escalate(
        _triage_path(
            tmp_path,
            source_status=InfraFailureTriageStatus.IMAGE_SOURCE_EXACT_REFERENCE_FOUND.value,
        )
    )

    assert result["record"]["status"] == (
        ArtifactSourceEscalationStatus.ARTIFACT_SOURCE_ESCALATION_BLOCKED_NOT_OPERATOR_RECOVERY.value
    )


def test_fixture_admission_is_ignored_for_real_hydration(tmp_path):
    _admission(tmp_path, fixture=True)

    result = _escalator(tmp_path).escalate(_triage_path(tmp_path))

    assert (
        ArtifactSourceEscalationStatus.FIXTURE_ADMISSION_IGNORED.value
        in result["record"]["escalation_statuses"]
    )
    assert (
        ArtifactSourceEscalationStatus.MISSING_REAL_PROVENANCE.value
        in result["record"]["escalation_statuses"]
    )


def test_real_admission_marks_escalation_not_required(tmp_path):
    _admission(tmp_path, fixture=False)

    result = _escalator(tmp_path).escalate(_triage_path(tmp_path))

    assert (
        ArtifactSourceEscalationStatus.ARTIFACT_SOURCE_ESCALATION_NOT_REQUIRED_REAL_ADMISSION_EXISTS.value
        in result["record"]["escalation_statuses"]
    )


def test_required_provenance_fields_are_listed(tmp_path):
    result = _escalator(tmp_path).escalate(_triage_path(tmp_path))

    assert "image_reference" in result["record"]["required_provenance_fields"]
    assert "digest or immutable_revision" in result["record"]["required_provenance_fields"]
    assert "license/provenance notes" in result["record"]["required_provenance_fields"]


def test_accepted_and_rejected_forms_are_listed(tmp_path):
    result = _escalator(tmp_path).escalate(_triage_path(tmp_path))

    assert "registry reference pinned by digest" in result["record"]["accepted_forms"]
    assert "latest tag" in result["record"]["rejected_forms"]
    assert "unverified public image" in result["record"]["rejected_forms"]


def test_escalation_never_authorizes_hydration_or_execution(tmp_path):
    result = _escalator(tmp_path).escalate(_triage_path(tmp_path))

    assert result["record"]["hydration_authorized"] is False
    assert result["record"]["executable"] is False
    assert (
        ArtifactSourceEscalationStatus.NO_HYDRATION_AUTHORIZED.value
        in result["record"]["escalation_statuses"]
    )
    assert (
        ArtifactSourceEscalationStatus.NO_EXECUTION_AUTHORIZED.value
        in result["record"]["escalation_statuses"]
    )


def test_escalation_is_not_training_eligible(tmp_path):
    result = _escalator(tmp_path).escalate(_triage_path(tmp_path))

    assert result["record"]["training_eligible"] is False
    assert result["record"]["record_status"] == "active_eval_evidence"


def test_signed_escalation_record_is_produced(tmp_path):
    result = _escalator(tmp_path).escalate(_triage_path(tmp_path))

    assert Path(result["record_path"]).is_file()
    assert verify_artifact_source_escalation_record(result["record"])
