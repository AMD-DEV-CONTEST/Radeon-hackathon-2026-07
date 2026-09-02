from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_ROOT / "scripts"))

from corpus.programbench.cleanroom_image_import import (  # noqa: E402
    CleanroomImageImportConfig,
    CleanroomImageImportStatus,
    ProgramBenchCleanroomImageImport,
)
from corpus.programbench.cleanroom_image_import_record import (
    verify_cleanroom_image_import_record,  # noqa: E402
)
from corpus.programbench.dockerhub_manifest_provenance_record import (  # noqa: E402
    make_dockerhub_manifest_provenance_record,
    write_dockerhub_manifest_provenance_record,
)
from corpus.programbench.operator_artifact_admission_record import (  # noqa: E402
    make_operator_artifact_admission_record,
    write_operator_artifact_admission_record,
)

IMAGE = "programbench/doxygen_1776_doxygen.966d98e:task_cleanroom"
DIGEST = "sha256:cc50d0f7e9a1f3f90512e3d4c34781f4686a8fa3774fbff489947ef41bde2e72"


def _target() -> dict:
    return {
        "tool": "doxygen__doxygen.966d98e",
        "candidate_id": "close_lock_v7_doxygen_richgo_20260527",
    }


def _provenance_path(
    tmp_path: Path, *, image: str = IMAGE, digest: str = DIGEST, tag: str = "task_cleanroom"
) -> Path:
    record = make_dockerhub_manifest_provenance_record(
        status="EXACT_REMOTE_MANIFEST_FOUND",
        triage_record="triage.json",
        image_reference=image,
        registry="docker.io",
        repository="programbench/doxygen_1776_doxygen.966d98e",
        tag=tag,
        manifest_digest=digest,
        target=_target(),
        provenance_statuses=[
            "DOCKERHUB_MANIFEST_PROVENANCE_READY",
            "EXACT_REMOTE_MANIFEST_FOUND",
            "OPERATOR_CLAIM_CREATED",
        ],
        metadata={"pulled_layers": False, "executed": False},
    )
    return write_dockerhub_manifest_provenance_record(record, tmp_path / "provenance")


def _admission_path(
    tmp_path: Path,
    *,
    image: str = IMAGE,
    digest: str = DIGEST,
    fixture: bool = False,
    hydration_candidate: bool = True,
) -> Path:
    claim = {
        "image_reference": image,
        "source_type": "docker_hub_exact_reference",
        "source_url_or_registry": f"docker.io/programbench/doxygen_1776_doxygen.966d98e@{digest}",
        "digest": digest,
        "tag": "task_cleanroom",
        "license_provenance_notes": "Docker Hub exact manifest provenance.",
        "operator_id": "lock_fixture" if fixture else "codex_registry_metadata_lookup",
        "admission_reason": "fixture admission" if fixture else "real manifest admission",
        "requested_use": "hydration_candidate",
    }
    record = make_operator_artifact_admission_record(
        status="OPERATOR_ARTIFACT_ADMISSION_ACCEPTED",
        triage_record="triage.json",
        image_reference=image,
        target=_target(),
        admission_statuses=[
            "OPERATOR_ARTIFACT_ADMISSION_ACCEPTED",
            "OPERATOR_ARTIFACT_HYDRATION_CANDIDATE",
            "OPERATOR_ARTIFACT_NOT_EXECUTABLE",
        ],
        operator_claim=claim,
        hydration_candidate=hydration_candidate,
        executable=False,
    )
    return write_operator_artifact_admission_record(record, tmp_path / "admissions")


def _importer(tmp_path: Path) -> ProgramBenchCleanroomImageImport:
    return ProgramBenchCleanroomImageImport(
        CleanroomImageImportConfig(
            root=tmp_path,
            output_dir=tmp_path / "imports",
            quarantine_dir=tmp_path / "quarantine",
        )
    )


def _artifact(tmp_path: Path) -> Path:
    path = tmp_path / "doxygen-image.tar"
    path.write_text("fixture image tar bytes\n", encoding="utf-8")
    return path


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


def test_missing_provenance_blocks(tmp_path):
    result = _importer(tmp_path).import_image(tmp_path / "missing.json", _admission_path(tmp_path))

    assert (
        result["record"]["status"]
        == CleanroomImageImportStatus.CLEANROOM_IMAGE_IMPORT_BLOCKED_NO_PROVENANCE.value
    )


def test_missing_admission_blocks(tmp_path):
    result = _importer(tmp_path).import_image(_provenance_path(tmp_path), tmp_path / "missing.json")

    assert (
        result["record"]["status"]
        == CleanroomImageImportStatus.CLEANROOM_IMAGE_IMPORT_BLOCKED_NO_ADMISSION.value
    )


def test_fixture_admission_blocks(tmp_path):
    result = _importer(tmp_path).import_image(
        _provenance_path(tmp_path), _admission_path(tmp_path, fixture=True)
    )

    assert (
        result["record"]["status"]
        == CleanroomImageImportStatus.CLEANROOM_IMAGE_IMPORT_BLOCKED_FIXTURE_ADMISSION.value
    )


