from __future__ import annotations

from corpus.programbench.commit_provenance_repair_audit import (
    CommitProvenanceAuditConfig,
    ProgramBenchCommitProvenanceRepairAudit,
    classify_commit_path,
    classify_paths,
)
from corpus.programbench.commit_provenance_repair_audit_record import (
    verify_commit_provenance_audit_record,
)


def test_commit_path_classifier_separates_lanes() -> None:
    assert (
        classify_commit_path("scripts/corpus/programbench/batch001_import_scan_pipeline.py")
        == "CODEX_PROGRAMBENCH"
    )
    assert (
        classify_commit_path("locks/sentinel/PROGRAMBENCH_BATCH001_SCAN_QUEUE_LOCK_001.json")
        == "CODEX_PROGRAMBENCH"
    )
    assert (
        classify_commit_path("frontend/src/components/ide-repair/RepairPanelShell.tsx")
        == "CLAUDE_FRONTEND"
    )
    assert classify_commit_path("assurance/evidence/evidence_index.json") == "SHARED_EVIDENCE_INDEX"
    assert classify_commit_path("some/unknown/path.txt") == "NEEDS_REVIEW"


def test_classify_paths_keeps_all_required_buckets() -> None:
    classified = classify_paths(
        [
            "assurance/evidence/evidence_index.json",
            "docs/PROGRAMBENCH_BATCH001_IMPORT_SCAN_PIPELINE.md",
            "docs/FRONTEND_REPAIR_PANEL_SHELL.md",
        ]
    )

    assert classified["CODEX_PROGRAMBENCH"] == [
        "docs/PROGRAMBENCH_BATCH001_IMPORT_SCAN_PIPELINE.md"
    ]
    assert classified["CLAUDE_FRONTEND"] == ["docs/FRONTEND_REPAIR_PANEL_SHELL.md"]
    assert classified["SHARED_EVIDENCE_INDEX"] == ["assurance/evidence/evidence_index.json"]
    assert classified["NEEDS_REVIEW"] == []


def test_live_mixed_commit_audit_passes_with_label_warning() -> None:
    record = ProgramBenchCommitProvenanceRepairAudit(
        CommitProvenanceAuditConfig(write_record=False)
    ).run()

    assert record["status"] == "PROGRAMBENCH_COMMIT_PROVENANCE_AUDIT_PASSED_WITH_LABEL_WARNING"
    assert verify_commit_provenance_audit_record(record)
    assert record["label_warning"] is True
    assert record["repair_required"] is False
    assert record["programbench_evidence"]["valid"] is True
    assert record["programbench_locks"]["valid"] is True
    assert record["evidence_index"]["valid"] is True
    assert record["cross_lane_imports"]["found"] is False
    assert record["cross_lane_mutations_found"] is False
    assert record["operation_check"]["valid"] is True
    assert record["execution_performed"] is False
    assert record["training_rows_written"] is False


def test_audit_finds_unknown_commit_file() -> None:
    record = ProgramBenchCommitProvenanceRepairAudit(
        CommitProvenanceAuditConfig(write_record=False)
    ).run(
        commit_files=[
            "scripts/corpus/programbench/batch001_import_scan_pipeline.py",
            "mystery/file.txt",
        ],
        commit_subject="FRONTEND_REPAIR_PANEL_SHELL_LOCK_001: 9-section shell",
    )

    assert record["status"] == "PROGRAMBENCH_COMMIT_PROVENANCE_AUDIT_FINDINGS_WRITTEN"
    assert record["classification"]["NEEDS_REVIEW"] == ["mystery/file.txt"]


def test_audit_label_warning_does_not_create_execution_authority() -> None:
    record = ProgramBenchCommitProvenanceRepairAudit(
        CommitProvenanceAuditConfig(write_record=False)
    ).run()
    flags = record["operation_check"]["authorization_flags"]

    assert flags["docker_execution_authorized"] is False
    assert flags["programbench_rerun_authorized"] is False
    assert flags["source_rebuild_authorized"] is False
    assert flags["remediation_authorized"] is False
    assert flags["policy_exception_granted"] is False
    assert flags["training_eligible"] is False
