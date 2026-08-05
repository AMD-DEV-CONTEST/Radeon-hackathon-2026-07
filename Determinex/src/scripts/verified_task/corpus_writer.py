"""Verdict-rich corpus writer for universal benchmark traces.

Benchmark attempts are training data, so they must follow the same rule as
language repair traces: provenance fields plus HMAC signature. This writer
keeps the caller-provided staging path, but signs records through the shared
CorpusManager normalization/signing primitive before appending.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from agents.base_agent import CorpusType
from corpus.corpus_manager import CorpusManager

from .bench_to_corpus_eligibility import complete_benchmark_payload
from .task_spec import TaskSpec


class CorpusWriter:
    def __init__(self, path: Path, *, corpus_type: CorpusType = CorpusType.TERMINAL_TRACE) -> None:
        self.path = path
        self.corpus_type = corpus_type
        self._manager = CorpusManager(root=path.parent)

    def write_attempt(
        self,
        *,
        spec: TaskSpec,
        attempt_index: int,
        action_summary: str,
        validator_results: list[dict[str, Any]],
        verdict: str,
        failure_class: str | None = None,
        repair_prompt: str | None = None,
        patch_summary: str | None = None,
    ) -> None:
        payload = {
            "ts": time.time(),
            "benchmark": spec.benchmark,
            "task_id": spec.id,
            "language": spec.language,
            "source_kind": "benchmark_attempt",
            "initial_prompt": spec.prompt or spec.instruction,
            "workspace": spec.repo_or_workspace,
            "attempt_index": attempt_index,
            "attempt_code_or_patch": action_summary,
            "validator_results": validator_results,
            "verdict": verdict,
            "repair_outcome": verdict,
            "failure_class": failure_class,
            "failure_type": failure_class,
            "repair_prompt": repair_prompt,
            "final_patch": patch_summary,
            "privacy_policy": spec.privacy_policy,
            "cloak_mode": spec.cloak_mode,
            "license_gate": spec.metadata.get("license_gate", "unknown"),
            "safety_gate": spec.metadata.get("safety_gate", "unknown"),
            "supply_chain_gate": spec.metadata.get("supply_chain_gate", "unknown"),
            "model_router": spec.metadata.get("model_router", "unknown"),
            "router_used": spec.metadata.get("router_used", "unknown"),
            "validator": spec.validation_commands,
            "source_benchmark": spec.benchmark,
            "record_status": spec.metadata.get("record_status"),
            "license_provenance": (
                spec.metadata.get("license_provenance")
                or spec.metadata.get("license_bucket")
                or spec.metadata.get("license")
                or "unknown"
            ),
            "verifier_command": spec.validation_commands,
            "verifier_result": verdict,
            "corpus_type": self.corpus_type.value,
            "trace_hash": spec.metadata.get("trace_hash", ""),
        }
        payload = complete_benchmark_payload(payload)
        record = self._manager._normalize_record(
            corpus_type=self.corpus_type,
            task_id=spec.id,
            input_hash=spec.metadata.get("input_hash", spec.id),
            output_hash=spec.metadata.get("output_hash", f"{spec.id}:{attempt_index}:{verdict}"),
            source_benchmark=spec.benchmark,
            payload=payload,
        )
        self._manager._atomic_append(self.path, record)
