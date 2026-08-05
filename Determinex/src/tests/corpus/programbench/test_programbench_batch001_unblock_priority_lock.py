from __future__ import annotations

from corpus.programbench.batch001_unblock_priority import (
    PriorityConfig,
    ProgramBenchBatch001UnblockPriority,
)
from corpus.programbench.batch001_unblock_priority_record import verify_priority_record
from corpus.programbench.operator_ready_platform import DOXYGEN_INSTANCE


def _record() -> dict:
    return ProgramBenchBatch001UnblockPriority(PriorityConfig(write_records=False)).build()


def test_batch001_priority_record_is_signed_and_non_executing() -> None:
    record = _record()

    assert record["status"] == "BATCH001_UNBLOCK_PRIORITY_WRITTEN"
    assert verify_priority_record(record)
    assert record["safety_closure"]["execution_performed"] is False
    assert record["safety_closure"]["docker_run_performed"] is False
    assert record["safety_closure"]["docker_pull_performed"] is False
    assert record["safety_closure"]["programbench_rerun_performed"] is False
    assert record["safety_closure"]["training_rows_written"] is False
    assert record["authorization"]["programbench_rerun_authorized"] is False


def test_priority_ranks_metadata_targets_before_doxygen() -> None:
    record = _record()
    ranked = record["ranked_unblock_list"]

    assert ranked[0]["estimated_difficulty"] == "EASY_METADATA_ONLY"
    assert ranked[0]["exact_operator_packet_needed"] == "image_metadata_submission"
    assert DOXYGEN_INSTANCE not in [
        row["instance_id"] for row in record["top_3_safest_next_targets"]
    ]
    doxygen = next(row for row in ranked if row["instance_id"] == DOXYGEN_INSTANCE)
    assert doxygen["estimated_difficulty"] == "HARD_POLICY_ADMISSION_REQUIRED"
    assert doxygen["exact_operator_packet_needed"] == "security_policy_admission"
    assert doxygen["policy_admission_requirement"] == "REQUIRED_BEFORE_EXECUTION"


def test_priority_preserves_doxygen_blocked_state_and_training_false() -> None:
    doxygen = next(
        row for row in _record()["ranked_unblock_list"] if row["instance_id"] == DOXYGEN_INSTANCE
    )

    assert doxygen["artifact_authority_status"] == "ARTIFACT_AUTHORITY_PRESENT"
    assert doxygen["scan_status"] == "CLEANROOM_IMAGE_SCAN_FAILED"
    assert doxygen["bounded_rerun_readiness"] == "BOUNDED_RERUN_BLOCKED_SECURITY_PREFLIGHT"
    assert doxygen["training_eligibility"] == "TRAINING_ELIGIBLE_FALSE"
    assert doxygen["execution_authorized"] is False


def test_priority_identifies_targets_that_can_progress_without_policy_admission_only_for_metadata() -> (
    None
):
    record = _record()

    assert record["summary"]["any_target_can_proceed_without_security_policy_admission"] is True
    assert record["summary"]["any_target_has_lower_scan_security_burden_than_doxygen"] is True
    assert (
        record["summary"]["doxygen_recommendation"]
        == "PAUSE_UNTIL_OPERATOR_SECURITY_POLICY_ADMISSION"
    )
    metadata_rows = [
        row
        for row in record["ranked_unblock_list"]
        if row["can_proceed_without_security_policy_admission_for_next_step"]
    ]
    assert metadata_rows
    assert all(row["scan_status"] == "SCAN_NOT_EVALUATED" for row in metadata_rows)
    assert all(row["training_eligibility"] == "TRAINING_ELIGIBLE_FALSE" for row in metadata_rows)
