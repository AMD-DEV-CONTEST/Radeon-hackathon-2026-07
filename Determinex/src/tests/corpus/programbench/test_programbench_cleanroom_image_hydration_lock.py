from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_ROOT / "scripts"))

from corpus.programbench.cleanroom_image_hydration import (  # noqa: E402
    CleanroomImageHydrationConfig,
    CleanroomImageHydrationStatus,
    ProgramBenchCleanroomImageHydration,
)
from corpus.programbench.cleanroom_image_hydration_record import (
    verify_cleanroom_image_hydration_record,  # noqa: E402
)
from corpus.programbench.operator_artifact_admission_record import (  # noqa: E402
    make_operator_artifact_admission_record,
    write_operator_artifact_admission_record,
)

MISSING_IMAGE = "programbench/doxygen_1776_doxygen.966d98e:task_cleanroom"
DIGEST = "sha256:cc50d0f7e9a1f3f90512e3d4c34781f4686a8fa3774fbff489947ef41bde2e72"


def _target() -> dict:
    return {
        "tool": "doxygen__doxygen.966d98e",
        "candidate_id": "close_lock_v7_doxygen_richgo_20260527",
    }


def _admission_path(
    tmp_path: Path,
    *,
    fixture: bool = False,
    status: str = "OPERATOR_ARTIFACT_ADMISSION_ACCEPTED",
    hydration_candidate: bool = True,
    executable: bool = False,
    training_eligible: bool = False,
    digest: str = DIGEST,
    provenance: str = "Docker Hub exact manifest provenance.",
) -> Path:
    claim = {
        "image_reference": MISSING_IMAGE,
        "source_type": "docker_hub_exact_reference",
        "source_url_or_registry": f"docker.io/programbench/doxygen_1776_doxygen.966d98e@{digest}",
        "digest": digest,
        "tag": "task_cleanroom",
        "license_provenance_notes": provenance,
        "operator_id": "lock_fixture" if fixture else "codex_registry_metadata_lookup",
        "admission_reason": "fixture admission" if fixture else "real manifest admission",
        "requested_use": "hydration_candidate",
    }
    record = make_operator_artifact_admission_record(
        status=status,
        triage_record="triage.json",
        image_reference=MISSING_IMAGE,
        target=_target(),
        admission_statuses=[
            status,
            "OPERATOR_ARTIFACT_HYDRATION_CANDIDATE",
            "OPERATOR_ARTIFACT_NOT_EXECUTABLE",
        ],
        operator_claim=claim,
        hydration_candidate=hydration_candidate,
        executable=executable,
    )
    record["training_eligible"] = training_eligible
    record["record_signature"] = ""
    record = make_operator_artifact_admission_record(
        status=status,
        triage_record="triage.json",
        image_reference=MISSING_IMAGE,
        target=_target(),
        admission_statuses=[
            status,
            "OPERATOR_ARTIFACT_HYDRATION_CANDIDATE",
            "OPERATOR_ARTIFACT_NOT_EXECUTABLE",
        ],
        operator_claim=claim,
        hydration_candidate=hydration_candidate,
        executable=executable,
    )
    if training_eligible:
        record["training_eligible"] = True
        from corpus.programbench.operator_artifact_admission_record import (
            OperatorArtifactAdmissionRecord,  # noqa: PLC0415
        )

        record = OperatorArtifactAdmissionRecord(
            schema_version=record["schema_version"],
            record_type=record["record_type"],
            status=record["status"],
            triage_record=record["triage_record"],
            image_reference=record["image_reference"],
            target=record["target"],
            admission_statuses=record["admission_statuses"],
            operator_claim=record["operator_claim"],
            hydration_candidate=record["hydration_candidate"],
            executable=record["executable"],
            training_eligible=True,
        ).signed()
    return write_operator_artifact_admission_record(record, tmp_path / "admissions")


def _hydrator(tmp_path: Path) -> ProgramBenchCleanroomImageHydration:
    return ProgramBenchCleanroomImageHydration(
        CleanroomImageHydrationConfig(
            root=tmp_path,
            output_dir=tmp_path / "hydration",
            quarantine_dir=tmp_path / "quarantine",
            cache_dir=tmp_path / "cache",
        )
    )


def _scan(**overrides) -> dict:
    scan = {
        "scanner": "fixture-scan",
        "policy": "pass",
        "critical": 0,
        "high": 0,
        "medium": 0,
        "low": 0,
    }
    scan.update(overrides)
    return scan


def _artifact(tmp_path: Path) -> Path:
    path = tmp_path / "image.oci"
    path.write_text("fixture artifact bytes\n", encoding="utf-8")
    return path


def test_fixture_admission_is_blocked_for_real_hydration(tmp_path):
    result = _hydrator(tmp_path).hydrate(_admission_path(tmp_path, fixture=True))

    assert (
        result["record"]["status"]
        == CleanroomImageHydrationStatus.CLEANROOM_IMAGE_BLOCKED_FIXTURE_ADMISSION.value
    )


