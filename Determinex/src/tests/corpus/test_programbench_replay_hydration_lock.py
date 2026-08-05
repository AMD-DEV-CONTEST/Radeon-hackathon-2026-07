from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "scripts"))

from corpus.legacy_recovery.replay_hydration import (  # noqa: E402
    HydrationConfig,
    HydrationStatus,
    ProgramBenchReplayHydrator,
)


def _candidate(tool: str = "sharkdp__fd.40d8eb3") -> dict:
    return {
        "tool": tool,
        "failure_classes": ["path_env_dependency"],
        "language_guess": "rust",
        "legacy_row_hash": "legacy_cluster:abc123",
        "duplicate_cluster_id": "abc123",
        "expected_verifier": "programbench eval",
        "priority_score": 42,
    }


def _config(
    tmp_path: Path, *, require_image: bool = False, require_baseline: bool = False
) -> HydrationConfig:
    return HydrationConfig(
        task_roots=[tmp_path / "tasks"],
        candidate_roots=[tmp_path / "candidates"],
        programbench_roots=[tmp_path / "programbench"],
        image_roots=[tmp_path / "images"],
        output_path=tmp_path / "hydration.json",
        require_image=require_image,
        require_baseline=require_baseline,
    )


def _make_ready_layout(tmp_path: Path, tool: str = "sharkdp__fd.40d8eb3") -> None:
    task = tmp_path / "tasks" / tool
    candidate = tmp_path / "candidates" / tool
    harness = tmp_path / "programbench"
    task.mkdir(parents=True)
    candidate.mkdir(parents=True)
    harness.mkdir(parents=True)
    (harness / "pyproject.toml").write_text("[project]\nname='programbench'\n", encoding="utf-8")
    (candidate / "executable").write_text("#!/bin/sh\n", encoding="utf-8")


def test_hydrated_ready_when_all_required_parts_exist(tmp_path):
    _make_ready_layout(tmp_path)
    result = ProgramBenchReplayHydrator(_config(tmp_path)).hydrate_candidate(_candidate())

    assert result.status == HydrationStatus.HYDRATED_READY.value
    assert result.task_root
    assert result.candidate_root
    assert result.eval_command.startswith("uv run programbench eval")
    assert result.workspace_checksum


def test_missing_task_root_status(tmp_path):
    result = ProgramBenchReplayHydrator(_config(tmp_path)).hydrate_candidate(_candidate())

    assert result.status == HydrationStatus.MISSING_TASK_ROOT.value
    assert result.reason == "task_root_not_found"


def test_missing_candidate_root_status(tmp_path):
    task = tmp_path / "tasks" / "sharkdp__fd.40d8eb3"
    task.mkdir(parents=True)
    result = ProgramBenchReplayHydrator(_config(tmp_path)).hydrate_candidate(_candidate())

    assert result.status == HydrationStatus.MISSING_CANDIDATE_ROOT.value


def test_missing_eval_harness_status(tmp_path):
    (tmp_path / "tasks" / "sharkdp__fd.40d8eb3").mkdir(parents=True)
    (tmp_path / "candidates" / "sharkdp__fd.40d8eb3").mkdir(parents=True)
    result = ProgramBenchReplayHydrator(_config(tmp_path)).hydrate_candidate(_candidate())

    assert result.status == HydrationStatus.MISSING_EVAL_HARNESS.value


def test_missing_docker_image_status_when_required(tmp_path):
    _make_ready_layout(tmp_path)
    result = ProgramBenchReplayHydrator(_config(tmp_path, require_image=True)).hydrate_candidate(
        _candidate()
    )

    assert result.status == HydrationStatus.MISSING_DOCKER_IMAGE.value


def test_missing_baseline_status_when_required(tmp_path):
    _make_ready_layout(tmp_path)
    result = ProgramBenchReplayHydrator(_config(tmp_path, require_baseline=True)).hydrate_candidate(
        _candidate()
    )

    assert result.status == HydrationStatus.MISSING_BASELINE.value


def test_ambiguous_tool_match_status(tmp_path):
    (tmp_path / "tasks" / "sharkdp__fd.40d8eb3").mkdir(parents=True)
    (tmp_path / "other_tasks" / "sharkdp__fd.40d8eb3").mkdir(parents=True)
    config = _config(tmp_path)
    config.task_roots.append(tmp_path / "other_tasks")
    result = ProgramBenchReplayHydrator(config).hydrate_candidate(_candidate())

    assert result.status == HydrationStatus.AMBIGUOUS_TOOL_MATCH.value


def test_checksum_mismatch_status(tmp_path):
    _make_ready_layout(tmp_path)
    candidate = _candidate()
    candidate["workspace_checksum"] = "not-the-real-checksum"
    result = ProgramBenchReplayHydrator(_config(tmp_path)).hydrate_candidate(candidate)

    assert result.status == HydrationStatus.CHECKSUM_MISMATCH.value


def test_unsupported_legacy_format_status(tmp_path):
    result = ProgramBenchReplayHydrator(_config(tmp_path)).hydrate_candidate({"tool": ""})

    assert result.status == HydrationStatus.UNSUPPORTED_LEGACY_FORMAT.value


def test_batch_report_writes_status_counts(tmp_path):
    _make_ready_layout(tmp_path)
    batch = tmp_path / "batch.json"
    batch.write_text(json.dumps({"selected": [_candidate(), {"tool": ""}]}), encoding="utf-8")

    report = ProgramBenchReplayHydrator(_config(tmp_path)).hydrate_batch(batch)

    assert report["candidates"] == 2
    assert report["status_counts"][HydrationStatus.HYDRATED_READY.value] == 1
    assert report["status_counts"][HydrationStatus.UNSUPPORTED_LEGACY_FORMAT.value] == 1
    assert (tmp_path / "hydration.json").exists()
