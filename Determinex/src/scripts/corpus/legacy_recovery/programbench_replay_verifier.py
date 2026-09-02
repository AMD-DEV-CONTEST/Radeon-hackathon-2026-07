#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from corpus.legacy_recovery.replay_outcome_writer import (
    OUTCOME_EVAL,
    OUTCOME_INFRA,
    OUTCOME_REJECT,
    OUTCOME_TRAINING,
    ReplayOutcome,
    ReplayOutcomeWriter,
    classify_replay_outcome,
)
from corpus.legacy_recovery.replay_workspace_builder import ReplayWorkspace, ReplayWorkspaceBuilder

VerifierRunner = Callable[[ReplayWorkspace], dict[str, Any]]


@dataclass(slots=True)
class ReplayBatchConfig:
    batch_id: str = "legacy_replay_promotion_batch_001"
    max_candidates: int = 10
    corpus_root: Path = Path("assurance/evidence/replay_corpus")
    output_jsonl: Path = Path("assurance/evidence/programbench_replay_batch_001_rows.jsonl")
    result_path: Path = Path("assurance/evidence/programbench_replay_batch_001_result.json")
    manifest_dir: Path = Path("assurance/evidence/programbench_replay_manifests")


class ProgramBenchReplayVerifier:
    """Run selected legacy replay candidates through fresh ProgramBench verification.

    The live ProgramBench command runner is injected. The default runner marks
    candidates as infrastructure failures so this module never silently pretends
    that a live verifier ran.
    """

    def __init__(
        self,
        *,
        workspace_builder: ReplayWorkspaceBuilder,
        outcome_writer: ReplayOutcomeWriter,
        runner: VerifierRunner | None = None,
        config: ReplayBatchConfig | None = None,
    ) -> None:
        self.workspace_builder = workspace_builder
        self.outcome_writer = outcome_writer
        self.runner = runner or _default_runner
        self.config = config or ReplayBatchConfig()

    def run_batch(self, batch_artifact: Path) -> dict[str, Any]:
        batch = json.loads(batch_artifact.read_text(encoding="utf-8"))
        candidates = list(batch.get("selected") or [])[: self.config.max_candidates]
        self.config.manifest_dir.mkdir(parents=True, exist_ok=True)
        self.config.result_path.parent.mkdir(parents=True, exist_ok=True)

        results: list[dict[str, Any]] = []
        counts = {
            OUTCOME_TRAINING: 0,
            OUTCOME_EVAL: 0,
            OUTCOME_REJECT: 0,
            OUTCOME_INFRA: 0,
        }

        for candidate in candidates:
            workspace = self.workspace_builder.build(candidate, self.config.manifest_dir)
            if not workspace.hydrated:
                outcome = ReplayOutcome(
                    status=OUTCOME_INFRA,
                    verifier_result="fail",
                    repair_outcome="infra_failure",
                    failure_class=_failure_class(candidate),
                    verifier_command=str(candidate.get("expected_verifier") or "programbench eval"),
                    reason=workspace.reason,
                )
            else:
                outcome = classify_replay_outcome(self.runner(workspace))
            record = self.outcome_writer.write(candidate, outcome)
            counts[outcome.status] += 1
            manifest = _write_candidate_manifest(workspace, outcome, record)
            results.append(
                {
                    "tool": candidate.get("tool"),
                    "legacy_row_hash": candidate.get("legacy_row_hash"),
                    "duplicate_cluster_id": candidate.get("duplicate_cluster_id"),
                    "predicted_failure_class": _failure_class(candidate),
                    "fresh_failure_class": outcome.failure_class,
                    "status": outcome.status,
                    "record_status": record.get("record_status"),
                    "training_eligible": record.get("training_eligible") is True,
                    "trace_hash": record.get("trace_hash"),
                    "signed": bool(record.get("_sig")),
                    "manifest_path": str(manifest),
                    "verifier_artifact": outcome.verifier_artifact,
                    "verifier_run_id": outcome.verifier_run_id,
                }
            )

        report = {
            "schema_version": "determinex-programbench-replay-result-v1",
            "batch_id": self.config.batch_id,
            "source_batch": str(batch_artifact),
            "candidates": len(candidates),
            "attempted": len(results),
            "active_training_eligible": counts[OUTCOME_TRAINING],
            "active_eval_evidence": counts[OUTCOME_EVAL],
            "signed_rejects": counts[OUTCOME_REJECT],
            "signed_infra_failures": counts[OUTCOME_INFRA],
            "loose_artifacts": 0,
            "results": results,
            "policy": "Every replay candidate resolves to exactly one signed training/eval/reject/infra row.",
        }
        self.config.result_path.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return report


def _default_runner(workspace: ReplayWorkspace) -> dict[str, Any]:
    return {
        "status": OUTCOME_INFRA,
        "verifier_result": "fail",
        "repair_outcome": "infra_failure",
        "failure_class": _failure_class(workspace.candidate),
        "reason": "no_live_programbench_runner_configured",
    }


def _write_candidate_manifest(
    workspace: ReplayWorkspace, outcome: ReplayOutcome, record: dict[str, Any]
) -> Path:
    manifest_path = workspace.manifest_path
    if not manifest_path:
        manifest_path = (
            Path("assurance/evidence/programbench_replay_manifests")
            / "unknown_replay_manifest.json"
        )
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": "determinex-programbench-replay-candidate-manifest-v1",
        "tool": workspace.candidate.get("tool"),
        "workspace_path": str(workspace.workspace_path),
        "hydrated": workspace.hydrated,
        "hydrate_reason": workspace.reason,
        "outcome_status": outcome.status,
        "verifier_command": outcome.verifier_command,
        "verifier_artifact": outcome.verifier_artifact,
        "verifier_run_id": outcome.verifier_run_id,
        "trace_hash": record.get("trace_hash"),
        "record_status": record.get("record_status"),
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest_path


def _failure_class(candidate: dict[str, Any]) -> str:
    classes = candidate.get("failure_classes") or []
    return str(classes[0]) if classes else "unknown"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Replay selected legacy ProgramBench candidates through a fresh verifier."
    )
    parser.add_argument("batch_artifact", type=Path)
    parser.add_argument("--workspace-root", action="append", type=Path, default=[])
    parser.add_argument(
        "--corpus-root", type=Path, default=Path("assurance/evidence/replay_corpus")
    )
    parser.add_argument(
        "--output-jsonl",
        type=Path,
        default=Path("assurance/evidence/programbench_replay_batch_001_rows.jsonl"),
    )
    parser.add_argument(
        "--result",
        type=Path,
        default=Path("assurance/evidence/programbench_replay_batch_001_result.json"),
    )
    parser.add_argument(
        "--manifest-dir",
        type=Path,
        default=Path("assurance/evidence/programbench_replay_manifests"),
    )
    args = parser.parse_args()

    config = ReplayBatchConfig(
        corpus_root=args.corpus_root,
        output_jsonl=args.output_jsonl,
        result_path=args.result,
        manifest_dir=args.manifest_dir,
    )
    verifier = ProgramBenchReplayVerifier(
        workspace_builder=ReplayWorkspaceBuilder(args.workspace_root),
        outcome_writer=ReplayOutcomeWriter(args.corpus_root, args.output_jsonl),
        config=config,
    )
    report = verifier.run_batch(args.batch_artifact)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
