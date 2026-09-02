from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_ROOT / "scripts"))

from corpus.programbench.alternate_cleanroom_image_provenance import (  # noqa: E402
    AlternateCleanroomImageProvenanceConfig,
    AlternateCleanroomImageProvenanceStatus,
    ProgramBenchAlternateCleanroomImageProvenance,
)
from corpus.programbench.alternate_cleanroom_image_provenance_record import (  # noqa: E402
    verify_alternate_cleanroom_image_provenance_record,
)
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
from corpus.programbench.operator_provenance_request_packet_record import (  # noqa: E402
    make_operator_provenance_request_packet_record,
    write_operator_provenance_request_packet_record,
)
from corpus.programbench.rebuild_provenance_quarantine_decision_record import (  # noqa: E402
    make_rebuild_provenance_quarantine_decision_record,
    write_rebuild_provenance_quarantine_decision_record,
)

IMAGE = "programbench/doxygen_1776_doxygen.966d98e:task_cleanroom"
DIGEST = "sha256:cc50d0f7e9a1f3f90512e3d4c34781f4686a8fa3774fbff489947ef41bde2e72"
ALT_IMAGE = "programbench/doxygen_1776_doxygen.966d98e:task_cleanroom_go124"
ALT_DIGEST = "sha256:" + "a" * 64


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
            "REBUILD_NOT_AUTHORIZED",
        ],
        authorization={
            "rebuild_authorized": False,
            "cache_ready": False,
            "executable": False,
            "training_eligible": False,
        },
        cache_ready=False,
        executable=False,
    )
    return write_cleanroom_build_recipe_provenance_gap_record(record, tmp_path / "gaps")


def _recovery(
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
            "go_runtime_update_plan_available": True,
            "all_required_provenance_closed": False,
        },
        go_remediation={"current_version": "1.21.0", "target_version": "1.24.13"},
        fidelity_assessment={"fidelity_risk": "material"},
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
    recovery_path = _recovery(
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
        findings={
            "original_recipe_gap_open": True,
            "pinned_base_image_digest_gap_open": True,
            "go_runtime_current": "1.21.0",
            "go_runtime_target": "1.24.13",
            "material_fidelity_change_candidate": True,
        },
        authorization={"cache_ready": False, "executable": False, "training_eligible": False},
        cache_ready=False,
        executable=False,
    )
    return write_rebuild_provenance_quarantine_decision_record(record, tmp_path / "decisions")


def _request(
    tmp_path: Path, *, image: str = IMAGE, digest: str = DIGEST, plan_ref: str | None = None
) -> Path:
    decision_path = _decision(tmp_path, image=image, digest=digest, plan_ref=plan_ref)
    record = make_operator_provenance_request_packet_record(
        status="OPERATOR_PROVENANCE_REQUEST_PACKET_WRITTEN",
        image_reference=image,
        image_digest=digest,
        rebuild_quarantine_decision=decision_path.relative_to(tmp_path).as_posix(),
        current_decision="REBUILD_QUARANTINE_DECISION_PARTIAL_ONLY",
        missing_evidence=[
            "original_cleanroom_build_recipe",
            "original_build_context",
            "pinned_base_image_digest",
            "toolchain_version_provenance",
        ],
        authorization={"cache_ready": False, "executable": False, "training_eligible": False},
        cache_ready=False,
        executable=False,
    )
    return write_operator_provenance_request_packet_record(record, tmp_path / "requests")


def _candidate(root: Path, body: dict) -> Path:
    path = root / "candidate.json"
    root.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body, indent=2), encoding="utf-8")
    return path


def _runner(
    tmp_path: Path,
    search_root: Path | None = None,
    target_image: str = IMAGE,
    target_digest: str = DIGEST,
):
    return ProgramBenchAlternateCleanroomImageProvenance(
        AlternateCleanroomImageProvenanceConfig(
            root=tmp_path,
            output_dir=tmp_path / "alternate_records",
            search_roots=[] if search_root is None else [search_root],
            target_image=target_image,
            target_digest=target_digest,
        )
    )


