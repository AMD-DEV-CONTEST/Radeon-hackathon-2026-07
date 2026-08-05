from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "scripts"))

from agents.base_agent import CorpusType  # noqa: E402
from corpus.corpus_manager import CorpusManager  # noqa: E402
from verified_task import (  # noqa: E402
    CorpusWriter,
    GenericBenchmarkTraceAdapter,
    TaskSpec,
    signed_training_eligible,
)


def _spec(
    benchmark: str, language: str = "python", validator: str = "python -m pytest"
) -> TaskSpec:
    return TaskSpec(
        id=f"{benchmark.lower().replace('-', '_')}_001",
        benchmark=benchmark,
        language=language,
        instruction="run verifier and capture trace",
        validation_commands=[validator],
        metadata={
            "license_gate": "pass",
            "license_provenance": "MIT",
            "safety_gate": "pass",
            "supply_chain_gate": "pass",
            "model_router": "local",
        },
    )


def _signed_record(payload: dict, tmp_path: Path) -> dict:
    cm = CorpusManager(root=tmp_path / "corpus")
    record = cm._normalize_record(
        corpus_type=CorpusType.CODE_VERDICT,
        task_id=payload["task_id"],
        input_hash=f"in-{payload['task_id']}",
        output_hash=f"out-{payload['task_id']}",
        source_benchmark=payload["source_benchmark"],
        payload=payload,
    )
    assert cm.verify(record) is True
    return record


def _assert_training_eligible(payload: dict, tmp_path: Path) -> dict:
    record = _signed_record(payload, tmp_path)
    ok, reasons = signed_training_eligible(record)
    assert ok, reasons
    assert record["record_status"] == "active_training_eligible"
    assert record["training_eligible"] is True
    assert record["trace_hash_schema_version"] == "canonical-v2"
    assert record["trace_hash"]
    assert record["verifier_command"]
    assert record["verifier_result"]
    assert record["failure_class"]
    assert record["license_provenance"] == "MIT"
    return record


def test_programbench_reject_trace_is_schema_complete(tmp_path):
    trace = GenericBenchmarkTraceAdapter().reject_to_trace(
        _spec("ProgramBench", language="go", validator="go test ./..."),
        "passed_delta_negative",
        {"passed": 342, "baseline": 349},
    )
    payload = trace.to_corpus_payload()

    record = _assert_training_eligible(payload, tmp_path)

    assert record["trace_kind"] == "reject"
    assert record["source_kind"] == "benchmark_reject"
    assert record["verifier_result"] == "reject"
    assert record["failure_type"] == "passed_delta_negative"


def test_programbench_accept_trace_is_schema_complete(tmp_path):
    trace = GenericBenchmarkTraceAdapter().accept_to_trace(
        _spec("ProgramBench", language="rust", validator="cargo test --locked"),
        {"passed": 250, "total": 250},
    )

    record = _assert_training_eligible(trace.to_corpus_payload(), tmp_path)

    assert record["trace_kind"] == "accept"
    assert record["repair_outcome"] == "pass"


def test_aider_polyglot_trace_is_schema_complete(tmp_path):
    trace = GenericBenchmarkTraceAdapter().attempt_to_trace(
        _spec("Aider Polyglot", language="java", validator="mvn test"),
        {"passed": True, "failure_class": "none"},
    )

    record = _assert_training_eligible(trace.to_corpus_payload(), tmp_path)

    assert record["source_benchmark"] == "Aider Polyglot"
    assert record["language"] == "java"


def test_terminal_bench_trace_is_schema_complete(tmp_path):
    trace = GenericBenchmarkTraceAdapter().attempt_to_trace(
        _spec("Terminal-Bench", language="bash", validator="pytest -q"),
        {"passed": False, "failure_class": "cli_state_mismatch"},
    )

    record = _assert_training_eligible(trace.to_corpus_payload(), tmp_path)

    assert record["source_benchmark"] == "Terminal-Bench"
    assert record["failure_class"] == "cli_state_mismatch"


def test_swebench_trace_is_schema_complete(tmp_path):
    trace = GenericBenchmarkTraceAdapter().failure_to_repair_task(
        _spec("SWE-bench Pro", language="python", validator="python -m pytest"),
        {"failure_class": "pytest_failure", "issue_id": "repo__issue-1"},
    )

    record = _assert_training_eligible(trace.to_corpus_payload(), tmp_path)

    assert record["trace_kind"] == "repair_task"
    assert record["repair_outcome"] == "pending"


def test_sql_bird_trace_is_schema_complete(tmp_path):
    trace = GenericBenchmarkTraceAdapter().attempt_to_trace(
        _spec("BIRD", language="sql", validator="sqlite result compare"),
        {"passed": False, "failure_class": "wrong_result_set"},
    )

    record = _assert_training_eligible(trace.to_corpus_payload(), tmp_path)

    assert record["language"] == "sql"
    assert record["verifier_command"] == ["sqlite result compare"]


def test_browser_trace_is_schema_complete(tmp_path):
    trace = GenericBenchmarkTraceAdapter().attempt_to_trace(
        _spec("Browser", language="typescript", validator="playwright test"),
        {"passed": True, "failure_class": "none", "oracle": "DOM+URL+screenshot"},
    )

    record = _assert_training_eligible(trace.to_corpus_payload(), tmp_path)

    assert record["source_benchmark"] == "Browser"
    assert record["safety_gate"] == "pass"


def test_unsigned_row_rejected():
    ok, reasons = signed_training_eligible(
        {
            "record_status": "active_training_eligible",
            "training_eligible": True,
            "schema_version": "determinex-agent-trace-v1",
            "corpus_type": "code_verdict",
            "language": "python",
            "source_kind": "benchmark_attempt",
            "source_benchmark": "ProgramBench",
            "license_provenance": "MIT",
            "verifier_command": "python -m pytest",
            "verifier_result": "pass",
            "failure_class": "none",
            "failure_type": "none",
            "repair_outcome": "pass",
            "trace_hash_schema_version": "canonical-v2",
            "trace_hash": "x",
            "signature_key_scope": "durable",
        }
    )

    assert ok is False
    assert "invalid_or_missing_signature" in reasons


def test_missing_verifier_row_marked_non_training_eligible(tmp_path):
    trace = GenericBenchmarkTraceAdapter().attempt_to_trace(
        _spec("ProgramBench", language="python", validator="python -m pytest"),
        {"passed": True},
    )
    payload = trace.to_corpus_payload()
    payload["verifier_command"] = ""
    payload["record_status"] = "legacy_backfill_needed"
    payload["training_eligible"] = False

    record = _signed_record(payload, tmp_path)
    ok, reasons = signed_training_eligible(record)

    assert ok is False
    assert "missing_verifier_command" in reasons
    assert "training_eligible_not_true" in reasons


def test_corpus_writer_outputs_training_eligible_signed_row(tmp_path):
    out = tmp_path / "trace.jsonl"
    CorpusWriter(out, corpus_type=CorpusType.CODE_VERDICT).write_attempt(
        spec=_spec("Terminal-Bench", language="bash", validator="pytest -q"),
        attempt_index=1,
        action_summary="ran command sequence",
        validator_results=[{"returncode": 0}],
        verdict="pass",
        failure_class="none",
    )
    record = json.loads(out.read_text(encoding="utf-8").splitlines()[0])

    ok, reasons = signed_training_eligible(record)

    assert ok, reasons
    assert record["record_status"] == "active_training_eligible"
