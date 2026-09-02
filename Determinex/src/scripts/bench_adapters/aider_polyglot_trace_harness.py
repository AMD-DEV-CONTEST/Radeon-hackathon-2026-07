"""Aider Polyglot trace harness.

This is not a scorer. It is the bridge that makes Aider-style benchmark
attempts corpus-producing by construction:

  manifest case -> TaskSpec -> benchmark result -> signed corpus row

The harness intentionally starts small. It accepts local manifest files and
emits one signed trace per attempt, so a later runner can scale without
inventing a new corpus path.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from agents.base_agent import CorpusType
from corpus.corpus_manager import CorpusManager
from verified_task.bench_to_corpus_eligibility import canonical_trace_hash, signed_training_eligible
from verified_task.benchmark_trace_contract import BenchmarkTrace, GenericBenchmarkTraceAdapter
from verified_task.language_profiles import default_validation_commands
from verified_task.task_spec import ResourceLimits, TaskSpec

AIDER_BENCHMARK_NAME = "Aider Polyglot"
AiderOutcome = Literal["pass", "fail", "reject", "infra_failure"]


@dataclass(slots=True)
class AiderPolyglotCase:
    task_id: str
    language: str
    workspace: str
    instruction: str
    validation_commands: list[str] = field(default_factory=list)
    license_provenance: str = "MIT"
    license_gate: str = "pass"
    safety_gate: str = "pass"
    supply_chain_gate: str = "pass"
    model_router: str = "local"
    source_id: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AiderPolyglotCase:
        return cls(
            task_id=str(data["task_id"]),
            language=str(data["language"]).lower(),
            workspace=str(data.get("workspace") or ""),
            instruction=str(data.get("instruction") or data.get("prompt") or ""),
            validation_commands=list(data.get("validation_commands") or []),
            license_provenance=str(data.get("license_provenance") or data.get("license") or "MIT"),
            license_gate=str(data.get("license_gate") or "pass"),
            safety_gate=str(data.get("safety_gate") or "pass"),
            supply_chain_gate=str(data.get("supply_chain_gate") or "pass"),
            model_router=str(data.get("model_router") or "local"),
            source_id=str(data.get("source_id") or ""),
        )

    def to_task_spec(self) -> TaskSpec:
        return TaskSpec(
            id=self.task_id,
            benchmark=AIDER_BENCHMARK_NAME,
            language=self.language,
            repo_or_workspace=self.workspace or None,
            instruction=self.instruction,
            validation_commands=self.validation_commands
            or default_validation_commands(self.language),
            scorer="all_commands_pass",
            privacy_policy="local",
            resource_limits=ResourceLimits(timeout_seconds=900, max_attempts=2, max_parallel=1),
            metadata={
                "adapter": "aider_polyglot_trace_harness",
                "license_gate": self.license_gate,
                "license_provenance": self.license_provenance,
                "safety_gate": self.safety_gate,
                "supply_chain_gate": self.supply_chain_gate,
                "model_router": self.model_router,
                "source_id": self.source_id,
            },
        )


def load_cases(path: Path) -> list[AiderPolyglotCase]:
    """Load a JSON/JSONL Aider case manifest."""
    text = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix.lower() == ".jsonl":
        rows = [json.loads(line) for line in text.splitlines() if line.strip()]
    else:
        data = json.loads(text)
        rows = data.get("cases", data) if isinstance(data, dict) else data
    if not isinstance(rows, list):
        raise ValueError("Aider manifest must be a list or an object with cases=[]")
    return [AiderPolyglotCase.from_dict(row) for row in rows]


def result_to_trace(spec: TaskSpec, result: dict[str, Any]) -> BenchmarkTrace:
    """Convert one Aider attempt result to the benchmark trace contract."""
    outcome = str(result.get("outcome") or result.get("verdict") or "").lower()
    adapter = GenericBenchmarkTraceAdapter()
    if outcome == "pass" or result.get("passed") is True:
        return adapter.accept_to_trace(spec, result)
    if outcome == "reject":
        return adapter.reject_to_trace(
            spec, str(result.get("reject_reason") or "benchmark_reject"), result
        )
    if outcome == "infra_failure":
        return BenchmarkTrace(
            trace_kind="infra_failure",
            task_id=spec.id,
            benchmark=spec.benchmark,
            language=spec.language,
            source_kind="benchmark_infra_failure",
            verdict="infra_failure",
            failure_type=str(result.get("failure_class") or "infra_failure"),
            validator=spec.validation_commands,
            license_gate=str(spec.metadata.get("license_gate", "unknown")),
            license_provenance=str(spec.metadata.get("license_provenance", "unknown")),
            safety_gate=str(spec.metadata.get("safety_gate", "unknown")),
            supply_chain_gate=str(spec.metadata.get("supply_chain_gate", "unknown")),
            repair_outcome="infra_failure",
            model_router=str(spec.metadata.get("model_router", "unknown")),
            payload={"result": result},
        )
    return adapter.failure_to_repair_task(spec, result)


def write_trace(
    trace: BenchmarkTrace, output_jsonl: Path, *, corpus_type: CorpusType = CorpusType.CODE_VERDICT
) -> dict[str, Any]:
    """Append a signed Aider trace row and return the signed record."""
    payload = trace.to_corpus_payload()
    if trace.trace_kind == "infra_failure":
        payload["record_status"] = "active_eval_evidence"
        payload["training_eligible"] = False
        payload["training_exclusion_reason"] = "infra_failure_not_training_fuel"
        payload["trace_hash"] = canonical_trace_hash(payload)

    manager = CorpusManager(root=output_jsonl.parent)
    record = manager._normalize_record(
        corpus_type=corpus_type,
        task_id=trace.task_id,
        input_hash=_stable_hash(trace.task_id + trace.benchmark + trace.language),
        output_hash=_stable_hash(json.dumps(payload, sort_keys=True, ensure_ascii=True)),
        source_benchmark=trace.benchmark,
        payload=payload,
    )
    manager._atomic_append(output_jsonl, record)
    return record


def write_case_result(
    case: AiderPolyglotCase, result: dict[str, Any], output_jsonl: Path
) -> dict[str, Any]:
    return write_trace(result_to_trace(case.to_task_spec(), result), output_jsonl)


def summarize_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    languages: dict[str, int] = {}
    statuses: dict[str, int] = {}
    training_eligible = 0
    for row in records:
        languages[str(row.get("language") or "unknown")] = (
            languages.get(str(row.get("language") or "unknown"), 0) + 1
        )
        statuses[str(row.get("record_status") or "unknown")] = (
            statuses.get(str(row.get("record_status") or "unknown"), 0) + 1
        )
        ok, _ = signed_training_eligible(row)
        if ok:
            training_eligible += 1
    return {
        "benchmark": AIDER_BENCHMARK_NAME,
        "records": len(records),
        "training_eligible": training_eligible,
        "by_language": languages,
        "by_record_status": statuses,
    }


def _stable_hash(text: str) -> str:
    return hashlib.blake2b(text.encode("utf-8", "replace"), digest_size=16).hexdigest()


def case_to_dict(case: AiderPolyglotCase) -> dict[str, Any]:
    return asdict(case)