def _exact_candidate() -> dict:
    return {
        "alternate_cleanroom_candidate": True,
        "alternate_image_reference": ALT_IMAGE,
        "alternate_image_digest": ALT_DIGEST,
        "source_registry": "internal.registry.example/programbench",
        "tag": "task_cleanroom_go124",
        "provenance": {
            "original_recipe": "recipes/doxygen.Dockerfile",
            "recipe_digest": "sha256:" + "b" * 64,
            "base_image_digest": "sha256:" + "c" * 64,
            "toolchain_provenance": {"go": "1.24.13", "digest": "sha256:" + "d" * 64},
        },
        "benchmark_fidelity": {"impact": "material", "reason": "Go runtime update"},
    }


def test_missing_request_blocks(tmp_path):
    result = _runner(tmp_path).discover(tmp_path / "missing.json")
    assert (
        result["record"]["status"]
        == AlternateCleanroomImageProvenanceStatus.ALTERNATE_IMAGE_BLOCKED_NO_REQUEST.value
    )


def test_original_image_mismatch_blocks(tmp_path):
    result = _runner(tmp_path, target_image="programbench/other:task_cleanroom").discover(
        _request(tmp_path)
    )
    assert (
        result["record"]["status"]
        == AlternateCleanroomImageProvenanceStatus.ALTERNATE_IMAGE_BLOCKED_IMAGE_MISMATCH.value
    )


def test_original_digest_mismatch_blocks(tmp_path):
    result = _runner(tmp_path, target_digest="sha256:bad").discover(_request(tmp_path))
    assert (
        result["record"]["status"]
        == AlternateCleanroomImageProvenanceStatus.ALTERNATE_IMAGE_BLOCKED_DIGEST_MISMATCH.value
    )


def test_invalid_upstream_chain_blocks(tmp_path):
    result = _runner(tmp_path).discover(_request(tmp_path, plan_ref="missing-plan.json"))
    assert (
        result["record"]["status"]
        == AlternateCleanroomImageProvenanceStatus.ALTERNATE_IMAGE_BLOCKED_CHAIN_INVALID.value
    )


def test_no_alternate_candidate_found(tmp_path):
    result = _runner(tmp_path, search_root=tmp_path / "empty").discover(_request(tmp_path))
    assert (
        result["record"]["status"]
        == AlternateCleanroomImageProvenanceStatus.ALTERNATE_CLEANROOM_PROVENANCE_NOT_FOUND.value
    )
    assert (
        result["record"]["decision"]
        == AlternateCleanroomImageProvenanceStatus.NO_ALTERNATE_IMAGE_CANDIDATE_FOUND.value
    )


def test_exact_alternate_candidate_is_admissible_candidate_only(tmp_path):
    search_root = tmp_path / "candidates"
    _candidate(search_root, _exact_candidate())
    result = _runner(tmp_path, search_root=search_root).discover(_request(tmp_path))
    assert (
        result["record"]["status"]
        == AlternateCleanroomImageProvenanceStatus.ALTERNATE_CLEANROOM_PROVENANCE_FOUND_EXACT.value
    )
    assert (
        result["record"]["decision"]
        == AlternateCleanroomImageProvenanceStatus.ALTERNATE_IMAGE_CANDIDATE_ADMISSIBLE.value
    )
    assert result["record"]["authorization"]["alternate_candidate_found"] is True


def test_partial_alternate_candidate_is_quarantine_only(tmp_path):
    search_root = tmp_path / "candidates"
    body = _exact_candidate()
    body["provenance"].pop("base_image_digest")
    _candidate(search_root, body)
    result = _runner(tmp_path, search_root=search_root).discover(_request(tmp_path))
    assert (
        result["record"]["status"]
        == AlternateCleanroomImageProvenanceStatus.ALTERNATE_CLEANROOM_PROVENANCE_FOUND_PARTIAL.value
    )
    assert (
        result["record"]["decision"]
        == AlternateCleanroomImageProvenanceStatus.ALTERNATE_IMAGE_CANDIDATE_QUARANTINE_ONLY.value
    )


