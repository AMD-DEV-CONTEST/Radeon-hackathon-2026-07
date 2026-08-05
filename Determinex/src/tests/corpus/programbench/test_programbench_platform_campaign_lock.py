from __future__ import annotations

from pathlib import Path

from corpus.programbench.programbench_campaign_platform import (
    DOXYGEN_DIGEST,
    DOXYGEN_IMAGE,
    DOXYGEN_INSTANCE,
    SKIP_REASONS,
    PlatformConfig,
    ProgramBenchCampaignPlatform,
    _fixture_complete_state,
    _missing_image_state,
)
from corpus.programbench.programbench_platform_record import verify_platform_record


def _platform(*, write_records: bool = False) -> ProgramBenchCampaignPlatform:
    return ProgramBenchCampaignPlatform(PlatformConfig(write_records=write_records))


def test_instance_state_schema_represents_doxygen_final_state() -> None:
    record = _platform().instance_state_schema()

    assert record["status"] == "INSTANCE_STATE_SCHEMA_WRITTEN"
    assert verify_platform_record(record)
    doxygen = record["doxygen_state"]
    assert doxygen["instance_id"] == DOXYGEN_INSTANCE
    assert doxygen["image_name"] == DOXYGEN_IMAGE
    assert doxygen["image_digest"] == DOXYGEN_DIGEST
    assert doxygen["artifact_authority"] == "ARTIFACT_AUTHORITY_PRESENT"
    assert doxygen["security_execution_authority"] == (
        "SECURITY_EXECUTION_AUTHORITY_ABSENT_PENDING_OPERATOR_POLICY_ADMISSION"
    )
    assert doxygen["cache_ready"] is False
    assert doxygen["executable"] is False
    assert doxygen["training_eligible"] == "TRAINING_ELIGIBLE_FALSE"
    assert set(record["fixture_states"]) == {"complete", "partial", "blocked", "skipped", "unknown"}


def test_batch001_state_preserves_doxygen_and_missing_metadata_rows() -> None:
    record = _platform().batch001_state()

    assert record["status"] == "BATCH001_STATE_AGGREGATED"
    assert verify_platform_record(record)
    states = {row["instance_id"]: row for row in record["instances"]}
    assert (
        states[DOXYGEN_INSTANCE]["bounded_rerun_status"]
        == "BOUNDED_RERUN_BLOCKED_SECURITY_PREFLIGHT"
    )
    missing = [row for row in states.values() if not row["image_name"]]
    assert len(missing) == 10
    assert all(row["executable"] is False for row in missing)
    assert all(row["training_eligible"] == "TRAINING_ELIGIBLE_FALSE" for row in missing)


def test_generic_policy_admission_live_requires_operator_approval() -> None:
    record = _platform().generic_policy_admission()

    assert record["status"] == "GENERIC_POLICY_ADMISSION_REQUIRED"
    assert record["live_policy_admission_accepted"] is False
    assert record["authorization"]["programbench_rerun_authorized"] is False
    assert record["training_eligible"] is False


def test_generic_policy_admission_accepts_fixture_but_not_live() -> None:
    state = _platform()._doxygen_state()
    refs = state["evidence_refs"]
    approval = {
        "instance_id": state["instance_id"],
        "image_name": state["image_name"],
        "image_digest": state["image_digest"],
        "scan_evidence_ref": refs["scan"],
        "sandbox_requirements_ref": refs["sandbox_requirements"],
        "policy_exception_request_ref": refs["policy_exception_request"],
        "max_attempts": 1,
        "allowed_scope": state["instance_id"],
        "approval_timestamp": "2026-05-28T00:00:00Z",
        "operator_signature": "fixture-signature",
        "acknowledges_scan_risk": True,
        "permits_only_bounded_official_eval": True,
        "permits_training_eligibility": False,
        "permits_rebuild_remediation": False,
        "permits_broad_docker_use": False,
    }

    record = _platform().generic_policy_admission(approval=approval, fixture=True)

    assert record["status"] == "GENERIC_POLICY_ADMISSION_ACCEPTED_FIXTURE"
    assert record["fixture_only"] is True
    assert record["live_policy_admission_accepted"] is False
    assert record["authorization"]["programbench_rerun_authorized"] is False


