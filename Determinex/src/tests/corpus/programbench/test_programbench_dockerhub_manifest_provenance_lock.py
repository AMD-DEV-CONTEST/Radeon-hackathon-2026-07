from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_ROOT / "scripts"))

from corpus.programbench.dockerhub_manifest_provenance import (  # noqa: E402
    DockerHubManifestProvenanceConfig,
    DockerHubManifestProvenanceStatus,
    ProgramBenchDockerHubManifestProvenance,
)
from corpus.programbench.dockerhub_manifest_provenance_record import (
    verify_dockerhub_manifest_provenance_record,  # noqa: E402
)
from corpus.programbench.infra_failure_triage import InfraFailureTriageStatus  # noqa: E402
from corpus.programbench.infra_failure_triage_record import (  # noqa: E402
    make_infra_failure_triage_record,
    write_infra_failure_triage_record,
)

MISSING_IMAGE = "programbench/doxygen_1776_doxygen.966d98e:task_cleanroom"
DIGEST = "sha256:cc50d0f7e9a1f3f90512e3d4c34781f4686a8fa3774fbff489947ef41bde2e72"


def _target() -> dict:
    return {
        "tool": "doxygen__doxygen.966d98e",
        "candidate_id": "close_lock_v7_doxygen_richgo_20260527",
    }


def _triage_path(
    tmp_path: Path,
    *,
    failure_type: str = InfraFailureTriageStatus.MISSING_CLEANROOM_IMAGE.value,
    image: str = MISSING_IMAGE,
) -> Path:
    record = make_infra_failure_triage_record(
        status=InfraFailureTriageStatus.INFRA_FAILURE_TRIAGED.value,
        source_record="real.json",
        packet_id="doxygen_real_bounded_rerun_20260527",
        target=_target(),
        failure_type=failure_type,
        missing_image=image,
        local_image_status=InfraFailureTriageStatus.IMAGE_MISSING_LOCAL.value,
        source_status=InfraFailureTriageStatus.IMAGE_RECOVERY_REQUIRES_OPERATOR.value,
        provenance_status=InfraFailureTriageStatus.IMAGE_HYDRATION_BLOCKED_NO_PROVENANCE.value,
        evidence={
            "rerun_scope": {
                **_target(),
                "max_attempts": 1,
            }
        },
    )
    return write_infra_failure_triage_record(record, tmp_path / "triage")


def _metadata(**overrides) -> dict:
    data = {
        "image_reference": MISSING_IMAGE,
        "registry": "docker.io",
        "repository": "programbench/doxygen_1776_doxygen.966d98e",
        "tag": "task_cleanroom",
        "manifest_digest": DIGEST,
        "media_type": "application/vnd.oci.image.manifest.v1+json",
        "platform": "linux/amd64",
        "config_digest": "sha256:" + "d" * 64,
        "last_updated": "2026-05-03T23:32:39.101172Z",
        "last_pushed": "2026-05-03T23:32:38.802423245Z",
        "last_updater_username": "klieret",
        "full_size": 703316826,
        "pulled_layers": False,
        "executed": False,
    }
    data.update(overrides)
    return data


def _converter(tmp_path: Path) -> ProgramBenchDockerHubManifestProvenance:
    return ProgramBenchDockerHubManifestProvenance(
        DockerHubManifestProvenanceConfig(
            root=tmp_path,
            output_dir=tmp_path / "provenance",
            operator_claim_dir=tmp_path / "claims",
        )
    )


def test_exact_dockerhub_manifest_becomes_signed_provenance_candidate(tmp_path):
    result = _converter(tmp_path).convert(_triage_path(tmp_path), _metadata())

    record = result["record"]
    assert record["status"] == DockerHubManifestProvenanceStatus.EXACT_REMOTE_MANIFEST_FOUND.value
    assert record["manifest_digest"] == DIGEST
    assert verify_dockerhub_manifest_provenance_record(record)


def test_operator_claim_is_created_from_manifest_metadata(tmp_path):
    result = _converter(tmp_path).convert(_triage_path(tmp_path), _metadata())

    claim = result["operator_claim"]
    assert Path(result["operator_claim_path"]).is_file()
    assert claim["image_reference"] == MISSING_IMAGE
    assert claim["digest"] == DIGEST
    assert claim["source_type"] == "docker_hub_exact_reference"
    assert claim["requested_use"] == "hydration_candidate"


def test_manifest_provenance_does_not_authorize_hydration_execution_or_training(tmp_path):
    result = _converter(tmp_path).convert(_triage_path(tmp_path), _metadata())
    record = result["record"]

    assert record["pulled_layers"] is False
    assert record["executed"] is False
    assert record["hydration_authorized"] is False
    assert record["execution_authorized"] is False
    assert record["training_eligible"] is False


def test_missing_triage_blocks(tmp_path):
    result = _converter(tmp_path).convert(tmp_path / "missing.triage.json", _metadata())

    assert (
        result["record"]["status"]
        == DockerHubManifestProvenanceStatus.DOCKERHUB_MANIFEST_BLOCKED_NO_TRIAGE.value
    )


def test_non_missing_cleanroom_triage_blocks(tmp_path):
    result = _converter(tmp_path).convert(
        _triage_path(tmp_path, failure_type="MISSING_TASK_ROOT"), _metadata()
    )

    assert (
        result["record"]["status"]
        == DockerHubManifestProvenanceStatus.DOCKERHUB_MANIFEST_BLOCKED_NO_TRIAGE.value
    )


def test_image_mismatch_blocks(tmp_path):
    result = _converter(tmp_path).convert(
        _triage_path(tmp_path),
        _metadata(image_reference="programbench/other:task_cleanroom"),
    )

    assert (
        result["record"]["status"]
        == DockerHubManifestProvenanceStatus.DOCKERHUB_MANIFEST_BLOCKED_IMAGE_MISMATCH.value
    )


def test_missing_digest_blocks(tmp_path):
    result = _converter(tmp_path).convert(_triage_path(tmp_path), _metadata(manifest_digest=""))

    assert (
        result["record"]["status"]
        == DockerHubManifestProvenanceStatus.DOCKERHUB_MANIFEST_BLOCKED_NO_DIGEST.value
    )


def test_latest_tag_blocks_even_with_digest(tmp_path):
    latest_image = "programbench/doxygen_1776_doxygen.966d98e:latest"
    result = _converter(tmp_path).convert(
        _triage_path(tmp_path, image=latest_image),
        _metadata(image_reference=latest_image, tag="latest"),
    )

    assert (
        result["record"]["status"]
        == DockerHubManifestProvenanceStatus.DOCKERHUB_MANIFEST_BLOCKED_FLOATING_LATEST.value
    )


def test_layer_pull_metadata_blocks(tmp_path):
    result = _converter(tmp_path).convert(_triage_path(tmp_path), _metadata(pulled_layers=True))

    assert (
        result["record"]["status"]
        == DockerHubManifestProvenanceStatus.DOCKERHUB_MANIFEST_BLOCKED_LAYER_PULL.value
    )


def test_executed_metadata_blocks(tmp_path):
    result = _converter(tmp_path).convert(_triage_path(tmp_path), _metadata(executed=True))

    assert (
        result["record"]["status"]
        == DockerHubManifestProvenanceStatus.DOCKERHUB_MANIFEST_BLOCKED_EXECUTION.value
    )
