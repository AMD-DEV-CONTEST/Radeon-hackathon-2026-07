from __future__ import annotations

import io
import json
import sys
import tarfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_ROOT / "scripts"))

from corpus.programbench.cleanroom_build_recipe_recovery import (  # noqa: E402
    BuildRecipeRecoveryConfig,
    BuildRecipeRecoveryStatus,
    ProgramBenchCleanroomBuildRecipeRecovery,
)
from corpus.programbench.cleanroom_build_recipe_recovery_record import (
    verify_cleanroom_build_recipe_recovery_record,  # noqa: E402
)
from corpus.programbench.cleanroom_image_remediation_plan_record import (  # noqa: E402
    make_cleanroom_image_remediation_plan_record,
    write_cleanroom_image_remediation_plan_record,
)
from corpus.programbench.cleanroom_image_scan_record import (  # noqa: E402
    make_cleanroom_image_scan_record,
    write_cleanroom_image_scan_record,
)

IMAGE = "programbench/doxygen_1776_doxygen.966d98e:task_cleanroom"
DIGEST = "sha256:cc50d0f7e9a1f3f90512e3d4c34781f4686a8fa3774fbff489947ef41bde2e72"


def _write_scan(tmp_path: Path, artifact_path: str = "") -> Path:
    record = make_cleanroom_image_scan_record(
        status="CLEANROOM_IMAGE_SCAN_FAILED",
        import_record="import.json",
        image_reference=IMAGE,
        artifact_path=artifact_path,
        expected_digest=DIGEST,
        observed_digest=DIGEST,
        file_sha256="sha256:file",
        file_size=123,
        scanner="trivy",
        scanner_version="Version: 0.test",
        findings_summary={
            "critical": 2,
            "high": 2,
            "medium": 0,
            "low": 0,
            "unknown": 0,
            "total": 4,
        },
        normalized_findings=[],
        reasons=["critical_or_high_findings_present"],
        cache_ready=False,
        executable=False,
    )
    return write_cleanroom_image_scan_record(record, tmp_path / "scan")


def _write_plan(
    tmp_path: Path, *, image: str = IMAGE, digest: str = DIGEST, artifact_path: str = ""
) -> Path:
    scan = _write_scan(tmp_path, artifact_path)
    record = make_cleanroom_image_remediation_plan_record(
        status="CLEANROOM_IMAGE_REMEDIATION_PLAN_WRITTEN",
        image_reference=image,
        image_digest=digest,
        scan_record=scan.relative_to(tmp_path).as_posix(),
        triage_record="triage.json",
        recommendation="REMEDIATE_IMAGE_REQUIRED",
        dominant_risk_category="language_runtime",
        required_inputs={
            "go_version_target": "1.24.13",
            "source_dockerfile_or_build_recipe_required": True,
            "base_image_digest_required": True,
            "scanner_rerun_required": True,
            "hydration_policy_rerun_required": True,
            "bounded_rerun_revalidation_required": True,
        },
        plan_statuses=["CLEANROOM_IMAGE_REMEDIATION_PLAN_WRITTEN"],
        cache_ready=False,
        executable=False,
    )
    return write_cleanroom_image_remediation_plan_record(record, tmp_path / "plans")


def _recoverer(
    tmp_path: Path, *search_roots: Path, target_image: str = IMAGE, target_digest: str = DIGEST
):
    return ProgramBenchCleanroomBuildRecipeRecovery(
        BuildRecipeRecoveryConfig(
            root=tmp_path,
            output_dir=tmp_path / "recovery",
            search_roots=list(search_roots),
            target_image=target_image,
            target_digest=target_digest,
        )
    )


def _oci_tar(path: Path) -> None:
    config = {
        "config": {
            "Env": ["PATH=/usr/local/go/bin:/usr/local/bin:/usr/bin"],
            "Labels": {"org.opencontainers.image.version": "22.04"},
            "WorkingDir": "/workspace",
        },
        "history": [
            {
                "created_by": "RUN /bin/sh -c wget -O go.tgz https://dl.google.com/go/go1.21.0.linux-amd64.tar.gz"
            },
            {
                "created_by": "RUN /bin/sh -c git clone https://x-access-token:ghp_SECRET@github.com/example/repo.git ."
            },
        ],
    }
    manifest_digest = DIGEST.removeprefix("sha256:")
    config_digest = "deb6e3d2e8483c7b448ab61c6aca402b719cfcb9259c11078a32e1df0f042047"
    with tarfile.open(path, "w") as tar:
        _add_json(tar, "index.json", {"manifests": [{"digest": DIGEST}]})
        _add_json(
            tar, "manifest.json", [{"Config": f"blobs/sha256/{config_digest}", "Layers": ["layer"]}]
        )
        _add_json(tar, f"blobs/sha256/{manifest_digest}", {"schemaVersion": 2})
        _add_json(tar, f"blobs/sha256/{config_digest}", config)


def _add_json(tar: tarfile.TarFile, name: str, data: object) -> None:
    raw = json.dumps(data).encode()
    info = tarfile.TarInfo(name)
    info.size = len(raw)
    tar.addfile(info, io.BytesIO(raw))


def test_missing_remediation_plan_blocks(tmp_path):
    result = _recoverer(tmp_path).recover(tmp_path / "missing.json")

    assert (
        result["record"]["status"]
        == BuildRecipeRecoveryStatus.BUILD_RECIPE_BLOCKED_NO_REMEDIATION_PLAN.value
    )


