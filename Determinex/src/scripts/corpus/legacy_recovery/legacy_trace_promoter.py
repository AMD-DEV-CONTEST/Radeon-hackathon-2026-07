from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agents.base_agent import CorpusType
from verified_task.bench_to_corpus_eligibility import complete_benchmark_payload

from corpus.corpus_manager import CorpusManager


@dataclass(slots=True)
class FreshVerifierResult:
    verifier_command: str
    verifier_result: str
    failure_class: str
    repair_outcome: str
    license_provenance: str
    verifier_artifact: str = ""
    verifier_run_id: str = ""
    safety_gate: str = "pass"
    supply_chain_gate: str = "pass"

    @property
    def gates_pass(self) -> bool:
        return (
            bool(self.verifier_command)
            and self.verifier_result in {"pass", "fail", "reject"}
            and bool(self.verifier_artifact or self.verifier_run_id)
            and self.license_provenance.lower() not in {"", "unknown", "none"}
            and self.safety_gate == "pass"
            and self.supply_chain_gate == "pass"
        )


def promote_replayed_trace(
    legacy_item: dict[str, Any],
    verifier: FreshVerifierResult,
    *,
    output_jsonl: Path,
    language: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Write a new recovered row only after fresh verifier evidence exists."""
    if not verifier.gates_pass:
        raise ValueError("legacy replay promotion requires verifier/license/safety gates")
    base = dict(payload or {})
    legacy_hash = str(legacy_item.get("legacy_row_hash") or "")
    row = complete_benchmark_payload(
        {
            **base,
            "task_id": str(
                legacy_item.get("test_id") or legacy_item.get("tool") or legacy_hash[:16]
            ),
            "language": language,
            "benchmark": "ProgramBench",
            "source_benchmark": "programbench",
            "source_kind": "legacy_replay_recovered",
            "verifier_command": verifier.verifier_command,
            "verifier_result": verifier.verifier_result,
            "verifier_artifact": verifier.verifier_artifact,
            "verifier_run_id": verifier.verifier_run_id,
            "failure_class": verifier.failure_class,
            "failure_type": verifier.failure_class,
            "repair_outcome": verifier.repair_outcome,
            "license_provenance": verifier.license_provenance,
            "safety_gate": verifier.safety_gate,
            "supply_chain_gate": verifier.supply_chain_gate,
            "recovered_from": {
                "legacy_corpus": "programbench_local_legacy",
                "legacy_row_hash": legacy_hash,
                "legacy_bucket": str(legacy_item.get("bucket") or "unknown"),
            },
            "recovery_method": "fresh_verifier_replay",
        }
    )
    manager = CorpusManager(root=output_jsonl.parent)
    record = manager._normalize_record(
        corpus_type=CorpusType.CODE_VERDICT,
        task_id=str(row["task_id"]),
        input_hash=_hash(legacy_hash + verifier.verifier_command),
        output_hash=_hash(json.dumps(row, sort_keys=True, ensure_ascii=True)),
        source_benchmark="programbench",
        payload=row,
    )
    manager._atomic_append(output_jsonl, record)
    return record


def _hash(text: str) -> str:
    return hashlib.blake2b(text.encode("utf-8", "replace"), digest_size=16).hexdigest()
