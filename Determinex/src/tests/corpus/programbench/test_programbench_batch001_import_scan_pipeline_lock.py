from __future__ import annotations

from corpus.programbench.batch001_import_scan_pipeline import (
    Batch001ImportScanConfig,
    ProgramBenchBatch001ImportScanPipeline,
    evaluate_import_packet,
    fixture_import_packet,
    hash_packet,
)
from corpus.programbench.batch001_import_scan_pipeline_record import (
    verify_import_scan_pipeline_record,
)


def _campaign(**kwargs: object) -> ProgramBenchBatch001ImportScanPipeline:
    return ProgramBenchBatch001ImportScanPipeline(
        Batch001ImportScanConfig(write_records=False, write_outbox=False, **kwargs)
    )


def test_artifact_import_request_packets_bind_exact_digests_without_authority() -> None:
    record = _campaign().artifact_import_request_packet()

    assert record["status"] == "ARTIFACT_IMPORT_REQUEST_PACKET_WRITTEN"
    assert record["summary"]["import_requests_written"] == 10
    assert verify_import_scan_pipeline_record(record)
    assert all(packet["exact_digest"].startswith("sha256:") for packet in record["packets"])
    assert all(packet["requested_import_mode"]["no_run"] is True for packet in record["packets"])
    assert all(
        packet["requested_import_mode"]["no_pull_by_tag"] is True for packet in record["packets"]
    )
    assert all(packet["authorizes_execution"] is False for packet in record["packets"])
    assert record["authorization"]["executable"] is False


def test_artifact_import_preflight_blocks_without_safe_import_method() -> None:
    record = _campaign().artifact_import_preflight()

    assert record["status"] == "ARTIFACT_IMPORT_PREFLIGHT_BLOCKED_NO_SAFE_IMPORT_METHOD"
    assert record["summary"]["blocked"] == 10
    assert all(
        row["status"] == "ARTIFACT_IMPORT_PREFLIGHT_BLOCKED_NO_SAFE_IMPORT_METHOD"
        for row in record["rows"]
    )
    assert all(row["execution_performed"] is False for row in record["rows"])


def test_artifact_import_preflight_ready_fixture_when_safe_method_available() -> None:
    record = _campaign(local_safe_import_method="operator_supplied_tar").artifact_import_preflight()

    assert record["status"] == "ARTIFACT_IMPORT_PREFLIGHT_READY"
    assert record["summary"]["ready"] == 10
    assert all(row["method_does_not_run_containers"] is True for row in record["rows"])
    assert all(row["observed_digest_verifiable"] is True for row in record["rows"])


def test_operator_artifact_import_packet_bundle_written_when_preflight_blocked() -> None:
    preflight = _campaign().artifact_import_preflight()
    record = _campaign().operator_artifact_import_packet_bundle(preflight)

    assert record["status"] == "OPERATOR_ARTIFACT_IMPORT_PACKET_BUNDLE_WRITTEN"
    assert record["summary"]["operator_import_packets_written"] == 10
    assert record["outbox_manifest"] == {}
    assert all(
        template["approval_status"] == "TEMPLATE_NOT_APPROVAL" for template in record["templates"]
    )
    assert all(template["authorizes_execution"] is False for template in record["templates"])
    assert all(
        template["scan_required_after_admission"] is True for template in record["templates"]
    )


def test_exact_artifact_import_gate_requires_live_import_by_default() -> None:
    record = _campaign().exact_artifact_import_gate()

    assert record["status"] == "EXACT_ARTIFACT_IMPORT_REQUIRED"
    assert record["live_packets_processed"] == 0
    assert record["executable"] is False
    assert record["training_eligible"] is False
    assert record["scan_required"] is True


def test_exact_artifact_import_gate_fixture_accept_and_reject_paths() -> None:
    expected = _campaign()._admitted_rows()[0]
    valid = fixture_import_packet(expected)
    bad_digest = fixture_import_packet(expected, digest="sha256:" + "0" * 64)
    missing_hash = fixture_import_packet(expected, include_hash=False)

    assert (
        evaluate_import_packet(valid, expected, allow_fixture=True)["status"]
        == "EXACT_ARTIFACT_IMPORT_ACCEPTED"
    )
    assert (
        evaluate_import_packet(valid, expected, allow_fixture=False)["status"]
        == "EXACT_ARTIFACT_IMPORT_BLOCKED_FIXTURE_NOT_LIVE"
    )
    assert (
        evaluate_import_packet(bad_digest, expected, allow_fixture=True)["status"]
        == "EXACT_ARTIFACT_IMPORT_BLOCKED_DIGEST_MISMATCH"
    )
    assert (
        evaluate_import_packet(missing_hash, expected, allow_fixture=True)["status"]
        == "EXACT_ARTIFACT_IMPORT_BLOCKED_FILE_HASH_MISSING"
    )
    assert hash_packet(valid).startswith("sha256:")


def test_scan_queue_represents_all_targets_pending_import() -> None:
    record = _campaign().scan_queue()

    assert record["status"] == "BATCH001_SCAN_QUEUE_WRITTEN"
    assert len(record["items"]) == 10
    assert record["summary"]["SCAN_PENDING_ARTIFACT_IMPORT"] == 10
    assert all(item["scan_performed"] is False for item in record["items"])
    assert all(item["execution_performed"] is False for item in record["items"])


def test_scan_queue_ready_fixture_after_accepted_import_packet() -> None:
    expected = _campaign()._admitted_rows()[0]
    gate = _campaign().exact_artifact_import_gate(
        [fixture_import_packet(expected)], allow_fixture=True
    )
    record = _campaign().scan_queue(gate)

    first = next(item for item in record["items"] if item["instance_id"] == expected["instance_id"])
    assert first["status"] == "SCAN_READY_FOR_IMPORTED_ARTIFACT"
    assert first["artifact_import_status"] == "ACCEPTED"
    assert first["scan_performed"] is False


def test_scan_policy_precheck_never_implies_execution_or_training() -> None:
    record = _campaign().scan_policy_precheck()

    assert record["status"] == "SCAN_POLICY_PRECHECK_WRITTEN"
    assert record["critical_threshold"] == 0
    assert record["high_threshold"] == 0
    assert record["scan_pass_implies_execution"] is False
    assert record["scan_fail_routes_to_security_decision"] is True
    assert record["authorization"]["executable"] is False
    assert record["authorization"]["training_eligible"] is False


def test_import_scan_campaign_final_state_is_non_executing() -> None:
    records = _campaign().run_all()
    final = records["final"]

    assert final["status"] == "BATCH001_IMPORT_SCAN_CAMPAIGN_FINAL_STATE_WRITTEN"
    assert final["summary"]["metadata_admitted_targets"] == 10
    assert final["summary"]["import_requests_written"] == 10
    assert final["summary"]["import_preflight_ready"] == 0
    assert final["summary"]["import_preflight_blocked"] == 10
    assert final["summary"]["operator_import_packets_written"] == 10
    assert final["summary"]["artifact_import_gate_ready"] is True
    assert final["summary"]["scan_queue_entries"] == 10
    assert final["summary"]["scans_performed"] == 0
    assert final["summary"]["execution_performed"] is False
    assert final["summary"]["training_rows_written"] is False
    assert verify_import_scan_pipeline_record(final)
