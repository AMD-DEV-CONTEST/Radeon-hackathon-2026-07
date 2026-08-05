from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "scripts"))

from corpus.corpus_coverage_report import generate_report  # noqa: E402
from corpus.corpus_manager import resign_record, verify_signature  # noqa: E402
from corpus.corpus_schema_maturity import (  # noqa: E402
    backfill_file,
    classify_record,
    generate_maturity_report,
    mature_record,
    missing_required_fields,
)


def _legacy_programbench_row() -> dict:
    return resign_record(
        {
            "schema_version": "determinex-agent-trace-v1",
            "corpus_type": "code_verdict",
            "task_id": "pb_richgo_001",
            "lang": "go",
            "source_benchmark": "programbench",
            "input_hash": "input-001",
            "output_hash": "output-001",
            "test_result": "pass",
            "compile_result": "pass",
        }
    )


def test_mature_record_backfills_legacy_programbench_verdict():
    row = _legacy_programbench_row()

    matured = mature_record(row, migrated_at="2026-05-27T00:00:00+00:00")

    assert matured["record_status"] == "active_eval_evidence"
    assert matured["training_eligible"] is False
    assert matured["training_exclusion_reason"] == "active_eval_evidence"
    assert matured["language"] == "go"
    assert matured["source_kind"] == "programbench_legacy_verdict"
    assert matured["verifier_command"] == "programbench eval"
    assert matured["verifier_result"] == "pass"
    assert matured["validator"] == "programbench eval"
    assert matured["failure_type"] == "none"
    assert matured["trace_hash"]
    assert matured["trace_hash_schema_version"] == "canonical-v2"
    assert matured["signature_key_scope"] in {"durable", "ephemeral"}
    assert missing_required_fields(matured) == []
    assert verify_signature(matured) is True


def test_trace_hash_uses_canonical_content_not_only_task_tuple():
    row_a = _legacy_programbench_row()
    row_b = dict(row_a)
    row_b["stderr_tail"] = "unique failure tail"
    row_b = resign_record(row_b)

    mature_a = mature_record(row_a, migrated_at="2026-05-27T00:00:00+00:00")
    mature_b = mature_record(row_b, migrated_at="2026-05-27T00:00:00+00:00")

    assert mature_a["task_id"] == mature_b["task_id"]
    assert mature_a["trace_hash"] != mature_b["trace_hash"]


def test_unsigned_record_is_quarantined():
    status, reasons = classify_record(
        {
            "schema_version": "determinex-agent-trace-v1",
            "corpus_type": "code_verdict",
            "task_id": "raw",
            "language": "python",
        }
    )

    assert status == "quarantined"
    assert "unsigned" in reasons


def test_incomplete_signed_row_requires_backfill():
    row = resign_record(
        {
            "schema_version": "determinex-agent-trace-v1",
            "corpus_type": "code_verdict",
            "task_id": "legacy",
        }
    )

    status, reasons = classify_record(row)

    assert status == "legacy_backfill_needed"
    assert "missing_language" in reasons
    assert "missing_verifier_command" in reasons


def test_generate_maturity_report_counts_statuses(tmp_path):
    corpus = tmp_path / "corpus" / "code_verdict"
    corpus.mkdir(parents=True)
    rows = [
        mature_record(_legacy_programbench_row(), migrated_at="2026-05-27T00:00:00+00:00"),
        {"task_id": "unsigned"},
    ]
    (corpus / "rows.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )

    report = generate_maturity_report([tmp_path / "corpus"], verify_signatures=True)

    assert report.total_rows == 2
    assert report.active_eval_evidence == 1
    assert report.quarantined == 1
    assert report.unsigned_count == 1
    assert report.invalid_signature_count == 0


def test_backfill_file_writes_backup_and_schema_complete_rows(tmp_path):
    path = tmp_path / "rows.jsonl"
    path.write_text(json.dumps(_legacy_programbench_row()) + "\n", encoding="utf-8")

    result = backfill_file(path, dry_run=False)
    row = json.loads(path.read_text(encoding="utf-8").splitlines()[0])

    assert result["changed"] == 1
    assert Path(result["backup"]).exists()
    assert row["record_status"] == "active_eval_evidence"
    assert row["training_eligible"] is False
    assert missing_required_fields(row) == []
    assert verify_signature(row) is True


def test_coverage_report_accepts_verifier_command(tmp_path):
    root = tmp_path / "corpus"
    out = root / "code_verdict" / "rows.jsonl"
    out.parent.mkdir(parents=True)
    row = mature_record(_legacy_programbench_row(), migrated_at="2026-05-27T00:00:00+00:00")
    out.write_text(json.dumps(row) + "\n", encoding="utf-8")

    report = generate_report([root], verify_signatures=True)

    assert report.total_rows == 1
    assert report.missing_verifier_count == 0
    assert report.invalid_signature_count == 0


def test_local_legacy_programbench_training_corpus_is_excluded():
    manifest = _ROOT / "corpus" / "programbench" / "training_corpus" / "TRAINING_EXCLUSION.json"
    payload = json.loads(manifest.read_text(encoding="utf-8"))

    assert payload["record_status"] == "excluded_from_training_by_default"
    assert payload["training_eligible"] is False
    assert payload["required_unlock_lock"] == "CORPUS_SCHEMA_MATURITY_LOCK_001"
