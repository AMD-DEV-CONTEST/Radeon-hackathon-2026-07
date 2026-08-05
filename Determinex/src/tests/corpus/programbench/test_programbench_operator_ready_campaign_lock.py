from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from corpus.programbench.operator_ready_platform import (
    DOXYGEN_DIGEST,
    DOXYGEN_IMAGE,
    DOXYGEN_INSTANCE,
    PACKET_TYPES,
    OperatorReadyConfig,
    ProgramBenchOperatorReadyPlatform,
    _fill_fixture_packet,
    check_evidence_graph_integrity,
    validate_operator_packet,
)
from corpus.programbench.programbench_platform_record import verify_platform_record


def _platform(
    *, write_records: bool = False, write_outbox: bool = False
) -> ProgramBenchOperatorReadyPlatform:
    return ProgramBenchOperatorReadyPlatform(
        OperatorReadyConfig(write_records=write_records, write_outbox=write_outbox)
    )


def test_operator_packet_templates_are_templates_not_approvals() -> None:
    record = _platform().operator_packet_templates()

    assert record["status"] == "OPERATOR_PACKET_TEMPLATES_WRITTEN"
    assert verify_platform_record(record)
    assert record["all_templates_are_not_approvals"] is True
    security = record["doxygen_security_template"]
    assert security["packet_type"] == "security_policy_admission"
    assert security["image_name"] == DOXYGEN_IMAGE
    assert security["image_digest"] == DOXYGEN_DIGEST
    assert security["template_only"] is True
    assert security["training_eligible"] is False
    assert validate_operator_packet(security)["status"] == "OPERATOR_PACKET_INVALID_SCHEMA"


def test_operator_packet_validator_covers_types_and_blocks_fixture_live() -> None:
    record = _platform().operator_packet_validator()

    assert record["status"] == "OPERATOR_PACKET_VALIDATOR_WRITTEN"
    assert set(record["packet_types"]) == PACKET_TYPES
    assert record["validation_results"]["valid_fixture"]["status"] == "OPERATOR_PACKET_VALID"
    assert (
        record["validation_results"]["fixture_not_live"]["status"]
        == "OPERATOR_PACKET_BLOCKED_FIXTURE_NOT_LIVE"
    )
    assert record["live_approval_created"] is False


def test_validator_rejects_missing_signature_stale_overbroad_and_mismatch() -> None:
    template = _platform().operator_packet_templates()["doxygen_security_template"]
    packet = _fill_fixture_packet(template)

    assert (
        validate_operator_packet({**packet, "operator_signature": ""}, allow_fixture=True)["status"]
        == "OPERATOR_PACKET_BLOCKED_MISSING_SIGNATURE"
    )
    assert (
        validate_operator_packet(
            {**packet, "timestamp": "2020-01-01T00:00:00+00:00"}, allow_fixture=True
        )["status"]
        == "OPERATOR_PACKET_BLOCKED_STALE"
    )
    assert (
        validate_operator_packet({**packet, "training_eligible": True}, allow_fixture=True)[
            "status"
        ]
        == "OPERATOR_PACKET_BLOCKED_OVERBROAD_AUTHORITY"
    )
    assert (
        validate_operator_packet(
            {**packet, "image_digest": "sha256:" + "0" * 64}, allow_fixture=True
        )["status"]
        == "OPERATOR_PACKET_BLOCKED_DIGEST_MISMATCH"
    )


def test_metadata_recovery_queue_classifies_doxygen_and_missing_images() -> None:
    record = _platform().metadata_recovery_queue()
    by_id = {item["instance_id"]: item for item in record["items"]}

    assert record["status"] == "BATCH001_METADATA_RECOVERY_QUEUE_WRITTEN"
    assert by_id[DOXYGEN_INSTANCE]["required_action"] == "RECOVER_SECURITY_POLICY_ADMISSION"
    assert by_id[DOXYGEN_INSTANCE]["training_eligible"] is False
    assert record["summary"]["RECOVER_TASK_IMAGE_METADATA"] == 10
    assert all(item["training_eligible"] is False for item in record["items"])


def test_exact_provider_probe_plan_is_non_executing_and_conservative() -> None:
    record = _platform().exact_provider_probe_plan()

    assert record["status"] == "EXACT_PROVIDER_PROBE_PLAN_WRITTEN"
    assert record["network_operations_executed"] is False
    assert record["pull_or_run_executed"] is False
    missing = [p for p in record["plans"] if p["instance_id"] != DOXYGEN_INSTANCE]
    assert len(missing) == 10
    assert all(p["status"] == "EXACT_PROVIDER_PROBE_BLOCKED_NAME_INFERENCE_UNSAFE" for p in missing)
    assert any(p["candidate_image_name"] == DOXYGEN_IMAGE for p in record["plans"])


def test_batch001_operator_packet_bundle_contains_doxygen_and_missing_metadata_packets() -> None:
    record = _platform().operator_packet_bundle()

    assert record["status"] == "BATCH001_OPERATOR_PACKET_BUNDLE_WRITTEN"
    assert record["all_packets_template_only"] is True
    assert record["summary"]["security_policy_admission"] == 1
    assert record["summary"]["image_metadata_submission"] == 10
    assert all(
        packet["approval_status"] == "TEMPLATE_NOT_APPROVAL"
        for packet in record["packet_templates"]
    )


