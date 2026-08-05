from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "scripts"))

from agents.base_agent import CorpusType  # noqa: E402
from corpus.corpus_manager import CorpusManager  # noqa: E402
from corpus.training_corpus_dashboard import generate_dashboard  # noqa: E402


def _write_row(root: Path, payload: dict) -> None:
    cm = CorpusManager(root=root)
    record = cm._normalize_record(
        corpus_type=CorpusType.CODE_VERDICT,
        task_id=payload["task_id"],
        input_hash=f"in-{payload['task_id']}",
        output_hash=f"out-{payload['task_id']}",
        source_benchmark=payload.get("source_benchmark", "testbench"),
        payload=payload,
    )
    out = root / "code_verdict" / "rows.jsonl"
    cm._atomic_append(out, record)


def _eligible(task_id: str, language: str, failure_class: str = "none") -> dict:
    return {
        "task_id": task_id,
        "record_status": "active_training_eligible",
        "training_eligible": True,
        "language": language,
        "source_kind": "benchmark_attempt",
        "source_benchmark": "Aider Polyglot",
        "license_provenance": "MIT",
        "verifier_command": "pytest -q",
        "verifier_result": "pass",
        "failure_class": failure_class,
        "failure_type": failure_class,
        "repair_outcome": "pass",
        "trace_hash_schema_version": "canonical-v2",
        "trace_hash": task_id,
    }


def test_training_dashboard_counts_only_training_eligible_rows(tmp_path):
    root = tmp_path / "corpus"
    _write_row(root, _eligible("py-1", "python"))
    _write_row(
        root,
        {
            "task_id": "eval-1",
            "record_status": "active_eval_evidence",
            "training_eligible": False,
            "language": "rust",
            "failure_type": "programbench_failure",
        },
    )

    report = generate_dashboard([root])

    assert report.total_rows == 2
    assert report.active_training_eligible == 1
    assert report.active_eval_evidence == 1
    assert report.by_language["python"] == 1
    assert "rust" not in report.by_language


def test_training_dashboard_reports_target_progress(tmp_path):
    root = tmp_path / "corpus"
    _write_row(root, _eligible("go-1", "go", "nil_pointer"))

    report = generate_dashboard([root], targets={"go": 2, "python": 1})

    assert report.target_progress["go"]["count"] == 1
    assert report.target_progress["go"]["remaining"] == 1
    assert report.target_progress["go"]["met"] is False
    assert report.target_progress["python"]["remaining"] == 1


def test_training_dashboard_flags_bad_training_rows(tmp_path):
    root = tmp_path / "corpus"
    row = _eligible("bad-1", "python")
    row["verifier_command"] = ""
    _write_row(root, row)

    report = generate_dashboard([root])

    assert report.verifier_missing_training_rows == 1
    assert "verifier_missing_training_rows:1" in report.maturity_failures


def test_training_dashboard_json_serializable(tmp_path):
    root = tmp_path / "corpus"
    _write_row(root, _eligible("ts-1", "typescript", "react_prop_mismatch"))

    report = generate_dashboard([root])

    encoded = json.dumps(report.to_dict(), sort_keys=True)
    assert "typescript" in encoded
