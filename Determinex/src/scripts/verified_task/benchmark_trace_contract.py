"""Benchmark-to-corpus adapter contract.

Every benchmark campaign must be trace-harvesting by default. Adapters can
produce accepted, rejected, failed, and repair-task traces, but they should not
finish a benchmark attempt without one of those signed trace intents.
"""

from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal

from .bench_to_corpus_eligibility import complete_benchmark_payload
from .task_spec import TaskSpec

TraceKind = Literal["attempt", "accept", "reject", "infra_failure", "repair_task"]


@dataclass(slots=True)
class BenchmarkTrace:
    trace_kind: TraceKind
    task_id: str
    benchmark: str
    language: str
    source_kind: str
    verdict: str
    failure_type: str = ""
    validator: str | list[str] = field(default_factory=list)
    license_gate: str = "unknown"
    license_provenance: str = "unknown"
    safety_gate: str = "unknown"
    supply_chain_gate: str = "unknown"
    repair_outcome: str = "unknown"
    model_router: str = "unknown"
    payload: dict[str, Any] = field(default_factory=dict)

    def to_corpus_payload(self) -> dict[str, Any]:
        payload = {
            "language": self.language,
            "benchmark": self.benchmark,
            "source_benchmark": self.benchmark,
            "task_id": self.task_id,
            "source_kind": self.source_kind,
            "trace_kind": self.trace_kind,
            "verdict": self.verdict,
            "failure_type": self.failure_type,
            "validator": self.validator,
            "license_gate": self.license_gate,
            "license_provenance": self.license_provenance,
            "safety_gate": self.safety_gate,
            "supply_chain_gate": self.supply_chain_gate,
            "repair_outcome": self.repair_outcome,
            "model_router": self.model_router,
            **self.payload,
        }
        return complete_benchmark_payload(payload)

    @staticmethod
    def trace_hash(payload: dict[str, Any]) -> str:
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=True)
        return hashlib.blake2b(raw.encode(), digest_size=16).hexdigest()


class BenchmarkTraceAdapter(ABC):
    """Required interface for benchmark adapters that feed Determinex corpus."""

    @abstractmethod
    def attempt_to_trace(self, spec: TaskSpec, result: dict[str, Any]) -> BenchmarkTrace:
        """Convert a benchmark attempt into a corpus trace."""

    @abstractmethod
    def reject_to_trace(
        self, spec: TaskSpec, reason: str, result: dict[str, Any] | None = None
    ) -> BenchmarkTrace:
        """Convert a gate/source/license rejection into a corpus trace."""

    @abstractmethod
    def accept_to_trace(self, spec: TaskSpec, result: dict[str, Any]) -> BenchmarkTrace:
        """Convert a successful benchmark acceptance into a corpus trace."""

    @abstractmethod
    def failure_to_repair_task(self, spec: TaskSpec, result: dict[str, Any]) -> BenchmarkTrace:
        """Convert a failed attempt into a repair-task trace."""


class GenericBenchmarkTraceAdapter(BenchmarkTraceAdapter):
    """Default adapter used when a benchmark has no custom trace mapping yet."""

    def attempt_to_trace(self, spec: TaskSpec, result: dict[str, Any]) -> BenchmarkTrace:
        verdict = str(result.get("verdict") or ("pass" if result.get("passed") else "fail"))
        failure_type = str(
            result.get("failure_type")
            or result.get("failure_class")
            or ("none" if verdict == "pass" else "validator_failure")
        )
        return self._trace(
            spec, "attempt", "benchmark_attempt", verdict, result, failure_type=failure_type
        )

    def reject_to_trace(
        self, spec: TaskSpec, reason: str, result: dict[str, Any] | None = None
    ) -> BenchmarkTrace:
        payload = dict(result or {})
        payload["reject_reason"] = reason
        return self._trace(
            spec, "reject", "benchmark_reject", "reject", payload, failure_type=reason
        )

    def accept_to_trace(self, spec: TaskSpec, result: dict[str, Any]) -> BenchmarkTrace:
        return self._trace(
            spec, "accept", "benchmark_accept", "pass", result, repair_outcome="pass"
        )

    def failure_to_repair_task(self, spec: TaskSpec, result: dict[str, Any]) -> BenchmarkTrace:
        failure_type = str(
            result.get("failure_type") or result.get("failure_class") or "validator_failure"
        )
        return self._trace(
            spec,
            "repair_task",
            "benchmark_failure_to_repair_task",
            "fail",
            result,
            failure_type=failure_type,
            repair_outcome="pending",
        )

    def _trace(
        self,
        spec: TaskSpec,
        trace_kind: TraceKind,
        source_kind: str,
        verdict: str,
        result: dict[str, Any],
        *,
        failure_type: str = "",
        repair_outcome: str = "unknown",
    ) -> BenchmarkTrace:
        return BenchmarkTrace(
            trace_kind=trace_kind,
            task_id=spec.id,
            benchmark=spec.benchmark,
            language=spec.language,
            source_kind=source_kind,
            verdict=verdict,
            failure_type=failure_type,
            validator=spec.validation_commands,
            license_gate=str(spec.metadata.get("license_gate", "unknown")),
            license_provenance=str(
                spec.metadata.get("license_provenance")
                or spec.metadata.get("license_bucket")
                or spec.metadata.get("license")
                or "unknown"
            ),
            safety_gate=str(spec.metadata.get("safety_gate", "unknown")),
            supply_chain_gate=str(spec.metadata.get("supply_chain_gate", "unknown")),
            repair_outcome=repair_outcome,
            model_router=str(spec.metadata.get("model_router", "unknown")),
            payload={"result": result},
        )
