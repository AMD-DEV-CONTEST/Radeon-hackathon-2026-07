from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_ROOT / "scripts"))

from corpus.programbench.infra_failure_triage import InfraFailureTriageStatus  # noqa: E402
from corpus.programbench.infra_failure_triage_record import (  # noqa: E402
    make_infra_failure_triage_record,
    write_infra_failure_triage_record,
)
from corpus.programbench.operator_artifact_admission import (  # noqa: E402
    OperatorArtifactAdmissionConfig,
    OperatorArtifactAdmissionStatus,
    ProgramBenchOperatorArtifactAdmission,
)
from corpus.programbench.operator_artifact_admission_record import (
    verify_operator_artifact_admission_record,  # noqa: E402
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
        source_record="assurance/evidence/programbench_real_bounded_reruns/doxygen.json",
        packet_id="doxygen_real_bounded_rerun_20260527",
        target=_target(),
        failure_type=failure_type,
        missing_image=MISSING_IMAGE,
        local_image_status=InfraFailureTriageStatus.IMAGE_MISSING_LOCAL.value,
        source_status=source_status,
        provenance_status=InfraFailureTriageStatus.IMAGE_HYDRATION_BLOCKED_NO_PROVENANCE.value,
        failure_statuses=[
            failure_type,
            InfraFailureTriageStatus.IMAGE_MISSING_LOCAL.value,
            source_status,
            InfraFailureTriageStatus.IMAGE_HYDRATION_BLOCKED_NO_PROVENANCE.value,
        ],
        evidence={
            "rerun_scope": {
                **_target(),
                "max_attempts": 1,
            }
        },
    )
    return write_infra_failure_triage_record(record, tmp_path / "triage")


def _claim(**overrides) -> dict:
    claim = {
        "image_reference": MISSING_IMAGE,
        "source_type": "trusted_internal",
        "source_url_or_registry": "registry.internal/programbench/doxygen",
        "digest": "sha256:" + "d" * 64,
        "tag": "task_cleanroom",
        "created_at_or_published_at": "2026-05-27T00:00:00+00:00",
        "license_provenance_notes": "Operator-supplied internal ProgramBench cleanroom image provenance.",
        "operator_id": "ryan",
        "intended_scope": {
            **_target(),
            "max_attempts": 1,
        },
        "related_triage_record": "triage/doxygen_real_bounded_rerun_20260527.MISSING_CLEANROOM_IMAGE.triage.json",
        "admission_reason": "Admit exact pinned cleanroom image provenance for Doxygen bounded rerun hydration review.",
    }
    claim.update(overrides)
    return claim


def _admitter(tmp_path: Path):
    return ProgramBenchOperatorArtifactAdmission(
        OperatorArtifactAdmissionConfig(
            root=tmp_path,
            output_dir=tmp_path / "admissions",
        )
    )


def test_valid_operator_admission_with_exact_image_and_digest_is_accepted(tmp_path):
    result = _admitter(tmp_path).admit(_triage_path(tmp_path), _claim())

    record = result["record"]
    assert (
        record["status"]
        == OperatorArtifactAdmissionStatus.OPERATOR_ARTIFACT_ADMISSION_ACCEPTED.value
    )
    assert record["image_reference"] == MISSING_IMAGE


def test_missing_triage_record_blocks(tmp_path):
    result = _admitter(tmp_path).admit(tmp_path / "missing.triage.json", _claim())

    assert (
        result["record"]["status"]
        == OperatorArtifactAdmissionStatus.OPERATOR_ARTIFACT_BLOCKED_NO_TRIAGE.value
    )


def test_non_missing_cleanroom_image_triage_blocks(tmp_path):
    result = _admitter(tmp_path).admit(
        _triage_path(tmp_path, failure_type="MISSING_TASK_ROOT"),
        _claim(),
    )

    assert (
        result["record"]["status"]
        == OperatorArtifactAdmissionStatus.OPERATOR_ARTIFACT_BLOCKED_NO_TRIAGE.value
    )


