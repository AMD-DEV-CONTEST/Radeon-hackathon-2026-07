from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "scripts"))

from corpus.corpus_manager import verify_signature  # noqa: E402
from corpus.legacy_recovery.programbench_replay_verifier import (  # noqa: E402
    ProgramBenchReplayVerifier,
    ReplayBatchConfig,
)
from corpus.legacy_recovery.replay_outcome_writer import (  # noqa: E402
    OUTCOME_EVAL,
    OUTCOME_INFRA,
    OUTCOME_REJECT,
    OUTCOME_TRAINING,
    ReplayOutcome,
    ReplayOutcomeWriter,
)
from corpus.legacy_recovery.replay_workspace_builder import ReplayWorkspaceBuilder  # noqa: E402


def _candidate(
    tool: str = "sharkdp__fd.40d8eb3", failure_class: str = "path_env_dependency"
) -> dict:
    return {
        "tool": tool,
        "candidate_rows": 42,
        "failure_classes": [failure_class],
        "duplicate_cluster_id": f"{tool}::{failure_class}",
        "expected_verifier": "programbench eval",
        "language_guess": "rust",
        "legacy_row_hash": f"legacy_cluster:{tool}:{failure_class}",
        "priority_score": 42,
        "training_eligible": False,
        "requires_fresh_verifier": True,
    }


def _batch(path: Path, candidates: list[dict]) -> Path:
    path.write_text(json.dumps({"selected": candidates}, indent=2), encoding="utf-8")
    return path


def _verifier(tmp_path: Path, roots: list[Path], runner):
    config = ReplayBatchConfig(
        corpus_root=tmp_path / "corpus",
        output_jsonl=tmp_path / "programbench_replay_batch_001_rows.jsonl",
        result_path=tmp_path / "programbench_replay_batch_001_result.json",
        manifest_dir=tmp_path / "manifests",
    )
    return ProgramBenchReplayVerifier(
        workspace_builder=ReplayWorkspaceBuilder(roots),
        outcome_writer=ReplayOutcomeWriter(config.corpus_root, config.output_jsonl),
        runner=runner,
        config=config,
    )


def test_missing_workspace_writes_signed_infra_failure(tmp_path):
    batch = _batch(tmp_path / "batch.json", [_candidate()])
    verifier = _verifier(tmp_path, roots=[], runner=lambda workspace: {})

    report = verifier.run_batch(batch)
    rows = _read_rows(tmp_path / "programbench_replay_batch_001_rows.jsonl")

    assert report["attempted"] == 1
    assert report["signed_infra_failures"] == 1
    assert report["loose_artifacts"] == 0
    assert len(rows) == 1
    assert rows[0]["record_status"] == OUTCOME_INFRA
    assert rows[0]["training_eligible"] is False
    assert verify_signature(rows[0]) is True


def test_replay_success_without_repair_is_eval_evidence(tmp_path):
    workspace_root = tmp_path / "workspaces"
    (workspace_root / "sharkdp__fd.40d8eb3").mkdir(parents=True)
    batch = _batch(tmp_path / "batch.json", [_candidate()])

    def runner(workspace):
        return {
            "verifier_result": "pass",
            "repair_outcome": "pass",
            "failure_class": "path_env_dependency",
            "verifier_command": "programbench eval",
            "verifier_artifact": str(tmp_path / "eval.json"),
        }

    report = _verifier(tmp_path, [workspace_root], runner).run_batch(batch)
    rows = _read_rows(tmp_path / "programbench_replay_batch_001_rows.jsonl")

    assert report["active_eval_evidence"] == 1
    assert report["active_training_eligible"] == 0
    assert rows[0]["record_status"] == OUTCOME_EVAL
    assert rows[0]["training_eligible"] is False
    assert rows[0]["recovered_from"]["legacy_row_hash"].startswith("legacy_cluster:")
    assert verify_signature(rows[0]) is True


