from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_ROOT / "scripts"))

from corpus.programbench.codex_completion_campaign import (  # noqa: E402
    DIGEST,
    IMAGE,
    INSTANCE_ID,
    CampaignConfig,
    ProgramBenchCodexCompletionCampaign,
)
from corpus.programbench.codex_completion_campaign_record import (
    verify_campaign_record,  # noqa: E402
)


def _campaign():
    return ProgramBenchCodexCompletionCampaign(CampaignConfig(root=_ROOT))


def test_sandbox_requirements_are_complete_and_non_executing():
    result = _campaign().sandbox_requirements()
    record = result["record"]
    req = record["sandbox_requirements"]
    assert record["status"] == "SANDBOX_REQUIREMENTS_WRITTEN"
    assert req["network"] == "none"
    assert req["host_docker_socket_mounted"] is False
    assert req["privileged_container"] is False
    assert req["broad_host_mounts"] is False
    assert req["read_only_artifact_input_mounts_where_possible"] is True
    assert req["bounded_temporary_workspace"] is True
    assert req["explicit_output_directory_required"] is True
    assert req["resource_limits"]["process_timeout_seconds"] == 3600
    assert req["environment_sanitization"] is True
    assert req["deterministic_command_capture"] is True
    assert req["stdout_capture"] is True
    assert req["stderr_capture"] is True
    assert req["signed_preflight_record_required"] is True
    assert req["signed_post_run_record_required_if_executed"] is True
    assert req["max_attempts"] == 1
    assert req["instance_scope"] == INSTANCE_ID
    assert req["image_digest"] == DIGEST
    assert record["authorization"]["docker_execution_authorized"] is False
    assert record["cache_ready"] is False
    assert record["executable"] is False
    assert record["training_eligible"] is False


def test_policy_exception_request_is_request_not_approval():
    sandbox = _campaign().sandbox_requirements()
    request = _campaign().policy_exception_request(Path(sandbox["record_path"]))["record"]
    assert request["status"] == "SECURITY_POLICY_EXCEPTION_REQUEST_WRITTEN"
    assert request["image_reference"] == IMAGE
    assert request["image_digest"] == DIGEST
    assert request["scan_summary"] == {
        "critical": 38,
        "high": 617,
        "medium": 2729,
        "low": 154,
        "total": 3538,
    }
    assert request["dominant_risk_category"] == "language_runtime"
    assert request["human_operator_approval_required"] is True
    assert request["authorization"]["docker_execution_authorized"] is False
    assert request["authorization"]["programbench_rerun_authorized"] is False
    assert request["training_eligible"] is False


def test_policy_admission_live_requires_real_approval():
    sandbox = _campaign().sandbox_requirements()
    request = _campaign().policy_exception_request(Path(sandbox["record_path"]))
    admission = _campaign().policy_admission_gate(
        Path(request["record_path"]), Path(sandbox["record_path"])
    )["record"]
    assert admission["status"] == "SECURITY_POLICY_ADMISSION_REQUIRED"
    assert admission["live_policy_admission_accepted"] is False
    assert admission["authorization"]["policy_admission_accepted"] is False
    assert admission["executable"] is False


def test_policy_admission_fixture_acceptance_is_not_live(tmp_path):
    sandbox = _campaign().sandbox_requirements()
    request = _campaign().policy_exception_request(Path(sandbox["record_path"]))
    approval = tmp_path / "approval.json"
    approval.write_text(
        json.dumps(
            {
                "fixture_approval": True,
                "image_reference": IMAGE,
                "image_digest": DIGEST,
                "scan_record": "scan",
                "sandbox_requirements_record": sandbox["record_path"],
                "operator_signature": "fixture",
                "acknowledges_scan_risk": True,
                "permits_only_bounded_official_artifact_evaluation": True,
                "permits_training_eligibility": False,
                "permits_rebuild_remediation": False,
                "permits_broad_docker_use": False,
                "permits_other_programbench_instances": False,
            }
        ),
        encoding="utf-8",
    )
    admission = _campaign().policy_admission_gate(
        Path(request["record_path"]), Path(sandbox["record_path"]), approval
    )["record"]
    assert admission["status"] == "SECURITY_POLICY_ADMISSION_ACCEPTED_FIXTURE"
    assert admission["fixture_only"] is True
    assert admission["live_policy_admission_accepted"] is False
    Path(
        "assurance/evidence/programbench_security_policy_admissions/programbench_doxygen_1776_doxygen.966d98e_task_cleanroom.SECURITY_POLICY_ADMISSION_ACCEPTED_FIXTURE.json"
    ).unlink(missing_ok=True)