def test_latest_or_name_only_candidate_is_blocked(tmp_path):
    search_root = tmp_path / "candidates"
    body = _exact_candidate()
    body.pop("alternate_image_digest")
    body["tag"] = "latest"
    _candidate(search_root, body)
    result = _runner(tmp_path, search_root=search_root).discover(_request(tmp_path))
    assert (
        result["record"]["decision"]
        == AlternateCleanroomImageProvenanceStatus.ALTERNATE_IMAGE_CANDIDATE_BLOCKED.value
    )
    assert result["record"]["provenance_findings"]["latest_or_name_only_rejected"] is True


def test_inferred_officialness_candidate_is_blocked(tmp_path):
    search_root = tmp_path / "candidates"
    body = _exact_candidate()
    body["inferred_officialness"] = True
    _candidate(search_root, body)
    result = _runner(tmp_path, search_root=search_root).discover(_request(tmp_path))
    assert (
        result["record"]["decision"]
        == AlternateCleanroomImageProvenanceStatus.ALTERNATE_IMAGE_CANDIDATE_BLOCKED.value
    )
    assert result["record"]["provenance_findings"]["inferred_officialness_rejected"] is True


def test_existing_original_image_is_not_alternate(tmp_path):
    search_root = tmp_path / "candidates"
    body = _exact_candidate()
    body["alternate_image_reference"] = IMAGE
    body["alternate_image_digest"] = DIGEST
    _candidate(search_root, body)
    result = _runner(tmp_path, search_root=search_root).discover(_request(tmp_path))
    assert (
        result["record"]["decision"]
        == AlternateCleanroomImageProvenanceStatus.NO_ALTERNATE_IMAGE_CANDIDATE_FOUND.value
    )


def test_fidelity_change_is_marked(tmp_path):
    search_root = tmp_path / "candidates"
    _candidate(search_root, _exact_candidate())
    result = _runner(tmp_path, search_root=search_root).discover(_request(tmp_path))
    assert result["record"]["benchmark_fidelity_impact"]["fidelity_change_required"] is True


def test_docker_pull_and_execution_blocked(tmp_path):
    search_root = tmp_path / "candidates"
    _candidate(search_root, _exact_candidate())
    result = _runner(tmp_path, search_root=search_root).discover(_request(tmp_path))
    assert result["record"]["authorization"]["docker_pull_authorized"] is False
    assert result["record"]["authorization"]["docker_execution_authorized"] is False


def test_hydration_and_programbench_rerun_blocked(tmp_path):
    search_root = tmp_path / "candidates"
    _candidate(search_root, _exact_candidate())
    result = _runner(tmp_path, search_root=search_root).discover(_request(tmp_path))
    assert result["record"]["authorization"]["hydration_authorized"] is False
    assert result["record"]["authorization"]["programbench_rerun_authorized"] is False


def test_cache_ready_false(tmp_path):
    search_root = tmp_path / "candidates"
    _candidate(search_root, _exact_candidate())
    result = _runner(tmp_path, search_root=search_root).discover(_request(tmp_path))
    assert result["record"]["cache_ready"] is False


def test_executable_false(tmp_path):
    search_root = tmp_path / "candidates"
    _candidate(search_root, _exact_candidate())
    result = _runner(tmp_path, search_root=search_root).discover(_request(tmp_path))
    assert result["record"]["executable"] is False


def test_training_ineligible(tmp_path):
    search_root = tmp_path / "candidates"
    _candidate(search_root, _exact_candidate())
    result = _runner(tmp_path, search_root=search_root).discover(_request(tmp_path))
    assert result["record"]["training_eligible"] is False


def test_records_searched_sources(tmp_path):
    search_root = tmp_path / "candidates"
    _candidate(search_root, _exact_candidate())
    result = _runner(tmp_path, search_root=search_root).discover(_request(tmp_path))
    assert result["record"]["searched_sources"][0]["exists"] is True
    assert result["record"]["searched_sources"][0]["matches"] == 1


def test_signed_record_is_written(tmp_path):
    search_root = tmp_path / "candidates"
    _candidate(search_root, _exact_candidate())
    result = _runner(tmp_path, search_root=search_root).discover(_request(tmp_path))
    assert Path(result["record_path"]).is_file()
    assert verify_alternate_cleanroom_image_provenance_record(result["record"])
