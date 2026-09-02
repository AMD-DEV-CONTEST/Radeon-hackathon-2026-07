from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "scripts"))

from bench_adapters.aider_polyglot_trace_harness import (  # noqa: E402
    AIDER_BENCHMARK_NAME,
    AiderPolyglotCase,
    load_cases,
    result_to_trace,
    summarize_records,
    write_case_result,
)
from corpus.corpus_manager import verify_signature  # noqa: E402
from verified_task.bench_to_corpus_eligibility import signed_training_eligible  # noqa: E402


def _case(language: str = "python", task_id: str = "aider-py-001") -> AiderPolyglotCase:
    return AiderPolyglotCase(
        task_id=task_id,
        language=language,
        workspace="",
        instruction="repair the exercise until tests pass",
        license_provenance="MIT",
        validation_commands=["python -m pytest"] if language == "python" else [],
    )


def test_case_becomes_task_spec_with_training_gates():
    spec = _case("go", "aider-go-001").to_task_spec()

    assert spec.benchmark == AIDER_BENCHMARK_NAME
    assert spec.language == "go"
    assert spec.validation_commands
    assert spec.metadata["license_gate"] == "pass"
    assert spec.metadata["license_provenance"] == "MIT"
    assert spec.metadata["safety_gate"] == "pass"
    assert spec.metadata["supply_chain_gate"] == "pass"


def test_manifest_loader_accepts_json_and_jsonl(tmp_path):
    json_path = tmp_path / "aider.json"
    json_path.write_text(
        json.dumps({"cases": [case_to_row(_case("rust", "aider-rs-001"))]}), encoding="utf-8"
    )
    jsonl_path = tmp_path / "aider.jsonl"
    jsonl_path.write_text(
        json.dumps(case_to_row(_case("java", "aider-java-001"))) + "\n", encoding="utf-8"
    )

    assert load_cases(json_path)[0].language == "rust"
    assert load_cases(jsonl_path)[0].language == "java"


def test_pass_result_writes_signed_training_eligible_row(tmp_path):
    out = tmp_path / "aider_traces.jsonl"
    record = write_case_result(
        _case("python"), {"outcome": "pass", "passed": True, "failure_class": "none"}, out
    )

    ok, reasons = signed_training_eligible(record)

    assert verify_signature(record) is True
    assert ok, reasons
    assert record["source_benchmark"] == AIDER_BENCHMARK_NAME
    assert record["record_status"] == "active_training_eligible"


def test_fail_result_becomes_repair_task_training_row(tmp_path):
    out = tmp_path / "aider_traces.jsonl"
    record = write_case_result(
        _case("typescript", "aider-ts-001"),
        {"outcome": "fail", "failure_class": "type_error", "stderr": "tsc failed"},
        out,
    )

    ok, reasons = signed_training_eligible(record)

    assert ok, reasons
    assert record["trace_kind"] == "repair_task"
    assert record["repair_outcome"] == "pending"
    assert record["failure_class"] == "type_error"


def test_reject_result_is_schema_complete_training_signal(tmp_path):
    out = tmp_path / "aider_traces.jsonl"
    record = write_case_result(
        _case("cpp", "aider-cpp-001"),
        {
            "outcome": "reject",
            "reject_reason": "license_not_green",
            "failure_class": "license_not_green",
        },
        out,
    )

    ok, reasons = signed_training_eligible(record)

    assert ok, reasons
    assert record["trace_kind"] == "reject"
    assert record["failure_type"] == "license_not_green"


def test_infra_failure_is_signed_eval_evidence_not_training_row(tmp_path):
    out = tmp_path / "aider_traces.jsonl"
    record = write_case_result(
        _case("java", "aider-java-002"),
        {"outcome": "infra_failure", "failure_class": "container_timeout"},
        out,
    )

    ok, reasons = signed_training_eligible(record)

    assert verify_signature(record) is True
    assert ok is False
    assert "record_status:active_eval_evidence" in reasons
    assert record["record_status"] == "active_eval_evidence"
    assert record["training_eligible"] is False


def test_summary_tracks_language_balance(tmp_path):
    out = tmp_path / "aider_traces.jsonl"
    records = [
        write_case_result(
            _case("python", "aider-py-001"), {"outcome": "pass", "passed": True}, out
        ),
        write_case_result(
            _case("rust", "aider-rs-001"), {"outcome": "fail", "failure_class": "borrow_error"}, out
        ),
        write_case_result(
            _case("go", "aider-go-001"), {"outcome": "fail", "failure_class": "nil_pointer"}, out
        ),
    ]

    summary = summarize_records(records)

    assert summary["records"] == 3
    assert summary["training_eligible"] == 3
    assert summary["by_language"] == {"python": 1, "rust": 1, "go": 1}


def test_result_to_trace_keeps_aider_benchmark_name():
    trace = result_to_trace(_case("python").to_task_spec(), {"outcome": "pass", "passed": True})

    assert trace.benchmark == AIDER_BENCHMARK_NAME
    assert trace.trace_kind == "accept"


def case_to_row(case: AiderPolyglotCase) -> dict:
    return {
        "task_id": case.task_id,
        "language": case.language,
        "workspace": case.workspace,
        "instruction": case.instruction,
        "validation_commands": case.validation_commands,
        "license_provenance": case.license_provenance,
    }