def test_replay_failure_writes_signed_reject(tmp_path):
    workspace_root = tmp_path / "workspaces"
    (workspace_root / "sharkdp__fd.40d8eb3").mkdir(parents=True)
    batch = _batch(tmp_path / "batch.json", [_candidate()])

    def runner(workspace):
        return {
            "verifier_result": "fail",
            "repair_outcome": "reject",
            "failure_class": "stdout_stderr_mismatch",
            "verifier_command": "programbench eval",
            "verifier_artifact": str(tmp_path / "eval.json"),
            "stderr": "expected stdout, got stderr",
            "exit_code": 1,
        }

    report = _verifier(tmp_path, [workspace_root], runner).run_batch(batch)
    rows = _read_rows(tmp_path / "programbench_replay_batch_001_rows.jsonl")

    assert report["signed_rejects"] == 1
    assert rows[0]["record_status"] == OUTCOME_REJECT
    assert rows[0]["failure_class"] == "stdout_stderr_mismatch"
    assert rows[0]["training_eligible"] is False
    assert verify_signature(rows[0]) is True


def test_training_row_requires_verified_repair_transition(tmp_path):
    writer = ReplayOutcomeWriter(tmp_path / "corpus", tmp_path / "rows.jsonl")
    with pytest.raises(ValueError):
        writer.write(
            _candidate(),
            ReplayOutcome(
                status=OUTCOME_TRAINING,
                verifier_result="pass",
                repair_outcome="pass",
                failure_class="path_env_dependency",
                verifier_command="programbench eval",
                verifier_artifact=str(tmp_path / "eval.json"),
                repair_transition=False,
            ),
        )


def test_repair_transition_can_create_training_eligible_row(tmp_path):
    workspace_root = tmp_path / "workspaces"
    (workspace_root / "sharkdp__fd.40d8eb3").mkdir(parents=True)
    batch = _batch(tmp_path / "batch.json", [_candidate()])

    def runner(workspace):
        return {
            "verifier_result": "pass",
            "repair_outcome": "pass",
            "failure_class": "path_env_dependency",
            "verifier_command": "programbench eval",
            "verifier_artifact": str(tmp_path / "eval.json"),
            "repair_transition": True,
        }

    report = _verifier(tmp_path, [workspace_root], runner).run_batch(batch)
    rows = _read_rows(tmp_path / "programbench_replay_batch_001_rows.jsonl")

    assert report["active_training_eligible"] == 1
    assert rows[0]["record_status"] == OUTCOME_TRAINING
    assert rows[0]["training_eligible"] is True
    assert rows[0]["repair_transition"] is True
    assert verify_signature(rows[0]) is True


def test_batch_writes_one_manifest_and_one_row_per_candidate(tmp_path):
    workspace_root = tmp_path / "workspaces"
    (workspace_root / "sharkdp__fd.40d8eb3").mkdir(parents=True)
    (workspace_root / "antonmedv__fx.86d0d34").mkdir(parents=True)
    candidates = [
        _candidate("sharkdp__fd.40d8eb3", "path_env_dependency"),
        _candidate("antonmedv__fx.86d0d34", "argv0_alias_regression"),
    ]
    batch = _batch(tmp_path / "batch.json", candidates)

    def runner(workspace):
        return {
            "status": OUTCOME_EVAL,
            "verifier_result": "pass",
            "repair_outcome": "pass",
            "failure_class": workspace.candidate["failure_classes"][0],
            "verifier_command": "programbench eval",
            "verifier_run_id": "run-123",
        }

    report = _verifier(tmp_path, [workspace_root], runner).run_batch(batch)
    rows = _read_rows(tmp_path / "programbench_replay_batch_001_rows.jsonl")
    manifests = list((tmp_path / "manifests").glob("*_replay_manifest.json"))

    assert report["candidates"] == 2
    assert report["attempted"] == 2
    assert len(rows) == 2
    assert len(manifests) == 2
    assert all(
        row["record_status"] in {OUTCOME_EVAL, OUTCOME_REJECT, OUTCOME_INFRA, OUTCOME_TRAINING}
        for row in rows
    )
    assert all(verify_signature(row) for row in rows)


def test_candidate_missing_hash_becomes_infra_failure(tmp_path):
    candidate = _candidate()
    candidate.pop("legacy_row_hash")
    candidate.pop("duplicate_cluster_id")
    batch = _batch(tmp_path / "batch.json", [candidate])
    verifier = _verifier(tmp_path, roots=[tmp_path], runner=lambda workspace: {})

    report = verifier.run_batch(batch)

    assert report["signed_infra_failures"] == 1
    assert report["results"][0]["status"] == OUTCOME_INFRA


def _read_rows(path: Path) -> list[dict]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
