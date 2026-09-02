from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_ROOT / "scripts"))

from corpus.programbench.cleanroom_build_recipe_provenance_gap import (  # noqa: E402
    BuildRecipeProvenanceGapConfig,
    ProgramBenchCleanroomBuildRecipeProvenanceGap,
)
from corpus.programbench.cleanroom_build_recipe_recovery_record import (  # noqa: E402
    make_cleanroom_build_recipe_recovery_record,
    write_cleanroom_build_recipe_recovery_record,
)
from corpus.programbench.cleanroom_image_remediation_plan_record import (  # noqa: E402
    make_cleanroom_image_remediation_plan_record,
    write_cleanroom_image_remediation_plan_record,
)
from corpus.programbench.cleanroom_recipe_provenance_recovery import (  # noqa: E402
    ProgramBenchCleanroomRecipeProvenanceRecovery,
    RecipeProvenanceRecoveryConfig,
    RecipeProvenanceRecoveryStatus,
)
from corpus.programbench.cleanroom_recipe_provenance_recovery_record import (  # noqa: E402
    verify_cleanroom_recipe_provenance_recovery_record,
)

IMAGE = "programbench/doxygen_1776_doxygen.966d98e:task_cleanroom"
DIGEST = "sha256:cc50d0f7e9a1f3f90512e3d4c34781f4686a8fa3774fbff489947ef41bde2e72"
BASE_DIGEST = "sha256:" + ("a" * 64)


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


