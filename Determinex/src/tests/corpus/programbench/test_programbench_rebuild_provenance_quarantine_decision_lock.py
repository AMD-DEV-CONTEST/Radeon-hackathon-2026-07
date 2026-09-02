from __future__ import annotations

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
from corpus.programbench.cleanroom_recipe_provenance_recovery_record import (  # noqa: E402
    make_cleanroom_recipe_provenance_recovery_record,
    write_cleanroom_recipe_provenance_recovery_record,
)
from corpus.programbench.rebuild_provenance_quarantine_decision import (  # noqa: E402
    ProgramBenchRebuildProvenanceQuarantineDecision,
    RebuildProvenanceQuarantineDecisionConfig,
    RebuildProvenanceQuarantineDecisionStatus,
)
from corpus.programbench.rebuild_provenance_quarantine_decision_record import (  # noqa: E402
    verify_rebuild_provenance_quarantine_decision_record,
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
        required_inputs={"go_version_target": "1.24.13"},
        fidelity_risk={"risk": "material"},
        cache_ready=False,
        executable=False,
    )
    return write_cleanroom_image_remediation_plan_record(record, tmp_path / "plans")


def _build_recipe_recovery(tmp_path: Path, *, image: str = IMAGE, digest: str = DIGEST) -> Path:
    record = make_cleanroom_build_recipe_recovery_record(
        status="BUILD_RECIPE_RECONSTRUCTED_QUARANTINE_ONLY",
        image_reference=image,
        image_digest=digest,
        remediation_plan="plans/plan.json",
        recipe_components={
            "original_recipe_file_recovered": False,
            "base_image_digest_present": False,
            "reconstructed_from_image_history": True,
        },
        go_update={
            "current_version_detected": "1.21.0",
            "target_version": "1.24.13",
            "recipe_compatible": True,
        },
        fidelity_assessment={"fidelity_class": "material_fidelity_change"},
        cache_ready=False,
        executable=False,
    )
    return write_cleanroom_build_recipe_recovery_record(record, tmp_path / "recipe_recovery")


def _gap(tmp_path: Path, *, image: str = IMAGE, digest: str = DIGEST) -> Path:
    result = ProgramBenchCleanroomBuildRecipeProvenanceGap(
        BuildRecipeProvenanceGapConfig(
            root=tmp_path,
            output_dir=tmp_path / "gaps",
            target_image=image,
            target_digest=digest,
        )
    ).write_gap(
        _plan(tmp_path, image=image, digest=digest),
        _build_recipe_recovery(tmp_path, image=image, digest=digest),
    )
    return Path(result["record_path"])


def _recipe_provenance_recovery(
    tmp_path: Path,
    *,
    image: str = IMAGE,
    digest: str = DIGEST,
    decision: str = "REBUILD_PROVENANCE_PARTIAL_QUARANTINE_ONLY",
    original_closed: bool = False,
    base_closed: bool = False,
    go_available: bool = True,
    plan_ref: str | None = None,
    recipe_ref: str | None = None,
    gap_ref: str | None = None,
) -> Path:
    plan_path = _plan(tmp_path, image=image, digest=digest)
    recipe_path = _build_recipe_recovery(tmp_path, image=image, digest=digest)
    gap_path = _gap(tmp_path, image=image, digest=digest)
    status = (
        "RECIPE_PROVENANCE_RECOVERED_EXACT"
        if decision == "REBUILD_PROVENANCE_READY"
        else "PROVENANCE_RECOVERY_EXHAUSTED"
        if decision == "REBUILD_PROVENANCE_BLOCKED"
        else "RECIPE_PROVENANCE_RECOVERED_PARTIAL"
    )
    record = make_cleanroom_recipe_provenance_recovery_record(
        status=status,
        decision=decision,
        image_reference=image,
        image_digest=digest,
        provenance_gap=gap_ref
        if gap_ref is not None
        else gap_path.relative_to(tmp_path).as_posix(),
        remediation_plan=plan_ref
        if plan_ref is not None
        else plan_path.relative_to(tmp_path).as_posix(),
        recipe_recovery=recipe_ref
        if recipe_ref is not None
        else recipe_path.relative_to(tmp_path).as_posix(),
        gap_closure={
            "original_cleanroom_build_recipe_closed": original_closed,
            "pinned_base_image_digest_closed": base_closed,
            "non_history_recipe_source_closed": original_closed,
            "go_runtime_update_plan_available": go_available,
            "all_required_provenance_closed": original_closed and base_closed and go_available,
        },
        go_remediation={
            "current_version": "1.21.0",
            "target_version": "1.24.13",
            "compatible_with_recovered_recipe": go_available,
        },
        fidelity_assessment={
            "fidelity_risk": "material",
            "material_change_requires_review": True,
        },
        authorization={
            "rebuild_authorized": original_closed and base_closed,
            "cache_ready": False,
            "executable": False,
            "training_eligible": False,
        },
        cache_ready=False,
        executable=False,
    )
    return write_cleanroom_recipe_provenance_recovery_record(record, tmp_path / "recipe_provenance")