def test_image_mismatch_blocks(tmp_path):
    result = _admitter(tmp_path).admit(
        _triage_path(tmp_path),
        _claim(image_reference="programbench/other:task_cleanroom"),
    )

    assert (
        result["record"]["status"]
        == OperatorArtifactAdmissionStatus.OPERATOR_ARTIFACT_BLOCKED_IMAGE_MISMATCH.value
    )


def test_scope_mismatch_blocks(tmp_path):
    bad_scope = {
        "tool": "richgo",
        "candidate_id": "close_lock_v7_doxygen_richgo_20260527",
        "max_attempts": 1,
    }
    result = _admitter(tmp_path).admit(_triage_path(tmp_path), _claim(intended_scope=bad_scope))

    assert (
        result["record"]["status"]
        == OperatorArtifactAdmissionStatus.OPERATOR_ARTIFACT_BLOCKED_SCOPE_MISMATCH.value
    )


def test_missing_digest_blocks(tmp_path):
    result = _admitter(tmp_path).admit(
        _triage_path(tmp_path), _claim(digest="", immutable_revision="")
    )

    assert (
        result["record"]["status"]
        == OperatorArtifactAdmissionStatus.OPERATOR_ARTIFACT_BLOCKED_NO_DIGEST.value
    )


def test_latest_floating_tag_without_digest_blocks(tmp_path):
    result = _admitter(tmp_path).admit(_triage_path(tmp_path), _claim(tag="latest", digest=""))

    assert (
        result["record"]["status"]
        == OperatorArtifactAdmissionStatus.OPERATOR_ARTIFACT_BLOCKED_FLOATING_TAG.value
    )


def test_missing_provenance_blocks(tmp_path):
    result = _admitter(tmp_path).admit(
        _triage_path(tmp_path),
        _claim(license_provenance_notes="", provenance_notes=""),
    )

    assert (
        result["record"]["status"]
        == OperatorArtifactAdmissionStatus.OPERATOR_ARTIFACT_BLOCKED_NO_PROVENANCE.value
    )


def test_public_untrusted_direct_hydration_blocks(tmp_path):
    result = _admitter(tmp_path).admit(
        _triage_path(tmp_path),
        _claim(
            source_type="public_untrusted",
            trust_level="public_untrusted",
            requested_use="direct_hydration",
        ),
    )

    assert result["record"]["status"] == (
        OperatorArtifactAdmissionStatus.OPERATOR_ARTIFACT_BLOCKED_PUBLIC_UNTRUSTED_DIRECT_HYDRATION.value
    )


def test_accepted_admission_becomes_hydration_candidate_only(tmp_path):
    result = _admitter(tmp_path).admit(_triage_path(tmp_path), _claim())

    assert result["record"]["hydration_candidate"] is True
    assert (
        OperatorArtifactAdmissionStatus.OPERATOR_ARTIFACT_HYDRATION_CANDIDATE.value
        in result["record"]["admission_statuses"]
    )


def test_accepted_admission_is_not_executable(tmp_path):
    result = _admitter(tmp_path).admit(_triage_path(tmp_path), _claim())

    assert result["record"]["executable"] is False
    assert (
        OperatorArtifactAdmissionStatus.OPERATOR_ARTIFACT_NOT_EXECUTABLE.value
        in result["record"]["admission_statuses"]
    )


def test_accepted_admission_is_not_training_eligible(tmp_path):
    result = _admitter(tmp_path).admit(_triage_path(tmp_path), _claim())

    assert result["record"]["training_eligible"] is False
    assert result["record"]["record_status"] == "active_eval_evidence"


def test_signed_admission_outcome_is_produced(tmp_path):
    result = _admitter(tmp_path).admit(_triage_path(tmp_path), _claim())
    path = Path(result["record_path"])

    assert path.is_file()
    assert verify_operator_artifact_admission_record(result["record"])


def test_triage_not_requiring_operator_recovery_blocks(tmp_path):
    result = _admitter(tmp_path).admit(
        _triage_path(
            tmp_path,
            source_status=InfraFailureTriageStatus.IMAGE_SOURCE_EXACT_REFERENCE_FOUND.value,
        ),
        _claim(),
    )

    assert (
        result["record"]["status"]
        == OperatorArtifactAdmissionStatus.OPERATOR_ARTIFACT_BLOCKED_NO_TRIAGE.value
    )