def test_invalid_remediation_signature_blocks(tmp_path):
    plan = _write_plan(tmp_path)
    data = json.loads(plan.read_text())
    data["recommendation"] = "tampered"
    plan.write_text(json.dumps(data), encoding="utf-8")

    result = _recoverer(tmp_path).recover(plan)

    assert (
        result["record"]["status"]
        == BuildRecipeRecoveryStatus.BUILD_RECIPE_BLOCKED_NO_REMEDIATION_PLAN.value
    )


def test_image_mismatch_blocks(tmp_path):
    plan = _write_plan(tmp_path, image="programbench/other:task_cleanroom")
    result = _recoverer(tmp_path).recover(plan)

    assert (
        result["record"]["status"]
        == BuildRecipeRecoveryStatus.BUILD_RECIPE_BLOCKED_IMAGE_MISMATCH.value
    )


def test_digest_mismatch_blocks(tmp_path):
    plan = _write_plan(tmp_path, digest="sha256:bad")
    result = _recoverer(tmp_path).recover(plan)

    assert (
        result["record"]["status"]
        == BuildRecipeRecoveryStatus.BUILD_RECIPE_BLOCKED_DIGEST_MISMATCH.value
    )


def test_records_searched_locations(tmp_path):
    root = tmp_path / "evidence"
    root.mkdir()
    plan = _write_plan(tmp_path)
    result = _recoverer(tmp_path, root).recover(plan)

    assert result["record"]["searched_locations"][0]["exists"] is True


def test_missing_recipe_is_classified(tmp_path):
    root = tmp_path / "empty"
    root.mkdir()
    plan = _write_plan(tmp_path)
    result = _recoverer(tmp_path, root).recover(plan)

    assert result["record"]["status"] == BuildRecipeRecoveryStatus.BUILD_RECIPE_MISSING.value


def test_exact_dockerfile_with_base_digest_is_recovered(tmp_path):
    root = tmp_path / "recipe"
    root.mkdir()
    (root / "Dockerfile").write_text(
        "FROM ubuntu:22.04@sha256:abc\nRUN echo ok\n", encoding="utf-8"
    )
    plan = _write_plan(tmp_path)
    result = _recoverer(tmp_path, root).recover(plan)

    assert (
        result["record"]["status"] == BuildRecipeRecoveryStatus.BUILD_RECIPE_RECOVERED_EXACT.value
    )
    assert result["record"]["recipe_components"]["base_image_digest_present"] is True


def test_dockerfile_without_base_digest_is_partial(tmp_path):
    root = tmp_path / "recipe"
    root.mkdir()
    (root / "Dockerfile").write_text("FROM ubuntu:22.04\nRUN echo ok\n", encoding="utf-8")
    plan = _write_plan(tmp_path)
    result = _recoverer(tmp_path, root).recover(plan)

    assert (
        result["record"]["status"] == BuildRecipeRecoveryStatus.BUILD_RECIPE_RECOVERED_PARTIAL.value
    )
    assert (
        BuildRecipeRecoveryStatus.BUILD_RECIPE_BASE_DIGEST_MISSING.value
        in result["record"]["recovery_statuses"]
    )


def test_image_history_reconstructs_quarantine_only_recipe(tmp_path):
    artifact = tmp_path / "image.tar"
    _oci_tar(artifact)
    plan = _write_plan(tmp_path, artifact_path=str(artifact))
    result = _recoverer(tmp_path).recover(plan)

    assert (
        result["record"]["status"]
        == BuildRecipeRecoveryStatus.BUILD_RECIPE_RECONSTRUCTED_QUARANTINE_ONLY.value
    )
    assert result["record"]["recipe_components"]["reconstructed_from_image_history"] is True


def test_reconstructed_history_redacts_tokens(tmp_path):
    artifact = tmp_path / "image.tar"
    _oci_tar(artifact)
    plan = _write_plan(tmp_path, artifact_path=str(artifact))
    result = _recoverer(tmp_path).recover(plan)

    raw = json.dumps(result["record"])
    assert "ghp_SECRET" not in raw
    assert "<redacted>" in raw


def test_go_update_compatibility_is_identified(tmp_path):
    artifact = tmp_path / "image.tar"
    _oci_tar(artifact)
    plan = _write_plan(tmp_path, artifact_path=str(artifact))
    result = _recoverer(tmp_path).recover(plan)

    assert result["record"]["go_update"]["current_version_detected"] == "1.21.0"
    assert result["record"]["go_update"]["target_version"] == "1.24.13"
    assert result["record"]["go_update"]["recipe_compatible"] is True


def test_fidelity_assessment_marks_material_change(tmp_path):
    plan = _write_plan(tmp_path)
    result = _recoverer(tmp_path).recover(plan)

    assert result["record"]["fidelity_assessment"]["fidelity_class"] == "material_fidelity_change"
    assert result["record"]["fidelity_assessment"]["bounded_rerun_revalidation_required"] is True


def test_recovery_does_not_mark_cache_ready(tmp_path):
    result = _recoverer(tmp_path).recover(_write_plan(tmp_path))

    assert result["record"]["cache_ready"] is False


def test_recovery_does_not_mark_executable(tmp_path):
    result = _recoverer(tmp_path).recover(_write_plan(tmp_path))

    assert result["record"]["executable"] is False


def test_recovery_does_not_mark_training_eligible(tmp_path):
    result = _recoverer(tmp_path).recover(_write_plan(tmp_path))

    assert result["record"]["training_eligible"] is False


def test_signed_recovery_record_is_written(tmp_path):
    result = _recoverer(tmp_path).recover(_write_plan(tmp_path))

    assert Path(result["record_path"]).is_file()
    assert verify_cleanroom_build_recipe_recovery_record(result["record"])
