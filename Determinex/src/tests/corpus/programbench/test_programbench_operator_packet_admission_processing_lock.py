from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from corpus.programbench.operator_ready_platform import (
    OperatorReadyConfig,
    ProgramBenchOperatorReadyPlatform,
    _fill_fixture_packet,
)
from corpus.programbench.programbench_platform_record import verify_platform_record


def _platform(*, write_records: bool = False) -> ProgramBenchOperatorReadyPlatform:
    return ProgramBenchOperatorReadyPlatform(
        OperatorReadyConfig(write_records=write_records, write_outbox=False)
    )


def test_live_empty_inbox_processes_no_packets(tmp_path: Path) -> None:
    record = _platform().packet_admission_processing(tmp_path / "missing")

    assert record["status"] == "OPERATOR_PACKET_ADMISSION_PROCESSING_NO_LIVE_PACKETS"
    assert record["gate_review_required"] is False
    assert record["execution_performed"] is False
    assert record["approval_granted"] is False
    assert record["training_eligible"] is False
    assert record["authorization"]["programbench_rerun_authorized"] is False
    assert verify_platform_record(record)


def test_fixture_packet_is_not_processed_as_live(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    template = _platform().operator_packet_templates()["doxygen_security_template"]
    packet = _fill_fixture_packet(template)
    (inbox / "fixture.json").write_text(json.dumps(packet), encoding="utf-8")

    record = _platform().packet_admission_processing(inbox)

    assert record["status"] == "OPERATOR_PACKET_ADMISSION_PROCESSING_BLOCKED_INVALID_PACKET"
    assert record["accepted_routes"] == []
    assert record["approval_granted"] is False
    assert record["execution_performed"] is False


def test_valid_live_packet_routes_to_gate_review_only(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    template = _platform().operator_packet_templates()["doxygen_security_template"]
    packet = _fill_fixture_packet(template)
    packet["fixture_packet"] = False
    packet["operator_identity"] = "operator@example.test"
    packet["operator_signature"] = "local-signature-placeholder"
    (inbox / "live.json").write_text(json.dumps(packet), encoding="utf-8")

    record = _platform().packet_admission_processing(inbox)

    assert record["status"] == "OPERATOR_PACKET_ADMISSION_PROCESSING_READY_FOR_GATE_REVIEW"
    assert record["gate_review_required"] is True
    assert record["accepted_routes"][0]["target_gate"] == "generic_operator_policy_admission"
    assert record["approval_granted"] is False
    assert record["authorization"]["executable"] is False


def test_processing_cli_smoke() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/corpus/programbench/programbench_operator_cli.py",
            "process-inbox",
            "--json",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    assert payload["status"] == "OPERATOR_PACKET_ADMISSION_PROCESSING_NO_LIVE_PACKETS"
    assert payload["execution_performed"] is False
