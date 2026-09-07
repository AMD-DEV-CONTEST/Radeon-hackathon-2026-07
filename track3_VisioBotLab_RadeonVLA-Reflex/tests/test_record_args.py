import json
from types import SimpleNamespace

import pytest

from radeonvla.record_dataset import (
    _collection_complete,
    _instruction_for,
    _load_resume_progress,
    _missing_task_coverage,
    _missing_task_quota,
    _promote_dataset,
    _resume_expected_config,
    _saved_episode_counts,
    _staging_root,
    _task_cycle,
    parse_args,
)
from radeonvla.tasks import get_task


def test_parse_record_defaults() -> None:
    args = parse_args(["--episodes", "3", "--overwrite"])
    assert args.episodes == 3
    assert args.overwrite is True
    assert args.repo_id == "visiobot/radeonvla_reflex"
    assert args.episodes_per_task == 0
    assert args.allow_kinematic_assist is False
    assert args.resume_incomplete is False


def test_task_cycle_single_and_suite() -> None:
    args = parse_args(["--task", "banana_white_left"])
    assert _task_cycle(args) == ["banana_white_left"]
    args = parse_args(["--suite", "basic"])
    basic = set(_task_cycle(args))
    assert len(basic) == 20
    assert "banana_white_left" in basic and "apple_blue_left" in basic and "orange_blue_right" in basic
    args = parse_args(["--suite", "multistep"])
    assert "seq_triple_sort" in _task_cycle(args)
    assert "seq_apple_blue_left_orange_blue_right" in _task_cycle(args)


def test_training_instruction_comes_from_registry() -> None:
    task = get_task("lemon_white_right")
    text = _instruction_for("lemon_white_right", train=True)
    assert text in task.training_instructions
    assert text not in task.evaluation_instructions
    assert _instruction_for("lemon_white_right", train=True, variation=1) == task.training_instructions[1]


def test_per_task_quota_reports_short_tasks() -> None:
    selected = ["apple_blue_left", "banana_white_left"]
    counts = {"apple_blue_left": 50, "banana_white_left": 49}
    assert _missing_task_quota(selected, counts, 50) == ["banana_white_left"]
    counts["banana_white_left"] = 50
    assert _missing_task_quota(selected, counts, 50) == []
    assert _collection_complete(
        successes=100,
        requested=100,
        task_cycle=selected,
        per_task=counts,
        require_coverage=True,
        episodes_per_task=50,
    )


def test_resume_progress_rejects_changed_collection_settings(tmp_path) -> None:
    args = parse_args(
        [
            "--episodes-per-task",
            "50",
            "--backend",
            "amdgpu",
            "--dr-appearance",
            "--dr-object-color",
            "--dr-runtime",
        ]
    )
    tasks = _task_cycle(args)
    expected = _resume_expected_config(args, backend="amdgpu", task_cycle=tasks, requested_successes=1000)
    progress = {**expected, "status": "interrupted"}
    staging = tmp_path / ".dataset.inprogress"
    staging.mkdir()
    (staging / "recording_progress.json").write_text(json.dumps(progress))
    assert _load_resume_progress(staging, expected)["requested_successes"] == 1000

    changed = {**expected, "episodes_per_task_target": 49}
    with pytest.raises(ValueError, match="episodes_per_task_target"):
        _load_resume_progress(staging, changed)


def test_saved_episode_counts_are_rebuilt_from_episode_metadata() -> None:
    dataset = SimpleNamespace(
        meta=SimpleNamespace(
            episodes=[
                {
                    "episode_index": 0,
                    "tasks": [_instruction_for("apple_blue_left", variation=0)],
                },
                {
                    "episode_index": 1,
                    "tasks": [_instruction_for("apple_blue_left", variation=1)],
                },
                {
                    "episode_index": 2,
                    "tasks": ["FAILED: " + _instruction_for("banana_white_left", variation=0)],
                },
            ]
        )
    )
    successes, failures, counts = _saved_episode_counts(
        dataset,
        ["apple_blue_left", "banana_white_left"],
    )
    assert successes == 2
    assert failures == 1
    assert counts == {"apple_blue_left": 2, "banana_white_left": 0}


def test_required_coverage_reports_missing_tasks() -> None:
    selected = ["apple_blue_left", "banana_white_left"]
    counts = {"apple_blue_left": 1, "banana_white_left": 0}
    assert _missing_task_coverage(selected, counts) == ["banana_white_left"]
    counts["banana_white_left"] = 1
    assert _missing_task_coverage(selected, counts) == []


def test_collection_repairs_coverage_after_requested_count() -> None:
    selected = ["apple_blue_left", "banana_white_left"]
    counts = {"apple_blue_left": 20, "banana_white_left": 0}
    assert not _collection_complete(
        successes=20,
        requested=20,
        task_cycle=selected,
        per_task=counts,
        require_coverage=True,
    )
    counts["banana_white_left"] = 1
    assert _collection_complete(
        successes=21,
        requested=20,
        task_cycle=selected,
        per_task=counts,
        require_coverage=True,
    )


def test_staging_root_is_hidden_sibling(tmp_path) -> None:
    target = tmp_path / "dataset"
    assert _staging_root(target) == tmp_path / ".dataset.inprogress"


def test_promote_dataset_replaces_target_only_after_staging_exists(tmp_path) -> None:
    target = tmp_path / "dataset"
    target.mkdir()
    (target / "old.txt").write_text("old")
    staging = _staging_root(target)
    staging.mkdir()
    (staging / "new.txt").write_text("new")
    _promote_dataset(staging, target, overwrite=True)
    assert not staging.exists()
    assert not (target / "old.txt").exists()
    assert (target / "new.txt").read_text() == "new"
