from __future__ import annotations

from pathlib import Path

from corpus.programbench.operator_ready_platform import (
    OperatorReadyConfig,
    ProgramBenchOperatorReadyPlatform,
    check_evidence_graph_integrity,
)
from corpus.programbench.programbench_platform_record import verify_platform_record


def _platform(
    *, write_records: bool = False, write_outbox: bool = False
) -> ProgramBenchOperatorReadyPlatform:
    return ProgramBenchOperatorReadyPlatform(
        OperatorReadyConfig(write_records=write_records, write_outbox=write_outbox)
    )


def test_operator_ready_audit_passes_with_closed_authority() -> None:
    record = _platform().operator_ready_audit()

    assert record["status"] == "PROGRAMBENCH_OPERATOR_READY_AUDIT_PASSED"
    assert record["findings"] == []
    assert all(record["checks"].values())
    assert record["live_packet_review"] == "NO_LIVE_PACKETS"
    assert record["execution_performed"] is False
    assert record["training_rows_written"] is False
    assert record["authorization"]["programbench_rerun_authorized"] is False
    assert verify_platform_record(record)


def test_audit_regenerates_outbox_readme_with_validation_command(tmp_path: Path) -> None:
    platform = ProgramBenchOperatorReadyPlatform(
        OperatorReadyConfig(write_records=False, write_outbox=True)
    )
    platform.operator_outbox(tmp_path / "outbox")
    readme = (tmp_path / "outbox" / "README.md").read_text(encoding="utf-8")

    assert "templates, not approvals" in readme
    assert "identity/signature" in readme
    assert "assurance/operator_inbox/programbench" in readme
    assert "inbox-scan --json" in readme


def test_evidence_graph_integrity_catches_required_bad_edges() -> None:
    template_exec = check_evidence_graph_integrity(
        {"nodes": [{"template_only": True, "executable": True}]}
    )
    fixture_live = check_evidence_graph_integrity(
        {"nodes": [{"fixture_packet": True, "status": "GENERIC_POLICY_ADMISSION_ACCEPTED"}]}
    )
    metadata_exec = check_evidence_graph_integrity(
        {"nodes": [{"authority": "metadata_only", "executable": True}]}
    )
    blocked_training = check_evidence_graph_integrity(
        {"nodes": [{"status": "SKIPPED_WITH_PROVENANCE_REASON", "training_eligible": True}]}
    )

    assert template_exec["no_template_authorizes_run"] is False
    assert fixture_live["no_policy_admission_from_fixture"] is False
    assert metadata_exec["no_executable_true_from_metadata_only"] is False
    assert blocked_training["no_training_true_from_blocked"] is False


def test_audit_does_not_create_execution_or_training_rows() -> None:
    record = _platform().operator_ready_audit()

    assert record["training_eligible"] is False
    assert record["authorization"]["docker_execution_authorized"] is False
    assert record["authorization"]["policy_exception_granted"] is False
    assert record["authorization"]["training_rows_written"] is False