def test_generic_policy_admission_rejects_mismatches() -> None:
    state = _platform()._doxygen_state()
    bad_digest = {
        "instance_id": state["instance_id"],
        "image_name": state["image_name"],
        "image_digest": "sha256:" + "0" * 64,
    }
    bad_scope = {
        "instance_id": "other__tool.0000000",
        "image_name": state["image_name"],
        "image_digest": state["image_digest"],
    }

    digest_record = _platform().generic_policy_admission(approval=bad_digest)
    scope_record = _platform().generic_policy_admission(approval=bad_scope)

    assert digest_record["status"] == "GENERIC_POLICY_ADMISSION_BLOCKED_DIGEST_MISMATCH"
    assert scope_record["status"] == "GENERIC_POLICY_ADMISSION_BLOCKED_SCOPE_MISMATCH"


def test_generic_execution_preflight_blocks_doxygen_policy_requirement() -> None:
    admission = _platform().generic_policy_admission()
    record = _platform().generic_execution_preflight(admission=admission)

    assert record["status"] == "GENERIC_EXECUTION_PREFLIGHT_BLOCKED_POLICY_ADMISSION_REQUIRED"
    assert record["checks"]["artifact_authority_present"] is True
    assert record["cache_ready"] is False
    assert record["executable"] is False
    assert record["training_eligible"] is False


def test_generic_execution_preflight_ready_fixture_does_not_execute() -> None:
    fixture_state = _fixture_complete_state()
    admission = {"status": "GENERIC_POLICY_ADMISSION_ACCEPTED"}
    record = _platform().generic_execution_preflight(
        instance_state=fixture_state,
        admission=admission,
        ready_fixture=True,
    )

    assert record["status"] == "GENERIC_EXECUTION_PREFLIGHT_READY"
    assert record["authorization"]["docker_execution_authorized"] is False
    assert record["authorization"]["programbench_rerun_authorized"] is False
    assert record["training_eligible"] is False


def test_generic_execution_preflight_blocks_missing_artifact_authority_and_digest() -> None:
    missing = _missing_image_state("example__missing.0000000")
    missing["artifact_authority"] = "ARTIFACT_AUTHORITY_ABSENT"

    authority_record = _platform().generic_execution_preflight(instance_state=missing)
    missing["artifact_authority"] = "ARTIFACT_AUTHORITY_PRESENT"
    digest_record = _platform().generic_execution_preflight(instance_state=missing)

    assert (
        authority_record["status"]
        == "GENERIC_EXECUTION_PREFLIGHT_BLOCKED_ARTIFACT_AUTHORITY_MISSING"
    )
    assert digest_record["status"] == "GENERIC_EXECUTION_PREFLIGHT_BLOCKED_IMAGE_DIGEST_MISSING"


def test_skip_reason_taxonomy_covers_every_required_reason() -> None:
    record = _platform().skip_reason_taxonomy()

    assert record["status"] == "SKIP_REASON_TAXONOMY_WRITTEN"
    assert set(record["reasons"]) == set(SKIP_REASONS)
    assert all(policy["training_eligible"] is False for policy in record["reasons"].values())
    assert "OPERATOR_POLICY_ADMISSION_REQUIRED" in record["doxygen_mapping"]


def test_batch_skip_decisions_write_non_training_non_model_failure_rows() -> None:
    batch = _platform().batch001_state()
    record = _platform().batch_skip_decisions(batch)

    assert record["status"] == "BATCH_SKIP_DECISIONS_WRITTEN"
    by_id = {row["instance_id"]: row for row in record["decisions"]}
    assert "OPERATOR_POLICY_ADMISSION_REQUIRED" in by_id[DOXYGEN_INSTANCE]["skip_reasons"]
    assert all(row["training_eligible"] is False for row in record["decisions"])
    assert all(row["model_failure"] is False for row in record["decisions"])
    assert any("MISSING_IMAGE_METADATA" in row["skip_reasons"] for row in record["decisions"])


def test_operator_action_queue_maps_doxygen_and_missing_metadata() -> None:
    batch = _platform().batch001_state()
    skips = _platform().batch_skip_decisions(batch)
    record = _platform().operator_action_queue(batch, skips)

    actions = {row["instance_id"]: row for row in record["actions"]}
    assert actions[DOXYGEN_INSTANCE]["action_type"] == "SUPPLY_SECURITY_POLICY_ADMISSION"
    assert any(row["action_type"] == "SUPPLY_IMAGE_METADATA" for row in actions.values())
    assert all(row["authorizes_execution"] is False for row in actions.values())


