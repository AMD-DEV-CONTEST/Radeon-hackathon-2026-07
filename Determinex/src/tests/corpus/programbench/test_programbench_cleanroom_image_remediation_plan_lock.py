from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_ROOT / "scripts"))

from corpus.programbench.cleanroom_image_remediation_plan import (  # noqa: E402
    CleanroomImageRemediationPlanConfig,
    CleanroomImageRemediationPlanStatus,
    ProgramBenchCleanroomImageRemediationPlan,
)
from corpus.programbench.cleanroom_image_remediation_plan_record import (
    verify_cleanroom_image_remediation_plan_record,  # noqa: E402
)
from corpus.programbench.cleanroom_image_scan_record import (  # noqa: E402
    make_cleanroom_image_scan_record,
    write_cleanroom_image_scan_record,
)
from corpus.programbench.cleanroom_image_scan_triage_record import (  # noqa: E402
    make_cleanroom_image_scan_triage_record,
    write_cleanroom_image_scan_triage_record,
)

IMAGE = "programbench/doxygen_1776_doxygen.966d98e:task_cleanroom"
DIGEST = "sha256:cc50d0f7e9a1f3f90512e3d4c34781f4686a8fa3774fbff489947ef41bde2e72"


def _write_scan(tmp_path: Path) -> Path:
    record = make_cleanroom_image_scan_record(
        status="CLEANROOM_IMAGE_SCAN_FAILED",
        import_record="import.json",
        image_reference=IMAGE,
        artifact_path="artifact.tar",
        expected_digest=DIGEST,
        observed_digest=DIGEST,
        file_sha256="sha256:file",
        file_size=123,
        scanner="trivy",
        scanner_version="Version: 0.test",
        findings_summary={
            "critical": 2,
            "high": 2,
            "medium": 1,
            "low": 0,
            "unknown": 0,
            "total": 5,
        },
        normalized_findings=[],
        reasons=["critical_or_high_findings_present"],
        cache_ready=False,
        executable=False,
    )
    return write_cleanroom_image_scan_record(record, tmp_path / "scan")


def _write_triage(
    tmp_path: Path, *, recommendation: str = "REMEDIATE_IMAGE_REQUIRED", policy_blocked: bool = True
) -> Path:
    record = make_cleanroom_image_scan_triage_record(
        status="CLEANROOM_IMAGE_SCAN_TRIAGED",
        recommendation=recommendation,
        image_reference=IMAGE,
        artifact_path="artifact.tar",
        expected_digest=DIGEST,
        observed_digest=DIGEST,
        file_sha256="sha256:file",
        scan_record="scan.json",
        hydration_record="hydration.json",
        severity_counts={"critical": 2, "high": 2, "medium": 1, "low": 0, "unknown": 0, "total": 5},
        fixed_version_summary={
            "critical_high_with_fix": 4,
            "critical_high_without_fix": 0,
            "critical_with_fix": 2,
            "critical_without_fix": 0,
            "high_with_fix": 2,
            "high_without_fix": 0,
            "no_fixed_version_total": 1,
        },
        category_summary={
            "all_findings": {"language_runtime": 4, "os_base": 1},
            "critical_high": {"language_runtime": 4},
            "dominant_category": "language_runtime",
        },
        top_critical=[
            {
                "id": "CVE-2024-24790",
                "package": "stdlib",
                "installed_version": "v1.21.0",
                "fixed_version": "1.21.11, 1.22.4",
                "severity": "critical",
                "count": 2,
                "category": "language_runtime",
            }
        ],
        top_high=[
            {
                "id": "CVE-2023-39321",
                "package": "stdlib",
                "installed_version": "v1.21.0",
                "fixed_version": "1.21.1",
                "severity": "high",
                "count": 2,
                "category": "language_runtime",
            }
        ],
        policy_blocked=policy_blocked,
        cache_ready=False,
        executable=False,
    )
    return write_cleanroom_image_scan_triage_record(record, tmp_path / "triage")


def _planner(tmp_path: Path, **kwargs) -> ProgramBenchCleanroomImageRemediationPlan:
    return ProgramBenchCleanroomImageRemediationPlan(
        CleanroomImageRemediationPlanConfig(root=tmp_path, output_dir=tmp_path / "plans", **kwargs)
    )


def test_missing_scan_evidence_blocks_plan(tmp_path):
    triage = _write_triage(tmp_path)
    result = _planner(tmp_path).plan(tmp_path / "missing.json", triage)

    assert (
        result["record"]["status"]
        == CleanroomImageRemediationPlanStatus.CLEANROOM_IMAGE_REMEDIATION_PLAN_BLOCKED_NO_SCAN.value
    )


def test_missing_triage_evidence_blocks_plan(tmp_path):
    scan = _write_scan(tmp_path)
    result = _planner(tmp_path).plan(scan, tmp_path / "missing.json")

    assert (
        result["record"]["status"]
        == CleanroomImageRemediationPlanStatus.CLEANROOM_IMAGE_REMEDIATION_PLAN_BLOCKED_NO_TRIAGE.value
    )