def _recovery(tmp_path: Path, *, image: str = IMAGE, digest: str = DIGEST) -> Path:
    record = make_cleanroom_build_recipe_recovery_record(
        status="BUILD_RECIPE_RECONSTRUCTED_QUARANTINE_ONLY",
        image_reference=image,
        image_digest=digest,
        remediation_plan="plans/plan.json",
        recipe_components={
            "original_recipe_file_recovered": False,
            "base_image_digest_present": False,
            "reconstructed_from_image_history": True,
            "image_config_history_present": True,
            "go_runtime_version_detected": "1.21.0",
        },
        image_config_metadata={
            "history": [
                {"created_by": "RUN wget https://dl.google.com/go/go1.21.0.linux-amd64.tar.gz"}
            ]
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


def _gap(tmp_path: Path, *, image: str = IMAGE, digest: str = DIGEST) -> Path:
    result = ProgramBenchCleanroomBuildRecipeProvenanceGap(
        BuildRecipeProvenanceGapConfig(
            root=tmp_path,
            output_dir=tmp_path / "gaps",
            target_image=image,
            target_digest=digest,
        )
    ).write_gap(
        _plan(tmp_path, image=image, digest=digest), _recovery(tmp_path, image=image, digest=digest)
    )
    return Path(result["record_path"])


def _recoverer(
    tmp_path: Path, *search_roots: Path, target_image: str = IMAGE, target_digest: str = DIGEST
):
    return ProgramBenchCleanroomRecipeProvenanceRecovery(
        RecipeProvenanceRecoveryConfig(
            root=tmp_path,
            output_dir=tmp_path / "recipe_provenance",
            search_roots=list(search_roots),
            target_image=target_image,
            target_digest=target_digest,
        )
    )


def test_missing_gap_blocks(tmp_path):
    result = _recoverer(tmp_path).recover(tmp_path / "missing.json")

    assert (
        result["record"]["status"]
        == RecipeProvenanceRecoveryStatus.PROVENANCE_RECOVERY_BLOCKED.value
    )
    assert (
        RecipeProvenanceRecoveryStatus.RECIPE_PROVENANCE_BLOCKED_NO_GAP.value
        in result["record"]["provenance_statuses"]
    )


def test_image_mismatch_blocks(tmp_path):
    result = _recoverer(tmp_path, target_image="programbench/other:task_cleanroom").recover(
        _gap(tmp_path)
    )

    assert (
        RecipeProvenanceRecoveryStatus.RECIPE_PROVENANCE_BLOCKED_IMAGE_MISMATCH.value
        in result["record"]["provenance_statuses"]
    )
    assert (
        result["record"]["decision"]
        == RecipeProvenanceRecoveryStatus.REBUILD_PROVENANCE_BLOCKED.value
    )


def test_digest_mismatch_blocks(tmp_path):
    result = _recoverer(tmp_path, target_digest="sha256:bad").recover(_gap(tmp_path))

    assert (
        RecipeProvenanceRecoveryStatus.RECIPE_PROVENANCE_BLOCKED_DIGEST_MISMATCH.value
        in result["record"]["provenance_statuses"]
    )


def test_exhausted_when_no_allowed_sources_close_gaps(tmp_path):
    result = _recoverer(tmp_path, tmp_path / "empty").recover(_gap(tmp_path))

    assert (
        result["record"]["status"]
        == RecipeProvenanceRecoveryStatus.PROVENANCE_RECOVERY_EXHAUSTED.value
    )
    assert (
        result["record"]["decision"]
        == RecipeProvenanceRecoveryStatus.REBUILD_PROVENANCE_BLOCKED.value
    )
    assert (
        RecipeProvenanceRecoveryStatus.ORIGINAL_RECIPE_STILL_MISSING.value
        in result["record"]["provenance_statuses"]
    )
    assert (
        RecipeProvenanceRecoveryStatus.BASE_IMAGE_DIGEST_STILL_MISSING.value
        in result["record"]["provenance_statuses"]
    )


def test_records_each_searched_location(tmp_path):
    root = tmp_path / "empty"
    root.mkdir()

    result = _recoverer(tmp_path, root, tmp_path / "missing-root").recover(_gap(tmp_path))
    searched = result["record"]["searched_locations"]

    assert [item["exists"] for item in searched] == [True, False]
    assert searched[0]["source_policy"] == "local_or_admitted_only"


def test_task_metadata_is_partial_quarantine_only(tmp_path):
    root = tmp_path / "task"
    root.mkdir()
    (root / "task.yaml").write_text(
        "repository: doxygen/doxygen\ncommit: 966d98e\n", encoding="utf-8"
    )

    result = _recoverer(tmp_path, root).recover(_gap(tmp_path))

    assert (
        result["record"]["decision"]
        == RecipeProvenanceRecoveryStatus.REBUILD_PROVENANCE_PARTIAL_QUARANTINE_ONLY.value
    )
    assert (
        RecipeProvenanceRecoveryStatus.RECIPE_PROVENANCE_RECOVERED_PARTIAL.value
        in result["record"]["provenance_statuses"]
    )
    assert result["record"]["recovered_provenance"][0]["quarantine_only"] is True


def test_dockerfile_without_base_digest_is_partial(tmp_path):
    root = tmp_path / "recipe"
    root.mkdir()
    (root / "Dockerfile").write_text(
        "FROM ubuntu:22.04\nRUN wget https://dl.google.com/go/go1.21.0.linux-amd64.tar.gz\n",
        encoding="utf-8",
    )

    result = _recoverer(tmp_path, root).recover(_gap(tmp_path))

    assert (
        result["record"]["decision"]
        == RecipeProvenanceRecoveryStatus.REBUILD_PROVENANCE_PARTIAL_QUARANTINE_ONLY.value
    )
    assert (
        RecipeProvenanceRecoveryStatus.BASE_IMAGE_DIGEST_STILL_MISSING.value
        in result["record"]["provenance_statuses"]
    )


def test_digest_pinned_dockerfile_recovers_exact_recipe_and_base(tmp_path):
    root = tmp_path / "recipe"
    root.mkdir()
    (root / "Dockerfile").write_text(
        f"FROM ubuntu@{BASE_DIGEST}\nRUN wget https://dl.google.com/go/go1.21.0.linux-amd64.tar.gz\n",
        encoding="utf-8",
    )

    result = _recoverer(tmp_path, root).recover(_gap(tmp_path))

    assert (
        result["record"]["status"]
        == RecipeProvenanceRecoveryStatus.RECIPE_PROVENANCE_RECOVERED_EXACT.value
    )
    assert (
        result["record"]["decision"]
        == RecipeProvenanceRecoveryStatus.REBUILD_PROVENANCE_READY.value
    )
    assert (
        RecipeProvenanceRecoveryStatus.BASE_IMAGE_PROVENANCE_RECOVERED_EXACT.value
        in result["record"]["provenance_statuses"]
    )
    assert result["record"]["gap_closure"]["all_required_provenance_closed"] is True


def test_operator_provenance_json_can_close_exact_gaps(tmp_path):
    root = tmp_path / "operator"
    root.mkdir()
    (root / "operator_recipe.json").write_text(
        json.dumps(
            {
                "image_reference": IMAGE,
                "image_digest": DIGEST,
                "original_cleanroom_build_recipe": "sha256:recipe",
                "base_image_digest": BASE_DIGEST,
            }
        ),
        encoding="utf-8",
    )

    result = _recoverer(tmp_path, root).recover(_gap(tmp_path))

    assert (
        result["record"]["decision"]
        == RecipeProvenanceRecoveryStatus.REBUILD_PROVENANCE_READY.value
    )


def test_operator_json_wrong_image_is_ignored(tmp_path):
    root = tmp_path / "operator"
    root.mkdir()
    (root / "operator_recipe.json").write_text(
        json.dumps(
            {
                "image_reference": "programbench/other:task_cleanroom",
                "image_digest": DIGEST,
                "original_cleanroom_build_recipe": "sha256:recipe",
                "base_image_digest": BASE_DIGEST,
            }
        ),
        encoding="utf-8",
    )

    result = _recoverer(tmp_path, root).recover(_gap(tmp_path))

    assert (
        result["record"]["decision"]
        == RecipeProvenanceRecoveryStatus.REBUILD_PROVENANCE_BLOCKED.value
    )


def test_material_fidelity_risk_is_recorded(tmp_path):
    result = _recoverer(tmp_path, tmp_path / "empty").recover(_gap(tmp_path))

    assert (
        RecipeProvenanceRecoveryStatus.MATERIAL_FIDELITY_RISK_REMAINS.value
        in result["record"]["provenance_statuses"]
    )
    assert result["record"]["fidelity_assessment"]["material_change_requires_review"] is True


def test_rebuild_blocked_unless_exact_recipe_and_base_digest(tmp_path):
    result = _recoverer(tmp_path, tmp_path / "empty").recover(_gap(tmp_path))

    assert result["record"]["authorization"]["rebuild_authorized"] is False
    assert (
        RecipeProvenanceRecoveryStatus.REBUILD_NOT_AUTHORIZED.value
        in result["record"]["provenance_statuses"]
    )


def test_docker_pull_is_not_authorized(tmp_path):
    result = _recoverer(tmp_path, tmp_path / "empty").recover(_gap(tmp_path))

    assert result["record"]["authorization"]["docker_pull_authorized"] is False


def test_docker_execution_is_not_authorized(tmp_path):
    result = _recoverer(tmp_path, tmp_path / "empty").recover(_gap(tmp_path))

    assert result["record"]["authorization"]["docker_execution_authorized"] is False


def test_hydration_is_not_authorized(tmp_path):
    result = _recoverer(tmp_path, tmp_path / "empty").recover(_gap(tmp_path))

    assert result["record"]["authorization"]["hydration_authorized"] is False


def test_programbench_rerun_is_not_authorized(tmp_path):
    result = _recoverer(tmp_path, tmp_path / "empty").recover(_gap(tmp_path))

    assert result["record"]["authorization"]["programbench_rerun_authorized"] is False


def test_cache_ready_false(tmp_path):
    result = _recoverer(tmp_path, tmp_path / "empty").recover(_gap(tmp_path))

    assert result["record"]["cache_ready"] is False


def test_executable_false(tmp_path):
    result = _recoverer(tmp_path, tmp_path / "empty").recover(_gap(tmp_path))

    assert result["record"]["executable"] is False


def test_training_ineligible(tmp_path):
    result = _recoverer(tmp_path, tmp_path / "empty").recover(_gap(tmp_path))

    assert result["record"]["training_eligible"] is False


def test_signed_record_is_written(tmp_path):
    result = _recoverer(tmp_path, tmp_path / "empty").recover(_gap(tmp_path))

    assert Path(result["record_path"]).is_file()
    assert verify_cleanroom_recipe_provenance_recovery_record(result["record"])
