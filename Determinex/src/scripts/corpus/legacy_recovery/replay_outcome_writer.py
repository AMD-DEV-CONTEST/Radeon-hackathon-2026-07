from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agents.base_agent import CorpusType
from verified_task.bench_to_corpus_eligibility import complete_benchmark_payload

from corpus.corpus_manager import CorpusManager

OUTCOME_TRAINING = "active_training_eligible"
OUTCOME_EVAL = "active_eval_evidence"
OUTCOME_REJECT = "signed_reject"
OUTCOME_INFRA = "signed_infra_failure"
ALLOWED_OUTCOMES = {OUTCOME_TRAINING, OUTCOME_EVAL, OUTCOME_REJECT, OUTCOME_INFRA}


@dataclass(slots=True)
class ReplayOutcome:
    status: str
    verifier_result: str
    repair_outcome: str
    failure_class: str
    verifier_command: str
    verifier_artifact: str = ""
    verifier_run_id: str = ""
    stdout: str = ""
    stderr: str = ""
    exit_code: int | None = None
    eval_json_path: str = ""
    reason: str = ""
    repair_transition: bool = False


class ReplayOutcomeWriter:
    """Write exactly one signed outcome row for each replay candidate."""

    def __init__(self, corpus_root: Path, output_jsonl: Path) -> None:
        self.manager = CorpusManager(root=corpus_root)
        self.output_jsonl = output_jsonl

    def write(self, candidate: dict[str, Any], outcome: ReplayOutcome) -> dict[str, Any]:
        if outcome.status not in ALLOWED_OUTCOMES:
            raise ValueError(f"unknown replay outcome status: {outcome.status}")
        if outcome.status == OUTCOME_TRAINING and not outcome.repair_transition:
            raise ValueError(
                "active_training_eligible replay rows require a verified repair transition"
            )

        base = complete_benchmark_payload(
            {
                "task_id": _task_id(candidate),
                "language": candidate.get("language_guess") or "unknown",
                "benchmark": "ProgramBench",
                "source_benchmark": "programbench",
                "source_kind": "legacy_replay_recovered",
                "tool": candidate.get("tool") or "unknown",
                "verifier_command": outcome.verifier_command,
                "verifier_result": outcome.verifier_result,
                "verifier_artifact": outcome.verifier_artifact,
                "verifier_run_id": outcome.verifier_run_id,
                "failure_class": outcome.failure_class,
                "failure_type": outcome.failure_class,
                "repair_outcome": outcome.repair_outcome,
                "license_provenance": candidate.get("license_provenance")
                or "ProgramBench legacy bounded provenance",
                "safety_gate": "pass" if outcome.status != OUTCOME_INFRA else "not_applicable",
                "supply_chain_gate": "pass"
                if outcome.status != OUTCOME_INFRA
                else "not_applicable",
                "recovered_from": {
                    "legacy_corpus": "programbench_local_legacy",
                    "legacy_row_hash": str(candidate.get("legacy_row_hash") or ""),
                    "legacy_bucket": str(candidate.get("bucket") or "reconstructable_verifier_row"),
                    "duplicate_cluster_id": str(candidate.get("duplicate_cluster_id") or ""),
                },
                "recovery_method": "fresh_verifier_replay",
                "replay_outcome_status": outcome.status,
                "stdout_excerpt": outcome.stdout[:2000],
                "stderr_excerpt": outcome.stderr[:2000],
                "exit_code": outcome.exit_code,
                "eval_json_path": outcome.eval_json_path,
                "replay_reason": outcome.reason,
                "repair_transition": outcome.repair_transition,
            }
        )

        # complete_benchmark_payload marks schema-complete rows as training eligible.
        # Replay rows are more restrictive: only verified failure->repair->pass
        # transitions may train. Everything else stays signed evidence/reject/infra.
        if outcome.status == OUTCOME_TRAINING:
            base["record_status"] = OUTCOME_TRAINING
            base["training_eligible"] = True
        else:
            base["record_status"] = outcome.status
            base["training_eligible"] = False
            base["training_exclusion_reason"] = outcome.status

        record = self.manager._normalize_record(
            corpus_type=CorpusType.CODE_VERDICT,
            task_id=str(base["task_id"]),
            input_hash=_hash(json.dumps(candidate, sort_keys=True, ensure_ascii=True)),
            output_hash=_hash(json.dumps(base, sort_keys=True, ensure_ascii=True)),
            source_benchmark="programbench",
            payload=base,
        )
        self.manager._atomic_append(self.output_jsonl, record)
        return record


def classify_replay_outcome(result: dict[str, Any]) -> ReplayOutcome:
    status = str(result.get("status") or "")
    if status in ALLOWED_OUTCOMES:
        return ReplayOutcome(
            status=status,
            verifier_result=str(result.get("verifier_result") or "fail"),
            repair_outcome=str(result.get("repair_outcome") or status),
            failure_class=str(result.get("failure_class") or "unknown"),
            verifier_command=str(result.get("verifier_command") or "programbench eval"),
            verifier_artifact=str(result.get("verifier_artifact") or ""),
            verifier_run_id=str(result.get("verifier_run_id") or ""),
            stdout=str(result.get("stdout") or ""),
            stderr=str(result.get("stderr") or ""),
            exit_code=result.get("exit_code"),
            eval_json_path=str(result.get("eval_json_path") or ""),
            reason=str(result.get("reason") or ""),
            repair_transition=bool(result.get("repair_transition")),
        )

    verifier_result = str(result.get("verifier_result") or "").lower()
    repair_transition = bool(result.get("repair_transition"))
    repair_outcome = str(result.get("repair_outcome") or verifier_result or "unknown").lower()
    if result.get("infra_failure"):
        status = OUTCOME_INFRA
    elif repair_transition and verifier_result == "pass" and repair_outcome == "pass":
        status = OUTCOME_TRAINING
    elif verifier_result == "pass":
        status = OUTCOME_EVAL
    else:
        status = OUTCOME_REJECT
    return ReplayOutcome(
        status=status,
        verifier_result=verifier_result or ("reject" if status == OUTCOME_REJECT else "fail"),
        repair_outcome=repair_outcome,
        failure_class=str(result.get("failure_class") or "unknown"),
        verifier_command=str(result.get("verifier_command") or "programbench eval"),
        verifier_artifact=str(result.get("verifier_artifact") or ""),
        verifier_run_id=str(result.get("verifier_run_id") or ""),
        stdout=str(result.get("stdout") or ""),
        stderr=str(result.get("stderr") or ""),
        exit_code=result.get("exit_code"),
        eval_json_path=str(result.get("eval_json_path") or ""),
        reason=str(result.get("reason") or ""),
        repair_transition=repair_transition,
    )


def _task_id(candidate: dict[str, Any]) -> str:
    tool = str(candidate.get("tool") or "unknown")
    cluster = str(
        candidate.get("duplicate_cluster_id") or candidate.get("legacy_row_hash") or "unknown"
    )
    return f"legacy_replay::{tool}::{cluster[:24]}"


def _hash(text: str) -> str:
    return hashlib.blake2b(text.encode("utf-8", "replace"), digest_size=16).hexdigest()