def test_operator_inbox_scanner_empty_and_fixture_validation(tmp_path: Path) -> None:
    empty = _platform().operator_inbox_scanner(tmp_path / "missing")
    assert empty["status"] == "OPERATOR_INBOX_EMPTY"

    inbox = tmp_path / "inbox"
    inbox.mkdir()
    packet = _fill_fixture_packet(
        _platform().operator_packet_templates()["doxygen_security_template"]
    )
    (inbox / "packet.json").write_text(json.dumps(packet), encoding="utf-8")
    scanned = _platform().operator_inbox_scanner(inbox, allow_fixture=True)
    assert scanned["status"] == "OPERATOR_INBOX_PACKETS_VALIDATED"
    assert scanned["packets"][0]["status"] == "OPERATOR_PACKET_VALID"


def test_operator_packet_router_routes_only_valid_packets(tmp_path: Path) -> None:
    packet = _fill_fixture_packet(
        _platform().operator_packet_templates()["doxygen_security_template"]
    )
    inbox_scan = {
        "status": "OPERATOR_INBOX_PACKETS_VALIDATED",
        "packets": [
            {
                "path": "fixture.json",
                "packet_type": packet["packet_type"],
                **validate_operator_packet(packet, allow_fixture=True),
            }
        ],
    }

    blocked = _platform().packet_admission_router(inbox_scan)
    routed = _platform().packet_admission_router(inbox_scan, allow_fixture_routes=True)
    assert blocked["status"] == "OPERATOR_PACKET_ROUTE_BLOCKED_FIXTURE_NOT_LIVE"
    assert routed["status"] == "OPERATOR_PACKET_ROUTE_WRITTEN"
    assert routed["routes"][0]["target_gate"] == "generic_operator_policy_admission"
    assert routed["routes"][0]["executes"] is False


def test_unblock_simulation_never_executes_or_trains() -> None:
    record = _platform().unblock_simulation()

    assert record["status"] == "UNBLOCK_SIMULATION_WRITTEN"
    assert record["execution_performed"] is False
    assert record["training_rows_written"] is False
    doxygen = next(
        s
        for s in record["scenarios"]
        if s["scenario"] == "doxygen_security_policy_admission_supplied"
    )
    assert doxygen["execution_preflight_would_be_ready"] is True
    assert doxygen["requires_explicit_bounded_authorization"] is True


def test_evidence_graph_integrity_guard_passes_live_and_fails_bad_fixture() -> None:
    record = _platform().evidence_graph_integrity_guard()
    assert record["status"] == "EVIDENCE_GRAPH_INTEGRITY_PASSED"
    assert all(record["checks"].values())

    bad_graph = {
        "nodes": [{"training_eligible": True, "model_failure": True}],
        "template_authorizes_execution": True,
    }
    checks = check_evidence_graph_integrity(bad_graph)
    assert checks["no_training_true_from_blocked"] is False
    assert checks["no_model_failure_for_security_skip"] is False
    assert checks["no_template_authorizes_run"] is False


def test_operator_cli_evidence_and_read_only_commands() -> None:
    record = _platform().operator_cli_evidence()
    assert record["status"] == "OPERATOR_CLI_WRITTEN"
    assert "status" in record["commands"]
    assert record["authorization"]["programbench_rerun_authorized"] is False


def test_operator_outbox_writes_templates_with_placeholder_signatures(tmp_path: Path) -> None:
    outbox = tmp_path / "outbox"
    record = ProgramBenchOperatorReadyPlatform(
        OperatorReadyConfig(write_records=False, write_outbox=True)
    ).operator_outbox(outbox)

    assert record["status"] == "OPERATOR_OUTBOX_WRITTEN"
    assert record["templates_are_not_approvals"] is True
    templates = list(outbox.glob("*.template.json"))
    assert templates
    raw = "\n".join(path.read_text(encoding="utf-8") for path in templates)
    assert "<operator_signature>" in raw
    assert "APPROVED" not in raw


def test_completion_scorecard_does_not_score_blocked_dimensions_as_complete() -> None:
    record = _platform().completion_scorecard()

    assert record["status"] == "PLATFORM_COMPLETION_SCORECARD_WRITTEN"
    assert record["no_inflated_blocked_scores"] is True
    assert record["doxygen_score"] < 100
    assert record["batch001_score"] < 100


def test_final_state_is_operator_ready_but_non_executing() -> None:
    record = _platform().final_state()

    assert record["status"] == "CODEX_OPERATOR_READY_FINAL_STATE_WRITTEN"
    assert record["operator_packet_templates"] == "PRESENT"
    assert record["operator_outbox"] == "PRESENT"
    assert record["execution_performed"] is False
    assert record["training_rows_written"] is False
    assert record["next_unblockers_actionable"] is True


def test_run_all_writes_expected_operator_ready_records() -> None:
    platform = ProgramBenchOperatorReadyPlatform(
        OperatorReadyConfig(write_records=True, write_outbox=True)
    )
    records = platform.run_all()

    assert set(records) == {
        "templates",
        "validator",
        "queue",
        "probes",
        "bundle",
        "inbox",
        "router",
        "simulation",
        "integrity",
        "cli",
        "outbox",
        "scorecard",
        "final",
    }
    assert all(verify_platform_record(record) for record in records.values())


def test_operator_cli_smoke_status_actions_packets_simulation_graph(tmp_path: Path) -> None:
    commands = [
        ["status", "--json"],
        ["actions", "--json"],
        ["packets", "--out", str(tmp_path / "cli-outbox")],
        ["inbox-scan", "--json"],
        ["simulate-unblock", "--json"],
        ["evidence-graph", "--json"],
    ]
    for command in commands:
        result = subprocess.run(
            [sys.executable, "scripts/corpus/programbench/programbench_operator_cli.py", *command],
            check=True,
            capture_output=True,
            text=True,
        )
        assert json.loads(result.stdout)