def test_missing_real_admission_blocks(tmp_path):
    result = _hydrator(tmp_path).hydrate(tmp_path / "missing.json")

    assert (
        result["record"]["status"]
        == CleanroomImageHydrationStatus.CLEANROOM_IMAGE_BLOCKED_NO_REAL_ADMISSION.value
    )


def test_non_hydration_candidate_blocks(tmp_path):
    result = _hydrator(tmp_path).hydrate(_admission_path(tmp_path, hydration_candidate=False))

    assert (
        result["record"]["status"]
        == CleanroomImageHydrationStatus.CLEANROOM_IMAGE_BLOCKED_NON_CANDIDATE.value
    )


def test_missing_digest_blocks(tmp_path):
    result = _hydrator(tmp_path).hydrate(_admission_path(tmp_path, digest=""))

    assert (
        result["record"]["status"]
        == CleanroomImageHydrationStatus.CLEANROOM_IMAGE_BLOCKED_NO_DIGEST.value
    )


def test_missing_provenance_blocks(tmp_path):
    result = _hydrator(tmp_path).hydrate(_admission_path(tmp_path, provenance=""))

    assert (
        result["record"]["status"]
        == CleanroomImageHydrationStatus.CLEANROOM_IMAGE_BLOCKED_NO_PROVENANCE.value
    )


def test_missing_artifact_blocks(tmp_path):
    result = _hydrator(tmp_path).hydrate(_admission_path(tmp_path))

    assert (
        result["record"]["status"]
        == CleanroomImageHydrationStatus.CLEANROOM_IMAGE_BLOCKED_NO_ARTIFACT.value
    )


def test_digest_mismatch_blocks(tmp_path):
    result = _hydrator(tmp_path).hydrate(
        _admission_path(tmp_path),
        artifact_path=_artifact(tmp_path),
        observed_digest="sha256:" + "0" * 64,
        scan_result=_scan(),
    )

    assert (
        result["record"]["status"]
        == CleanroomImageHydrationStatus.CLEANROOM_IMAGE_DIGEST_MISMATCH.value
    )


def test_scan_failure_blocks_policy_admission(tmp_path):
    result = _hydrator(tmp_path).hydrate(
        _admission_path(tmp_path),
        artifact_path=_artifact(tmp_path),
        observed_digest=DIGEST,
        scan_result=_scan(policy="fail", critical=1),
    )

    assert (
        result["record"]["status"]
        == CleanroomImageHydrationStatus.CLEANROOM_IMAGE_SCAN_FAILED.value
    )
    assert (
        result["record"]["policy_result"]
        == CleanroomImageHydrationStatus.CLEANROOM_IMAGE_POLICY_BLOCKED.value
    )


def test_successful_hydration_writes_signed_record(tmp_path):
    result = _hydrator(tmp_path).hydrate(
        _admission_path(tmp_path),
        artifact_path=_artifact(tmp_path),
        observed_digest=DIGEST,
        scan_result=_scan(),
    )

    record = result["record"]
    assert record["status"] == CleanroomImageHydrationStatus.CLEANROOM_IMAGE_CACHE_READY.value
    assert verify_cleanroom_image_hydration_record(record)
    assert Path(result["record_path"]).is_file()


def test_successful_hydration_records_digest_scan_and_policy(tmp_path):
    result = _hydrator(tmp_path).hydrate(
        _admission_path(tmp_path),
        artifact_path=_artifact(tmp_path),
        observed_digest=DIGEST,
        scan_result=_scan(),
    )

    statuses = result["record"]["hydration_statuses"]
    assert CleanroomImageHydrationStatus.CLEANROOM_IMAGE_DIGEST_VERIFIED.value in statuses
    assert CleanroomImageHydrationStatus.CLEANROOM_IMAGE_SCAN_PASSED.value in statuses
    assert CleanroomImageHydrationStatus.CLEANROOM_IMAGE_POLICY_ADMITTED.value in statuses
    assert CleanroomImageHydrationStatus.CLEANROOM_IMAGE_CACHE_READY.value in statuses


def test_hydrated_image_remains_not_executable(tmp_path):
    result = _hydrator(tmp_path).hydrate(
        _admission_path(tmp_path),
        artifact_path=_artifact(tmp_path),
        observed_digest=DIGEST,
        scan_result=_scan(),
    )

    assert result["record"]["executable"] is False
    assert (
        CleanroomImageHydrationStatus.CLEANROOM_IMAGE_NOT_EXECUTABLE.value
        in result["record"]["hydration_statuses"]
    )


def test_hydrated_image_remains_not_training_eligible(tmp_path):
    result = _hydrator(tmp_path).hydrate(
        _admission_path(tmp_path),
        artifact_path=_artifact(tmp_path),
        observed_digest=DIGEST,
        scan_result=_scan(),
    )

    assert result["record"]["training_eligible"] is False
    assert result["record"]["record_status"] == "active_eval_evidence"
