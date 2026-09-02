from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_ROOT / "scripts"))

from corpus.programbench.cleanroom_build_recipe_provenance_gap import (  # noqa: E402
    BuildRecipeProvenanceGapConfig,
    BuildRecipeProvenanceGapStatus,
    ProgramBenchCleanroomBuildRecipeProvenanceGap,
)
from corpus.programbench.cleanroom_build_recipe_provenance_gap_record import (
    verify_cleanroom_build_recipe_provenance_gap_record,  # noqa: E402
)
from corpus.programbench.cleanroom_build_recipe_recovery_record import (  # noqa: E402
    make_cleanroom_build_recipe_recovery_record,
    write_cleanroom_build_recipe_recovery_record,
)
from corpus.programbench.cleanroom_image_remediation_plan_record import (  # noqa: E402
    make_cleanroom_image_remediation_plan_record,
    write_cleanroom_image_remediation_plan_record,
)

IMAGE = "programbench/doxygen_1776_doxygen.966d98e:task_cleanroom"
DIGEST = "sha256:cc50d0f7e9a1f3f90512e3d4c34781f4686a8fa3774fbff489947ef41bde2e72"


def _plan(tmp_path: Path, *, image: str = IMAGE, digest: str = DIGEST) -> Path:
    record = make_cleanroom_image_remediation_plan_record(
        status="CLEANROOM_IMAGE_REMEDIATION_PLAN_WRITTEN",
        image_reference=image,
        image_digest=digest,
        scan_record="scan.json",
        triage_record="triage.json",
        recommendation="REMEDIATE_IMAGE_REQUIRED",
        dominant_risk_category="language_runtime",
        required_inputs={
            "go_version_target": "1.24.13",
            "source_dockerfile_or_build_recipe_required": True,
            "base_image_digest_required": True,
        },
        fidelity_risk={"risk": "material"},
        cache_ready=False,
        executable=False,
    )
    return write_cleanroom_image_remediation_plan_record(record, tmp_path / "plans")


def _recovery(
    tmp_path: Path,
    *,
    image: str = IMAGE,
    digest: str = DIGEST,
    original_recipe: bool = False,
    base_digest: bool = False,
    history_only: bool = True,
    unredacted_token: bool = False,
) -> Path:
    history = [{"created_by": "RUN wget https://dl.google.com/go/go1.21.0.linux-amd64.tar.gz"}]
    if unredacted_token:
        history.append(
            {
                "created_by": "RUN git clone https://x-access-token:ghp_SECRETSECRET@github.com/example/repo"
            }
        )
    record = make_cleanroom_build_recipe_recovery_record(
        status="BUILD_RECIPE_RECONSTRUCTED_QUARANTINE_ONLY"
        if history_only
        else "BUILD_RECIPE_RECOVERED_EXACT",
        image_reference=image,
        image_digest=digest,
        remediation_plan="plans/plan.json",
        recipe_components={
            "original_recipe_file_recovered": original_recipe,
            "base_image_digest_present": base_digest,
            "reconstructed_from_image_history": history_only,
            "image_config_history_present": history_only,
            "go_runtime_version_detected": "1.21.0",
        },
        image_config_metadata={
            "history": history,
            "base_image_label": "22.04",
        },
        go_update={
            "current_version_detected": "1.21.0",
            "target_version": "1.24.13",
            "recipe_compatible": True,
        },
        fidelity_assessment={"fidelity_class": "material_fidelity_change"},
        recovery_statuses=["BUILD_RECIPE_RECONSTRUCTED_QUARANTINE_ONLY"],
        cache_ready=False,
        executable=False,
    )
    return write_cleanroom_build_recipe_recovery_record(record, tmp_path / "recovery")


def _gapper(tmp_path: Path, target_image: str = IMAGE, target_digest: str = DIGEST):
    return ProgramBenchCleanroomBuildRecipeProvenanceGap(
        BuildRecipeProvenanceGapConfig(
            root=tmp_path,
            output_dir=tmp_path / "gaps",
            target_image=target_image,
            target_digest=target_digest,
        )
    )


def test_missing_remediation_plan_blocks(tmp_path):
    result = _gapper(tmp_path).write_gap(tmp_path / "missing.json", _recovery(tmp_path))

    assert (
        result["record"]["status"]
        == BuildRecipeProvenanceGapStatus.BUILD_RECIPE_PROVENANCE_GAP_BLOCKED_NO_PLAN.value
    )


def test_missing_recipe_recovery_blocks(tmp_path):
    result = _gapper(tmp_path).write_gap(_plan(tmp_path), tmp_path / "missing.json")

    assert (
        result["record"]["status"]
        == BuildRecipeProvenanceGapStatus.BUILD_RECIPE_PROVENANCE_GAP_BLOCKED_NO_RECOVERY.value
    )


def test_image_mismatch_blocks(tmp_path):
    result = _gapper(tmp_path).write_gap(
        _plan(tmp_path), _recovery(tmp_path, image="programbench/other:task_cleanroom")
    )

    assert (
        result["record"]["status"]
        == BuildRecipeProvenanceGapStatus.BUILD_RECIPE_PROVENANCE_GAP_BLOCKED_IMAGE_MISMATCH.value
    )


