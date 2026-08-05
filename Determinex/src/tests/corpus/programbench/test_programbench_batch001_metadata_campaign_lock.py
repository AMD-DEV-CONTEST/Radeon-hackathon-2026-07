from __future__ import annotations

from corpus.programbench.batch001_metadata_campaign import (
    Batch001MetadataCampaignConfig,
    ProgramBenchBatch001MetadataCampaign,
    classify_safe_manifest_lookup,
    derive_image_name,
)
from corpus.programbench.batch001_metadata_campaign_record import verify_metadata_campaign_record
from corpus.programbench.operator_ready_platform import DOXYGEN_INSTANCE


def _campaign() -> ProgramBenchBatch001MetadataCampaign:
    return ProgramBenchBatch001MetadataCampaign(Batch001MetadataCampaignConfig(write_records=False))


def test_image_name_derivation_covers_top_metadata_targets_without_digest_or_authority() -> None:
    record = _campaign().image_name_derivation()

    assert record["status"] == "IMAGE_NAME_DERIVATION_WRITTEN"
    assert verify_metadata_campaign_record(record)
    assert record["summary"]["targets_considered"] == 10
    assert record["summary"]["image_names_derived"] == 10
    first = record["targets"][0]
    assert first["instance_id"] == "ammarabouzor__tui-journal.2b4540d"
    assert (
        first["derived_image_name"]
        == "programbench/ammarabouzor_1776_tui-journal.2b4540d:task_cleanroom"
    )
    assert first["image_digest"] == ""
    assert first["artifact_authority_status"] == "ARTIFACT_AUTHORITY_INCONCLUSIVE"
    assert record["authorization"]["docker_pull_authorized"] is False


def test_derivation_blocks_bad_instance_patterns() -> None:
    bad = derive_image_name({"instance_id": "not-a-programbench-id"})

    assert bad["status"] == "IMAGE_NAME_DERIVATION_BLOCKED_UNSUPPORTED_PATTERN"
    assert bad["derived_exact"] is False
    assert bad["derived_image_name"] == ""


def test_exact_manifest_metadata_plan_fabricates_no_digests() -> None:
    record = _campaign().exact_manifest_metadata_plan()

    assert record["status"] == "EXACT_MANIFEST_METADATA_PLAN_WRITTEN"
    assert len(record["plans"]) == 10
    assert all(plan["provider"] == "docker_hub_official" for plan in record["plans"])
    assert all(plan["digest"] == "" for plan in record["plans"])
    assert record["summary"]["digests_fabricated"] == 0
    assert record["authorization"]["docker_pull_authorized"] is False


def test_safe_manifest_lookup_live_path_is_not_supported_and_fixtures_cover_outcomes() -> None:
    record = _campaign().safe_manifest_lookup()

    assert record["status"] == "SAFE_MANIFEST_LOOKUP_NOT_SUPPORTED"
    assert record["manifest_lookups_attempted"] == 0
    assert record["network_operations_executed"] is False
    assert all(row["status"] == "SAFE_MANIFEST_LOOKUP_NOT_SUPPORTED" for row in record["results"])

    found = classify_safe_manifest_lookup(
        image_name="programbench/example_1776_tool.1234567:task_cleanroom",
        supported=True,
        metadata={"manifest_digest": "sha256:" + "a" * 64},
    )
    missing = classify_safe_manifest_lookup(
        image_name="programbench/missing:task_cleanroom", supported=True
    )
    blocked = classify_safe_manifest_lookup(
        image_name="programbench/blocked:task_cleanroom", blocked_by_policy=True
    )
    assert found["status"] == "SAFE_MANIFEST_LOOKUP_MANIFEST_FOUND"
    assert missing["status"] == "SAFE_MANIFEST_LOOKUP_MANIFEST_NOT_FOUND"
    assert blocked["status"] == "SAFE_MANIFEST_LOOKUP_BLOCKED_BY_POLICY"


def test_manifest_digest_admission_blocks_without_exact_digest() -> None:
    record = _campaign().manifest_digest_admission()

    assert record["status"] == "MANIFEST_DIGEST_ADMISSION_BLOCKED_NO_DIGEST"
    assert record["summary"]["metadata_admitted"] == 0
    assert record["summary"]["blocked_no_digest"] == 10
    assert all(
        row["cache_ready"] is False and row["executable"] is False for row in record["admissions"]
    )


def test_metadata_state_refresh_preserves_doxygen_and_marks_no_change() -> None:
    record = _campaign().metadata_state_refresh()

    assert record["status"] == "BATCH001_METADATA_STATE_NO_CHANGE"
    assert record["doxygen_state_preserved"] is True
    assert record["summary"]["changed"] == 0
    assert all(row["after_state"]["executable"] is False for row in record["rows"])
    assert all(
        row["after_state"]["training_eligible"] == "TRAINING_ELIGIBLE_FALSE"
        for row in record["rows"]
    )


def test_scan_requirements_queue_blocks_without_digest() -> None:
    record = _campaign().scan_requirements_queue()

    assert record["status"] == "SCAN_REQUIREMENTS_BLOCKED_NO_DIGEST"
    assert record["summary"]["metadata_admitted"] == 0
    assert record["summary"]["blocked_no_digest"] == 10
    assert all(
        item["import_authorized"] is False and item["scan_executed"] is False
        for item in record["items"]
    )


def test_operator_action_refresh_keeps_doxygen_security_and_metadata_targets_metadata() -> None:
    record = _campaign().operator_action_refresh()
    by_id = {row["instance_id"]: row for row in record["actions"]}

    assert record["status"] == "BATCH001_OPERATOR_ACTION_REFRESH_WRITTEN"
    assert by_id[DOXYGEN_INSTANCE]["action_type"] == "SUPPLY_SECURITY_POLICY_ADMISSION"
    metadata_actions = [row for row in record["actions"] if row["instance_id"] != DOXYGEN_INSTANCE]
    assert len(metadata_actions) == 10
    assert all(row["action_type"] == "SUPPLY_IMAGE_METADATA" for row in metadata_actions)
    assert all(row["authorizes_execution"] is False for row in record["actions"])


def test_unblock_priority_refresh_keeps_metadata_targets_ahead_of_doxygen() -> None:
    record = _campaign().unblock_priority_refresh()

    assert record["status"] == "BATCH001_UNBLOCK_PRIORITY_REFRESH_WRITTEN"
    assert (
        record["top_3_next_targets"][0]["exact_operator_packet_needed"]
        == "image_metadata_submission"
    )
    doxygen = next(
        row for row in record["ranked_unblock_list"] if row["instance_id"] == DOXYGEN_INSTANCE
    )
    assert doxygen["estimated_difficulty"] == "HARD_POLICY_ADMISSION_REQUIRED"
    assert doxygen["executable"] is False


def test_metadata_campaign_final_state_is_non_executing_and_honest_about_no_lookup() -> None:
    records = _campaign().run_all()
    final = records["final"]

    assert final["status"] == "BATCH001_METADATA_CAMPAIGN_FINAL_STATE_WRITTEN"
    assert final["summary"]["targets_considered"] == 10
    assert final["summary"]["image_names_derived"] == 10
    assert final["summary"]["manifest_lookups_attempted"] == 0
    assert final["summary"]["manifest_digests_found"] == 0
    assert final["summary"]["metadata_admitted"] == 0
    assert final["summary"]["still_missing_metadata"] == 10
    assert final["summary"]["execution_performed"] is False
    assert final["summary"]["training_rows_written"] is False
    assert verify_metadata_campaign_record(final)
