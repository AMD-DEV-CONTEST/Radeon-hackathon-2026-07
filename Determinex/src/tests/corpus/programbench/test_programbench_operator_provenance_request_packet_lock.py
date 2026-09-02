from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_ROOT / "scripts"))

from corpus.programbench.cleanroom_build_recipe_provenance_gap_record import (  # noqa: E402
    make_cleanroom_build_recipe_provenance_gap_record,
    write_cleanroom_build_recipe_provenance_gap_record,
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
from corpus.programbench.operator_provenance_request_packet import (  # noqa: E402
    OperatorProvenanceRequestPacketConfig,
    OperatorProvenanceRequestPacketStatus,
    ProgramBenchOperatorProvenanceRequestPacket,
)
from corpus.programbench.operator_provenance_request_packet_record import (  # noqa: E402
    verify_operator_provenance_request_packet_record,
)
from corpus.programbench.rebuild_provenance_quarantine_decision_record import (  # noqa: E402
    make_rebuild_provenance_quarantine_decision_record,
    write_rebuild_provenance_quarantine_decision_record,
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


def _recipe_recovery(tmp_path: Path, *, image: str = IMAGE, digest: str = DIGEST) -> Path:
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


def _gap(
    tmp_path: Path, plan_path: Path, recipe_path: Path, *, image: str = IMAGE, digest: str = DIGEST
) -> Path:
    record = make_cleanroom_build_recipe_provenance_gap_record(
        status="BUILD_RECIPE_PROVENANCE_GAP_WRITTEN",
        image_reference=image,
        image_digest=digest,
        remediation_plan=plan_path.relative_to(tmp_path).as_posix(),
        recipe_recovery=recipe_path.relative_to(tmp_path).as_posix(),
        gap_statuses=[
            "ORIGINAL_RECIPE_MISSING",
            "BASE_IMAGE_DIGEST_MISSING",
            "RECONSTRUCTED_FROM_IMAGE_HISTORY_ONLY",
            "MATERIAL_FIDELITY_RISK",
            "REBUILD_NOT_AUTHORIZED",
        ],
        missing_provenance_components=[
            {"id": "original_cleanroom_build_recipe"},
            {"id": "pinned_base_image_digest"},
        ],
        closure_requirements=[
            {"id": "original_cleanroom_build_recipe"},
            {"id": "pinned_base_image_digest"},
        ],
        observed_recipe_state={
            "original_recipe_file_recovered": False,
            "base_image_digest_present": False,
            "reconstructed_recipe_source": "OCI config history only",
            "go_current_version": "1.21.0",
            "go_target_version": "1.24.13",
        },
        authorization={
            "rebuild_authorized": False,
            "hydration_authorized": False,
            "programbench_rerun_authorized": False,
            "cache_ready": False,
            "executable": False,
            "training_eligible": False,
        },
        cache_ready=False,
        executable=False,
    )
    return write_cleanroom_build_recipe_provenance_gap_record(record, tmp_path / "gaps")


def _recipe_provenance_recovery(
    tmp_path: Path,
    plan_path: Path,
    recipe_path: Path,
    gap_path: Path,
    *,
    image: str = IMAGE,
    digest: str = DIGEST,
) -> Path:
    record = make_cleanroom_recipe_provenance_recovery_record(
        status="RECIPE_PROVENANCE_RECOVERED_PARTIAL",
        decision="REBUILD_PROVENANCE_PARTIAL_QUARANTINE_ONLY",
        image_reference=image,
        image_digest=digest,
        provenance_gap=gap_path.relative_to(tmp_path).as_posix(),
        remediation_plan=plan_path.relative_to(tmp_path).as_posix(),
        recipe_recovery=recipe_path.relative_to(tmp_path).as_posix(),
        gap_closure={
            "original_cleanroom_build_recipe_closed": False,
            "pinned_base_image_digest_closed": False,
            "non_history_recipe_source_closed": False,
            "go_runtime_update_plan_available": True,
            "all_required_provenance_closed": False,
        },
        go_remediation={
            "current_version": "1.21.0",
            "target_version": "1.24.13",
            "compatible_with_recovered_recipe": True,
        },
        fidelity_assessment={"fidelity_risk": "material", "material_change_requires_review": True},
        authorization={
            "rebuild_authorized": False,
            "cache_ready": False,
            "executable": False,
            "training_eligible": False,
        },
        cache_ready=False,
        executable=False,
    )
    return write_cleanroom_recipe_provenance_recovery_record(record, tmp_path / "recipe_provenance")


def _decision(
    tmp_path: Path, *, image: str = IMAGE, digest: str = DIGEST, plan_ref: str | None = None
) -> Path:
    plan_path = _plan(tmp_path, image=image, digest=digest)
    recipe_path = _recipe_recovery(tmp_path, image=image, digest=digest)
    gap_path = _gap(tmp_path, plan_path, recipe_path, image=image, digest=digest)
    recovery_path = _recipe_provenance_recovery(
        tmp_path, plan_path, recipe_path, gap_path, image=image, digest=digest
    )
    record = make_rebuild_provenance_quarantine_decision_record(
        status="REBUILD_QUARANTINE_DECISION_PARTIAL_ONLY",
        decision="REBUILD_QUARANTINE_DECISION_PARTIAL_ONLY",
        image_reference=image,
        image_digest=digest,
        recipe_provenance_recovery=recovery_path.relative_to(tmp_path).as_posix(),
        remediation_plan=plan_ref
        if plan_ref is not None
        else plan_path.relative_to(tmp_path).as_posix(),
        recipe_recovery=recipe_path.relative_to(tmp_path).as_posix(),
        provenance_gap=gap_path.relative_to(tmp_path).as_posix(),
        decision_statuses=[
            "REBUILD_QUARANTINE_DECISION_PARTIAL_ONLY",
            "REBUILD_PROVENANCE_NOT_AUTHORIZED",
            "ORIGINAL_RECIPE_GAP_OPEN",
            "PINNED_BASE_IMAGE_DIGEST_GAP_OPEN",
        ],
        findings={
            "original_recipe_gap_open": True,
            "pinned_base_image_digest_gap_open": True,
            "go_runtime_current": "1.21.0",
            "go_runtime_target": "1.24.13",
            "go_runtime_remediation_path_available": True,
            "remediation_technically_possible": True,
            "rebuild_provenance_authorized": False,
            "material_fidelity_change_candidate": True,
            "partial_provenance_is_sufficient_for_rebuild": False,
        },
        authorization={
            "image_rebuild_authorized": False,
            "docker_pull_authorized": False,
            "docker_execution_authorized": False,
            "hydration_authorized": False,
            "programbench_rerun_authorized": False,
            "cache_ready": False,
            "executable": False,
            "training_eligible": False,
        },
        required_next_evidence=["original_cleanroom_build_recipe", "pinned_base_image_digest"],
        cache_ready=False,
        executable=False,
    )
    return write_rebuild_provenance_quarantine_decision_record(record, tmp_path / "decisions")


def _requester(tmp_path: Path, target_image: str = IMAGE, target_digest: str = DIGEST):
    return ProgramBenchOperatorProvenanceRequestPacket(
        OperatorProvenanceRequestPacketConfig(
            root=tmp_path,
            output_dir=tmp_path / "requests",
            target_image=target_image,
            target_digest=target_digest,
        )
    )


def test_missing_decision_blocks_request(tmp_path):
    result = _requester(tmp_path).write_packet(tmp_path / "missing.json")

    assert (
        result["record"]["status"]
        == OperatorProvenanceRequestPacketStatus.OPERATOR_PROVENANCE_REQUEST_BLOCKED_NO_DECISION.value
    )


def test_wrong_image_reference_blocks(tmp_path):
    result = _requester(tmp_path, target_image="programbench/other:task_cleanroom").write_packet(
        _decision(tmp_path)
    )

    assert (
        result["record"]["status"]
        == OperatorProvenanceRequestPacketStatus.OPERATOR_PROVENANCE_REQUEST_BLOCKED_IMAGE_MISMATCH.value
    )


def test_wrong_digest_blocks(tmp_path):
    result = _requester(tmp_path, target_digest="sha256:bad").write_packet(_decision(tmp_path))

    assert (
        result["record"]["status"]
        == OperatorProvenanceRequestPacketStatus.OPERATOR_PROVENANCE_REQUEST_BLOCKED_DIGEST_MISMATCH.value
    )


def test_invalid_upstream_chain_blocks(tmp_path):
    result = _requester(tmp_path).write_packet(_decision(tmp_path, plan_ref="missing-plan.json"))

    assert (
        result["record"]["status"]
        == OperatorProvenanceRequestPacketStatus.OPERATOR_PROVENANCE_REQUEST_BLOCKED_CHAIN_INVALID.value
    )


def test_valid_partial_decision_writes_request_packet(tmp_path):
    result = _requester(tmp_path).write_packet(_decision(tmp_path))

    assert (
        result["record"]["status"]
        == OperatorProvenanceRequestPacketStatus.OPERATOR_PROVENANCE_REQUEST_PACKET_WRITTEN.value
    )
    assert result["record"]["current_decision"] == "REBUILD_QUARANTINE_DECISION_PARTIAL_ONLY"


def test_packet_requires_original_recipe_and_base_digest(tmp_path):
    result = _requester(tmp_path).write_packet(_decision(tmp_path))

    assert "original_cleanroom_build_recipe" in result["record"]["missing_evidence"]
    assert "pinned_base_image_digest" in result["record"]["missing_evidence"]


def test_packet_requires_original_build_context_and_toolchain_provenance(tmp_path):
    result = _requester(tmp_path).write_packet(_decision(tmp_path))

    assert "original_build_context" in result["record"]["missing_evidence"]
    assert "toolchain_version_provenance" in result["record"]["missing_evidence"]


def test_packet_confirms_go_runtime_source_and_target(tmp_path):
    result = _requester(tmp_path).write_packet(_decision(tmp_path))
    toolchain = result["record"]["toolchain_requirements"]

    assert toolchain["original_go_runtime_expected"] == "1.21.0"
    assert toolchain["remediation_target_go_runtime"] == "1.24.13"


def test_packet_discloses_benchmark_fidelity_impact(tmp_path):
    result = _requester(tmp_path).write_packet(_decision(tmp_path))

    assert result["record"]["benchmark_fidelity_impact"]["fidelity_risk"] == "material"
    assert (
        result["record"]["benchmark_fidelity_impact"]["packet_itself_authorizes_rebuild"] is False
    )


def test_acceptable_forms_are_machine_visible(tmp_path):
    result = _requester(tmp_path).write_packet(_decision(tmp_path))

    assert (
        "original Dockerfile/build recipe with provenance"
        in result["record"]["acceptable_provenance_forms"]
    )
    assert (
        "operator-signed provenance packet tying source, base digest, recipe, and target image together"
        in result["record"]["acceptable_provenance_forms"]
    )


def test_unacceptable_forms_reject_history_and_latest_only(tmp_path):
    result = _requester(tmp_path).write_packet(_decision(tmp_path))

    assert "latest tags" in result["record"]["unacceptable_provenance_forms"]
    assert "OCI history alone" in result["record"]["unacceptable_provenance_forms"]
    assert (
        "reconstructed Dockerfile-style steps alone"
        in result["record"]["unacceptable_provenance_forms"]
    )


def test_operator_admission_checklist_is_present(tmp_path):
    result = _requester(tmp_path).write_packet(_decision(tmp_path))

    assert any(
        "pinned base image digest" in item
        for item in result["record"]["operator_admission_checklist"]
    )


def test_request_packet_blocks_rebuild(tmp_path):
    result = _requester(tmp_path).write_packet(_decision(tmp_path))

    assert result["record"]["authorization"]["image_rebuild_authorized"] is False


def test_request_packet_blocks_docker_execution(tmp_path):
    result = _requester(tmp_path).write_packet(_decision(tmp_path))

    assert result["record"]["authorization"]["docker_execution_authorized"] is False


def test_request_packet_blocks_hydration_and_rerun(tmp_path):
    result = _requester(tmp_path).write_packet(_decision(tmp_path))

    assert result["record"]["authorization"]["hydration_authorized"] is False
    assert result["record"]["authorization"]["programbench_rerun_authorized"] is False


def test_request_packet_keeps_cache_ready_false(tmp_path):
    result = _requester(tmp_path).write_packet(_decision(tmp_path))

    assert result["record"]["cache_ready"] is False


def test_request_packet_keeps_executable_false(tmp_path):
    result = _requester(tmp_path).write_packet(_decision(tmp_path))

    assert result["record"]["executable"] is False


def test_request_packet_keeps_training_ineligible(tmp_path):
    result = _requester(tmp_path).write_packet(_decision(tmp_path))

    assert result["record"]["training_eligible"] is False


def test_signed_request_packet_is_written(tmp_path):
    result = _requester(tmp_path).write_packet(_decision(tmp_path))

    assert Path(result["record_path"]).is_file()
    assert verify_operator_provenance_request_packet_record(result["record"])