def test_non_remediate_recommendation_routes_to_not_required(tmp_path):
    result = _planner(tmp_path).plan(
        _write_scan(tmp_path),
        _write_triage(tmp_path, recommendation="POLICY_EXCEPTION_REVIEW_REQUIRED"),
    )

    assert (
        result["record"]["status"]
        == CleanroomImageRemediationPlanStatus.CLEANROOM_IMAGE_REMEDIATION_PLAN_NOT_REQUIRED.value
    )


def test_policy_unblocked_image_does_not_need_remediation_plan(tmp_path):
    result = _planner(tmp_path).plan(
        _write_scan(tmp_path), _write_triage(tmp_path, policy_blocked=False)
    )

    assert result["record"]["recommendation"] == "NO_REMEDIATION_REQUIRED"


def test_language_runtime_dominance_produces_runtime_update_strategy(tmp_path):
    result = _planner(tmp_path).plan(_write_scan(tmp_path), _write_triage(tmp_path))

    assert result["record"]["dominant_risk_category"] == "language_runtime"
    assert (
        result["record"]["remediation_strategies"][0]["strategy"] == "update_go_runtime_toolchain"
    )


def test_go_stdlib_findings_produce_go_runtime_update_strategy(tmp_path):
    result = _planner(tmp_path).plan(_write_scan(tmp_path), _write_triage(tmp_path))

    assert result["record"]["required_inputs"]["go_version_target"] == "1.24.13"
    assert "stdlib" in {item["package"] for item in result["record"]["top_drivers"]}


def test_missing_build_recipe_marks_requires_build_recipe(tmp_path):
    result = _planner(tmp_path).plan(_write_scan(tmp_path), _write_triage(tmp_path))

    assert (
        CleanroomImageRemediationPlanStatus.CLEANROOM_IMAGE_REMEDIATION_REQUIRES_BUILD_RECIPE.value
        in result["record"]["plan_statuses"]
    )


def test_missing_base_provenance_marks_requires_base_provenance(tmp_path):
    result = _planner(tmp_path).plan(_write_scan(tmp_path), _write_triage(tmp_path))

    assert (
        CleanroomImageRemediationPlanStatus.CLEANROOM_IMAGE_REMEDIATION_REQUIRES_BASE_PROVENANCE.value
        in result["record"]["plan_statuses"]
    )


def test_plan_marks_benchmark_fidelity_risk_when_runtime_or_base_changes(tmp_path):
    result = _planner(tmp_path).plan(_write_scan(tmp_path), _write_triage(tmp_path))

    assert result["record"]["fidelity_risk"]["risk"] == "material"
    assert result["record"]["fidelity_risk"]["must_revalidate_with_bounded_rerun"] is True


def test_plan_requires_scan_rerun_after_rebuild(tmp_path):
    result = _planner(tmp_path).plan(_write_scan(tmp_path), _write_triage(tmp_path))

    assert result["record"]["required_inputs"]["scanner_rerun_required"] is True


def test_plan_requires_hydration_policy_rerun_after_scan(tmp_path):
    result = _planner(tmp_path).plan(_write_scan(tmp_path), _write_triage(tmp_path))

    assert result["record"]["required_inputs"]["hydration_policy_rerun_required"] is True


def test_plan_requires_bounded_rerun_revalidation_before_execution(tmp_path):
    result = _planner(tmp_path).plan(_write_scan(tmp_path), _write_triage(tmp_path))

    assert result["record"]["required_inputs"]["bounded_rerun_revalidation_required"] is True


def test_plan_does_not_mark_scan_passed(tmp_path):
    result = _planner(tmp_path).plan(_write_scan(tmp_path), _write_triage(tmp_path))

    assert "CLEANROOM_IMAGE_SCAN_PASSED" not in result["record"]["plan_statuses"]


def test_plan_does_not_mark_cache_ready(tmp_path):
    result = _planner(tmp_path).plan(_write_scan(tmp_path), _write_triage(tmp_path))

    assert result["record"]["cache_ready"] is False


def test_plan_does_not_mark_executable_true(tmp_path):
    result = _planner(tmp_path).plan(_write_scan(tmp_path), _write_triage(tmp_path))

    assert result["record"]["executable"] is False


def test_plan_does_not_mark_training_eligible_true(tmp_path):
    result = _planner(tmp_path).plan(_write_scan(tmp_path), _write_triage(tmp_path))

    assert result["record"]["training_eligible"] is False


def test_signed_remediation_plan_record_is_produced(tmp_path):
    result = _planner(tmp_path).plan(_write_scan(tmp_path), _write_triage(tmp_path))

    assert Path(result["record_path"]).is_file()
    assert verify_cleanroom_image_remediation_plan_record(result["record"])