def test_campaign_reporting_api_is_read_only_and_blocks_ready_claims() -> None:
    batch = _platform().batch001_state()
    skips = _platform().batch_skip_decisions(batch)
    actions = _platform().operator_action_queue(batch, skips)
    record = _platform().campaign_report(batch, skips, actions)

    assert record["status"] == "CAMPAIGN_REPORTING_API_WRITTEN"
    assert record["read_only"] is True
    assert record["report"]["rerun_readiness_summary"]["ready"] == 0
    assert record["report"]["training_eligibility_summary"]["eligible"] == 0
    assert any(
        row["instance_id"] == DOXYGEN_INSTANCE for row in record["report"]["instance_summaries"]
    )


def test_evidence_graph_denies_unauthorized_execution_path() -> None:
    batch = _platform().batch001_state()
    skips = _platform().batch_skip_decisions(batch)
    actions = _platform().operator_action_queue(batch, skips)
    record = _platform().evidence_graph(batch, skips, actions)

    assert record["status"] == "EVIDENCE_GRAPH_WRITTEN"
    assert record["doxygen_execution_path"]["execution"] == "blocked"
    assert record["unauthorized_execution_path_exists"] is False
    assert record["blocked_record_points_to_training_true"] is False
    assert any(edge["reason"] == "blocks" for edge in record["edges"])


def test_codex_lane_final_state_summarizes_reusable_platform() -> None:
    record = _platform().codex_lane_final_state()

    assert record["status"] == "CODEX_LANE_FINAL_STATE_WRITTEN"
    assert record["doxygen_artifact_authority"] == "PRESENT"
    assert record["doxygen_execution_authority"] == "BLOCKED_PENDING_OPERATOR_POLICY_ADMISSION"
    assert record["generic_policy_admission_gate"] == "PRESENT"
    assert record["generic_execution_preflight"] == "PRESENT"
    assert record["official_score_available"] is False
    assert record["execution_performed"] is False
    assert record["authorization"]["training_rows_written"] is False


def test_run_all_writes_expected_evidence_files() -> None:
    records = _platform(write_records=True).run_all()

    assert set(records) == {
        "schema",
        "batch",
        "admission",
        "preflight",
        "taxonomy",
        "skips",
        "actions",
        "report",
        "graph",
        "final",
    }
    expected_paths = [
        "assurance/evidence/programbench_instance_state_schema/programbench_instance_state_schema_run_20260527.INSTANCE_STATE_SCHEMA_WRITTEN.json",
        "assurance/evidence/programbench_batch001_state/programbench_batch001_state_run_20260527.BATCH001_STATE_AGGREGATED.json",
        "assurance/evidence/programbench_generic_operator_policy_admission/programbench_generic_operator_policy_admission_run_20260527.GENERIC_POLICY_ADMISSION_REQUIRED.json",
        "assurance/evidence/programbench_generic_execution_preflight/programbench_generic_execution_preflight_run_20260527.GENERIC_EXECUTION_PREFLIGHT_BLOCKED_POLICY_ADMISSION_REQUIRED.json",
        "assurance/evidence/programbench_skip_reason_taxonomy/programbench_skip_reason_taxonomy_run_20260527.SKIP_REASON_TAXONOMY_WRITTEN.json",
        "assurance/evidence/programbench_batch_skip_decisions/programbench_batch_skip_decisions_run_20260527.BATCH_SKIP_DECISIONS_WRITTEN.json",
        "assurance/evidence/programbench_operator_action_queue/programbench_operator_action_queue_run_20260527.OPERATOR_ACTION_QUEUE_WRITTEN.json",
        "assurance/evidence/programbench_campaign_reporting_api/programbench_campaign_reporting_api_run_20260527.CAMPAIGN_REPORTING_API_WRITTEN.json",
        "assurance/evidence/programbench_evidence_graph/programbench_evidence_graph_run_20260527.EVIDENCE_GRAPH_WRITTEN.json",
        "assurance/evidence/programbench_codex_lane_final_state/programbench_codex_lane_final_state_run_20260527.CODEX_LANE_FINAL_STATE_WRITTEN.json",
    ]
    for record in records.values():
        assert verify_platform_record(record)
    for expected in expected_paths:
        assert Path(expected).exists()