def test_digest_mismatch_blocks(tmp_path):
    result = _gapper(tmp_path).write_gap(_plan(tmp_path), _recovery(tmp_path, digest="sha256:bad"))

    assert (
        result["record"]["status"]
        == BuildRecipeProvenanceGapStatus.BUILD_RECIPE_PROVENANCE_GAP_BLOCKED_DIGEST_MISMATCH.value
    )


def test_gap_packet_records_original_recipe_missing(tmp_path):
    result = _gapper(tmp_path).write_gap(_plan(tmp_path), _recovery(tmp_path))

    assert (
        BuildRecipeProvenanceGapStatus.ORIGINAL_RECIPE_MISSING.value
        in result["record"]["gap_statuses"]
    )


def test_gap_packet_records_base_digest_missing(tmp_path):
    result = _gapper(tmp_path).write_gap(_plan(tmp_path), _recovery(tmp_path))

    assert (
        BuildRecipeProvenanceGapStatus.BASE_IMAGE_DIGEST_MISSING.value
        in result["record"]["gap_statuses"]
    )


def test_gap_packet_records_history_only_reconstruction(tmp_path):
    result = _gapper(tmp_path).write_gap(_plan(tmp_path), _recovery(tmp_path))

    assert (
        BuildRecipeProvenanceGapStatus.RECONSTRUCTED_FROM_IMAGE_HISTORY_ONLY.value
        in result["record"]["gap_statuses"]
    )
    assert (
        result["record"]["observed_recipe_state"]["reconstructed_recipe_source"]
        == "OCI config history only"
    )


def test_gap_packet_records_material_fidelity_risk(tmp_path):
    result = _gapper(tmp_path).write_gap(_plan(tmp_path), _recovery(tmp_path))

    assert (
        BuildRecipeProvenanceGapStatus.MATERIAL_FIDELITY_RISK.value
        in result["record"]["gap_statuses"]
    )


def test_gap_packet_defines_closure_requirements(tmp_path):
    result = _gapper(tmp_path).write_gap(_plan(tmp_path), _recovery(tmp_path))
    requirements = {item["requirement"] for item in result["record"]["closure_requirements"]}

    assert "original_cleanroom_build_recipe" in requirements
    assert "pinned_base_image_digest" in requirements
    assert "go_runtime_update_plan" in requirements


def test_rebuild_is_not_authorized(tmp_path):
    result = _gapper(tmp_path).write_gap(_plan(tmp_path), _recovery(tmp_path))

    assert result["record"]["authorization"]["rebuild_authorized"] is False
    assert (
        BuildRecipeProvenanceGapStatus.REBUILD_NOT_AUTHORIZED.value
        in result["record"]["gap_statuses"]
    )


def test_docker_execution_is_not_authorized(tmp_path):
    result = _gapper(tmp_path).write_gap(_plan(tmp_path), _recovery(tmp_path))

    assert result["record"]["authorization"]["docker_execution_authorized"] is False


def test_hydration_is_not_authorized(tmp_path):
    result = _gapper(tmp_path).write_gap(_plan(tmp_path), _recovery(tmp_path))

    assert result["record"]["authorization"]["hydration_authorized"] is False


def test_programbench_rerun_is_not_authorized(tmp_path):
    result = _gapper(tmp_path).write_gap(_plan(tmp_path), _recovery(tmp_path))

    assert result["record"]["authorization"]["programbench_rerun_authorized"] is False


def test_cache_ready_false(tmp_path):
    result = _gapper(tmp_path).write_gap(_plan(tmp_path), _recovery(tmp_path))

    assert result["record"]["cache_ready"] is False


def test_training_ineligible(tmp_path):
    result = _gapper(tmp_path).write_gap(_plan(tmp_path), _recovery(tmp_path))

    assert result["record"]["training_eligible"] is False


def test_redaction_invariant_verified_for_sanitized_history(tmp_path):
    result = _gapper(tmp_path).write_gap(_plan(tmp_path), _recovery(tmp_path))

    assert result["record"]["redaction_invariant"]["redaction_passed"] is True
    assert (
        BuildRecipeProvenanceGapStatus.REDACTION_INVARIANT_VERIFIED.value
        in result["record"]["gap_statuses"]
    )


def test_redaction_invariant_failed_for_unredacted_history(tmp_path):
    result = _gapper(tmp_path).write_gap(
        _plan(tmp_path), _recovery(tmp_path, unredacted_token=True)
    )

    assert result["record"]["redaction_invariant"]["redaction_passed"] is False
    assert (
        BuildRecipeProvenanceGapStatus.REDACTION_INVARIANT_FAILED.value
        in result["record"]["gap_statuses"]
    )


def test_signed_gap_record_is_written(tmp_path):
    result = _gapper(tmp_path).write_gap(_plan(tmp_path), _recovery(tmp_path))

    assert Path(result["record_path"]).is_file()
    assert verify_cleanroom_build_recipe_provenance_gap_record(result["record"])
