from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "scripts"))

from agents.base_agent import CorpusType  # noqa: E402
from corpus.corpus_coverage_report import (  # noqa: E402
    CoverageThresholds,
    check_minimum_gate,
    generate_report,
)
from corpus.corpus_manager import CorpusManager  # noqa: E402
from verified_task import (  # noqa: E402
    CorpusWriter,
    GenericBenchmarkTraceAdapter,
    TaskSpec,
)


def _write_signed_code_row(root: Path, task_id: str, language: str, failure_type: str) -> None:
    cm = CorpusManager(root=root)
    payload = {
        "language": language,
        "framework": "unit",
        "build_system": "pytest" if language == "python" else "cargo",
        "source_kind": "synthetic_mutation",
        "failure_type": failure_type,
        "validator": "python -m pytest" if language == "python" else "cargo test --locked",
        "license_bucket": "green",
        "safety_gate": "pass",
        "supply_chain_gate": "pass",
        "repair_outcome": "pass",
        "model_router": "local",
        "trace_hash": task_id,
    }
    record = cm._normalize_record(
        corpus_type=CorpusType.CODE_VERDICT,
        task_id=task_id,
        input_hash=f"in-{task_id}",
        output_hash=f"out-{task_id}",
        source_benchmark="coverage_gate_test",
        payload=payload,
    )
    cm._write_record(CorpusType.CODE_VERDICT, record)


def test_corpus_writer_signs_verified_task_trace(tmp_path):
    spec = TaskSpec(
        id="bench-demo",
        benchmark="ProgramBench",
        language="rust",
        instruction="run official eval",
        validation_commands=["cargo test --locked"],
        metadata={
            "license_gate": "pass",
            "safety_gate": "pass",
            "supply_chain_gate": "pass",
            "model_router": "local",
        },
    )
    out = tmp_path / "trace.jsonl"
    CorpusWriter(out).write_attempt(
        spec=spec,
        attempt_index=1,
        action_summary="validator run",
        validator_results=[{"returncode": 0}],
        verdict="pass",
        failure_class="none",
    )
    record = json.loads(out.read_text(encoding="utf-8").splitlines()[0])
    assert "_sig" in record
    assert record["language"] == "rust"
    assert record["source_kind"] == "benchmark_attempt"
    assert record["license_gate"] == "pass"
    assert record["validator"] == ["cargo test --locked"]


def test_coverage_report_counts_core_dimensions(tmp_path):
    root = tmp_path / "corpus"
    _write_signed_code_row(root, "py-1", "python", "assertion_error")
    _write_signed_code_row(root, "rust-1", "rust", "panic")

    report = generate_report([root])

    assert report.total_rows == 2
    assert report.unsigned_count == 0
    assert report.by_language["python"] == 1
    assert report.by_language["rust"] == 1
    assert report.by_failure_type["assertion_error"] == 1
    assert report.by_benchmark["coverage_gate_test"] == 2
    assert report.by_safety_outcome["pass"] == 2


def test_coverage_gate_fails_unsigned_rows(tmp_path):
    root = tmp_path / "corpus"
    raw = root / "code_verdict" / "raw.jsonl"
    raw.parent.mkdir(parents=True)
    raw.write_text(
        json.dumps(
            {
                "task_id": "raw-1",
                "language": "python",
                "failure_type": "assertion_error",
                "source_benchmark": "raw",
                "validator": "python -m pytest",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    report = generate_report([root])
    failures = check_minimum_gate(report, CoverageThresholds(min_total_rows=1, min_signed_rows=1))

    assert "unsigned_rows_present:1" in failures
    assert any(reason.startswith("signed_rows_below_floor") for reason in failures)


def test_coverage_gate_can_require_durable_hmac_key():
    from corpus.corpus_coverage_report import CoverageReport

    report = CoverageReport(
        roots=[],
        total_rows=1,
        unsigned_count=0,
        current_signature_key_scope="ephemeral",
    )

    failures = check_minimum_gate(
        report,
        CoverageThresholds(
            min_total_rows=1,
            min_signed_rows=1,
            require_durable_signature_key=True,
        ),
    )

    assert "durable_hmac_key_missing:ephemeral" in failures


def test_resign_record_preserves_payload_and_verifies():
    from corpus.corpus_manager import resign_record, verify_signature

    record = {
        "schema_version": "determinex-agent-trace-v1",
        "corpus_type": "code_verdict",
        "task_id": "resign-001",
        "language": "python",
        "failure_type": "assertion_error",
        "_sig": "stale",
    }

    signed = resign_record(record)

    assert signed["task_id"] == "resign-001"
    assert signed["language"] == "python"
    assert signed["_sig"] != "stale"
    assert verify_signature(signed) is True


def test_coverage_gate_requires_language_failure_provenance_and_verifier(tmp_path):
    root = tmp_path / "corpus"
    raw = root / "code_verdict" / "bad.jsonl"
    raw.parent.mkdir(parents=True)
    raw.write_text(json.dumps({"task_id": "bad", "_sig": "x" * 128}) + "\n", encoding="utf-8")

    report = generate_report([root])
    failures = check_minimum_gate(
        report,
        CoverageThresholds(min_total_rows=1, min_signed_rows=1, require_no_unsigned=False),
    )

    assert "missing_language:1" in failures
    assert "missing_failure_type:1" in failures
    assert "missing_provenance:1" in failures
    assert "missing_verifier:1" in failures


def test_benchmark_trace_adapter_contract_outputs_all_trace_kinds(tmp_path):
    spec = TaskSpec(
        id="pb-demo",
        benchmark="ProgramBench",
        language="go",
        instruction="run eval",
        validation_commands=["go test ./..."],
        metadata={"license_gate": "pass", "safety_gate": "pass", "supply_chain_gate": "pass"},
    )
    adapter = GenericBenchmarkTraceAdapter()

    attempt = adapter.attempt_to_trace(spec, {"passed": False, "failure_class": "wrong_output"})
    reject = adapter.reject_to_trace(spec, "license_not_green")
    accept = adapter.accept_to_trace(spec, {"passed": True})
    repair = adapter.failure_to_repair_task(spec, {"failure_class": "wrong_output"})

    assert attempt.trace_kind == "attempt"
    assert reject.trace_kind == "reject"
    assert accept.trace_kind == "accept"
    assert repair.trace_kind == "repair_task"
    assert repair.to_corpus_payload()["trace_hash"]