def test_wrong_image_reference_blocks(tmp_path):
    result = _importer(tmp_path).import_image(
        _provenance_path(tmp_path),
        _admission_path(tmp_path, image="programbench/other:task_cleanroom"),
    )

    assert (
        result["record"]["status"]
        == CleanroomImageImportStatus.CLEANROOM_IMAGE_IMPORT_BLOCKED_IMAGE_MISMATCH.value
    )


def test_admission_digest_mismatch_blocks(tmp_path):
    result = _importer(tmp_path).import_image(
        _provenance_path(tmp_path),
        _admission_path(tmp_path, digest="sha256:" + "0" * 64),
    )

    assert (
        result["record"]["status"]
        == CleanroomImageImportStatus.CLEANROOM_IMAGE_IMPORT_BLOCKED_DIGEST_MISMATCH.value
    )


def test_unpinned_latest_blocks(tmp_path):
    result = _importer(tmp_path).import_image(
        _provenance_path(tmp_path, tag="latest"),
        _admission_path(tmp_path),
    )

    assert (
        result["record"]["status"]
        == CleanroomImageImportStatus.CLEANROOM_IMAGE_IMPORT_BLOCKED_UNPINNED.value
    )


def test_pull_disabled_without_artifact_blocks(tmp_path):
    result = _importer(tmp_path).import_image(_provenance_path(tmp_path), _admission_path(tmp_path))

    assert (
        result["record"]["status"]
        == CleanroomImageImportStatus.CLEANROOM_IMAGE_IMPORT_BLOCKED_PULL_DISABLED.value
    )
    assert result["record"]["pull_command"] == [
        "docker",
        "pull",
        f"docker.io/programbench/doxygen_1776_doxygen.966d98e@{DIGEST}",
    ]


def test_observed_digest_mismatch_blocks(tmp_path):
    result = _importer(tmp_path).import_image(
        _provenance_path(tmp_path),
        _admission_path(tmp_path),
        artifact_path=_artifact(tmp_path),
        observed_digest="sha256:" + "0" * 64,
        scan_result=_scan(),
    )

    assert (
        result["record"]["status"]
        == CleanroomImageImportStatus.CLEANROOM_IMAGE_IMPORT_DIGEST_MISMATCH.value
    )


def test_scan_unavailable_blocks(tmp_path):
    result = _importer(tmp_path).import_image(
        _provenance_path(tmp_path),
        _admission_path(tmp_path),
        artifact_path=_artifact(tmp_path),
        observed_digest=DIGEST,
    )

    assert (
        result["record"]["status"]
        == CleanroomImageImportStatus.CLEANROOM_IMAGE_IMPORT_SCAN_UNAVAILABLE.value
    )


def test_scan_failure_blocks(tmp_path):
    result = _importer(tmp_path).import_image(
        _provenance_path(tmp_path),
        _admission_path(tmp_path),
        artifact_path=_artifact(tmp_path),
        observed_digest=DIGEST,
        scan_result=_scan(policy="fail", critical=1),
    )

    assert (
        result["record"]["status"]
        == CleanroomImageImportStatus.CLEANROOM_IMAGE_IMPORT_SCAN_FAILED.value
    )


def test_successful_import_writes_signed_quarantine_record(tmp_path):
    result = _importer(tmp_path).import_image(
        _provenance_path(tmp_path),
        _admission_path(tmp_path),
        artifact_path=_artifact(tmp_path),
        observed_digest=DIGEST,
        scan_result=_scan(),
    )

    record = result["record"]
    assert (
        record["status"] == CleanroomImageImportStatus.CLEANROOM_IMAGE_IMPORTED_TO_QUARANTINE.value
    )
    assert (
        CleanroomImageImportStatus.CLEANROOM_IMAGE_IMPORT_DIGEST_VERIFIED.value
        in record["import_statuses"]
    )
    assert (
        CleanroomImageImportStatus.CLEANROOM_IMAGE_IMPORT_SCAN_PASSED.value
        in record["import_statuses"]
    )
    assert (tmp_path / record["artifact_import_path"]).is_file()
    assert verify_cleanroom_image_import_record(record)


def test_successful_import_remains_not_executable_or_training_eligible(tmp_path):
    result = _importer(tmp_path).import_image(
        _provenance_path(tmp_path),
        _admission_path(tmp_path),
        artifact_path=_artifact(tmp_path),
        observed_digest=DIGEST,
        scan_result=_scan(),
    )

    assert result["record"]["executable"] is False
    assert result["record"]["training_eligible"] is False
    assert (
        CleanroomImageImportStatus.CLEANROOM_IMAGE_IMPORT_NOT_EXECUTABLE.value
        in result["record"]["import_statuses"]
    )
    assert (
        CleanroomImageImportStatus.TRAINING_INELIGIBLE.value in result["record"]["import_statuses"]
    )