def test_execution_preflight_blocks_without_live_policy_admission():
    sandbox = _campaign().sandbox_requirements()
    request = _campaign().policy_exception_request(Path(sandbox["record_path"]))
    admission = _campaign().policy_admission_gate(
        Path(request["record_path"]), Path(sandbox["record_path"])
    )
    preflight = _campaign().execution_preflight(
        Path(sandbox["record_path"]), Path(request["record_path"]), Path(admission["record_path"])
    )["record"]
    assert preflight["status"] == "OFFICIAL_ARTIFACT_PREFLIGHT_BLOCKED_POLICY_ADMISSION_REQUIRED"
    assert preflight["checks"]["scope_exact"] is True
    assert preflight["checks"]["max_attempts_one"] is True
    assert preflight["authorization"]["programbench_rerun_authorized"] is False
    assert preflight["training_eligible"] is False


def test_task_skip_records_precise_non_model_failure_reason():
    sandbox = _campaign().sandbox_requirements()
    request = _campaign().policy_exception_request(Path(sandbox["record_path"]))
    admission = _campaign().policy_admission_gate(
        Path(request["record_path"]), Path(sandbox["record_path"])
    )
    preflight = _campaign().execution_preflight(
        Path(sandbox["record_path"]), Path(request["record_path"]), Path(admission["record_path"])
    )
    skip = _campaign().task_skip(Path(preflight["record_path"]))["record"]
    assert skip["status"] == "TASK_SKIP_WITH_PROVENANCE_REASON_WRITTEN"
    assert skip["skip_reason"] == "POLICY_ADMISSION_REQUIRED_FOR_SCAN_FAILED_OFFICIAL_ARTIFACT"
    assert skip["rerun_authorized"] is False
    assert skip["training_eligible"] is False
    assert "not evaluated" in skip["why_not_model_failure"]


def test_final_state_classifies_doxygen_as_policy_blocked_not_dead_end():
    result = _campaign().run_all()
    final = result["final_state"]["record"]
    assert final["status"] == "DOXYGEN_LANE_FINAL_STATE_WRITTEN"
    assert final["artifact_authority"] == "PRESENT"
    assert final["security_execution_authority"] == "ABSENT_PENDING_OPERATOR_POLICY_ADMISSION"
    assert final["bounded_rerun_authority"] == "BLOCKED_BY_SECURITY_PREFLIGHT"
    assert final["official_score_available"] is False
    assert final["training_eligible"] is False
    assert final["next_unblocker"] == "OPERATOR_SECURITY_POLICY_ADMISSION"
    assert final["clean_skip_allowed"] is True


def test_status_board_does_not_mark_blocked_task_ready():
    result = _campaign().run_all()
    board = result["status_board"]["record"]
    row = board["entries"][0]
    assert row["instance_id"] == INSTANCE_ID
    assert row["status"] == "SKIPPED_WITH_PROVENANCE_REASON"
    assert row["security_policy_status"] == "BLOCKED_POLICY_ADMISSION_REQUIRED"
    assert row["training_eligibility"] is False
    assert board["summary"]["ready"] == 0


def test_training_negative_guard_blocks_metadata_security_provenance_and_skip_rows():
    result = _campaign().run_all()
    guard = result["training_negative_guard"]["record"]
    assert guard["status"] == "TRAINING_ELIGIBILITY_NEGATIVE_GUARD_WRITTEN"
    assert guard["rules"]["metadata_only_artifact_is_not_training_eligible"] is True
    assert guard["rules"]["scan_failed_artifact_is_not_training_eligible"] is True
    assert guard["rules"]["policy_admission_required_is_not_training_eligible"] is True
    assert guard["rules"]["partial_provenance_is_not_training_eligible"] is True
    assert guard["rules"]["skipped_task_is_not_negative_model_sample"] is True
    assert guard["training_eligible"] is False


def test_readiness_matrix_points_to_operator_policy_admission():
    result = _campaign().run_all()
    matrix = result["readiness_matrix"]["record"]
    row = matrix["entries"][0]
    assert row["status"] == "BLOCKED_POLICY_ADMISSION_REQUIRED"
    assert row["artifact_authority"] == "PRESENT"
    assert row["security_policy_admitted"] is False
    assert row["execution_preflight_ready"] is False
    assert row["training_eligible"] is False
    assert "operator security policy admission" in row["next_action"]


def test_all_campaign_records_are_signed():
    result = _campaign().run_all()
    for item in result.values():
        assert Path(item["record_path"]).is_file()
        assert verify_campaign_record(item["record"])