def _decider(tmp_path: Path, target_image: str = IMAGE, target_digest: str = DIGEST):
    return ProgramBenchRebuildProvenanceQuarantineDecision(
        RebuildProvenanceQuarantineDecisionConfig(
            root=tmp_path,
            output_dir=tmp_path / "decisions",
            target_image=target_image,
            target_digest=target_digest,
        )
    )


def test_missing_recovery_blocks(tmp_path):
    result = _decider(tmp_path).decide(tmp_path / "missing.json")

    assert (
        result["record"]["status"]
        == RebuildProvenanceQuarantineDecisionStatus.REBUILD_QUARANTINE_DECISION_BLOCKED_NO_RECOVERY.value
    )
    assert (
        result["record"]["decision"]
        == RebuildProvenanceQuarantineDecisionStatus.REBUILD_QUARANTINE_DECISION_BLOCKED.value
    )


def test_image_mismatch_blocks(tmp_path):
    result = _decider(tmp_path, target_image="programbench/other:task_cleanroom").decide(
        _recipe_provenance_recovery(tmp_path)
    )

    assert (
        result["record"]["status"]
        == RebuildProvenanceQuarantineDecisionStatus.REBUILD_QUARANTINE_DECISION_BLOCKED_IMAGE_MISMATCH.value
    )


def test_digest_mismatch_blocks(tmp_path):
    result = _decider(tmp_path, target_digest="sha256:bad").decide(
        _recipe_provenance_recovery(tmp_path)
    )

    assert (
        result["record"]["status"]
        == RebuildProvenanceQuarantineDecisionStatus.REBUILD_QUARANTINE_DECISION_BLOCKED_DIGEST_MISMATCH.value
    )


def test_invalid_referenced_chain_blocks(tmp_path):
    recovery = _recipe_provenance_recovery(tmp_path, plan_ref="missing-plan.json")

    result = _decider(tmp_path).decide(recovery)

    assert (
        result["record"]["status"]
        == RebuildProvenanceQuarantineDecisionStatus.REBUILD_QUARANTINE_DECISION_BLOCKED_CHAIN_INVALID.value
    )
    assert (
        result["record"]["decision"]
        == RebuildProvenanceQuarantineDecisionStatus.REBUILD_QUARANTINE_DECISION_BLOCKED.value
    )


def test_partial_recovery_becomes_partial_only_decision(tmp_path):
    result = _decider(tmp_path).decide(_recipe_provenance_recovery(tmp_path))

    assert (
        result["record"]["status"]
        == RebuildProvenanceQuarantineDecisionStatus.REBUILD_QUARANTINE_DECISION_PARTIAL_ONLY.value
    )
    assert result["record"]["findings"]["rebuild_provenance_authorized"] is False


def test_blocked_recovery_becomes_blocked_decision(tmp_path):
    recovery = _recipe_provenance_recovery(
        tmp_path, decision="REBUILD_PROVENANCE_BLOCKED", go_available=False
    )

    result = _decider(tmp_path).decide(recovery)

    assert (
        result["record"]["status"]
        == RebuildProvenanceQuarantineDecisionStatus.REBUILD_QUARANTINE_DECISION_BLOCKED.value
    )


def test_ready_recovery_becomes_ready_decision_without_execution(tmp_path):
    recovery = _recipe_provenance_recovery(
        tmp_path,
        decision="REBUILD_PROVENANCE_READY",
        original_closed=True,
        base_closed=True,
    )

    result = _decider(tmp_path).decide(recovery)

    assert (
        result["record"]["status"]
        == RebuildProvenanceQuarantineDecisionStatus.REBUILD_QUARANTINE_DECISION_READY.value
    )
    assert result["record"]["authorization"]["rebuild_provenance_ready"] is True
    assert result["record"]["authorization"]["image_rebuild_authorized"] is False


def test_distinguishes_technical_remediation_from_authority(tmp_path):
    result = _decider(tmp_path).decide(_recipe_provenance_recovery(tmp_path))

    assert result["record"]["findings"]["remediation_technically_possible"] is True
    assert result["record"]["findings"]["rebuild_provenance_authorized"] is False
    assert result["record"]["findings"]["partial_provenance_is_sufficient_for_rebuild"] is False


def test_original_recipe_gap_remains_open(tmp_path):
    result = _decider(tmp_path).decide(_recipe_provenance_recovery(tmp_path))

    assert result["record"]["findings"]["original_recipe_gap_open"] is True
    assert (
        RebuildProvenanceQuarantineDecisionStatus.ORIGINAL_RECIPE_GAP_OPEN.value
        in result["record"]["decision_statuses"]
    )


def test_base_digest_gap_remains_open(tmp_path):
    result = _decider(tmp_path).decide(_recipe_provenance_recovery(tmp_path))

    assert result["record"]["findings"]["pinned_base_image_digest_gap_open"] is True
    assert (
        RebuildProvenanceQuarantineDecisionStatus.PINNED_BASE_IMAGE_DIGEST_GAP_OPEN.value
        in result["record"]["decision_statuses"]
    )


def test_material_fidelity_change_candidate_recorded(tmp_path):
    result = _decider(tmp_path).decide(_recipe_provenance_recovery(tmp_path))

    assert result["record"]["findings"]["material_fidelity_change_candidate"] is True


def test_rebuild_is_not_authorized_for_partial(tmp_path):
    result = _decider(tmp_path).decide(_recipe_provenance_recovery(tmp_path))

    assert result["record"]["authorization"]["image_rebuild_authorized"] is False


def test_hydration_not_authorized(tmp_path):
    result = _decider(tmp_path).decide(_recipe_provenance_recovery(tmp_path))

    assert result["record"]["authorization"]["hydration_authorized"] is False


def test_programbench_rerun_not_authorized(tmp_path):
    result = _decider(tmp_path).decide(_recipe_provenance_recovery(tmp_path))

    assert result["record"]["authorization"]["programbench_rerun_authorized"] is False


def test_cache_ready_false(tmp_path):
    result = _decider(tmp_path).decide(_recipe_provenance_recovery(tmp_path))

    assert result["record"]["cache_ready"] is False


def test_executable_false(tmp_path):
    result = _decider(tmp_path).decide(_recipe_provenance_recovery(tmp_path))

    assert result["record"]["executable"] is False


def test_training_ineligible(tmp_path):
    result = _decider(tmp_path).decide(_recipe_provenance_recovery(tmp_path))

    assert result["record"]["training_eligible"] is False


def test_signed_decision_record_is_written(tmp_path):
    result = _decider(tmp_path).decide(_recipe_provenance_recovery(tmp_path))

    assert Path(result["record_path"]).is_file()
    assert verify_rebuild_provenance_quarantine_decision_record(result["record"])
