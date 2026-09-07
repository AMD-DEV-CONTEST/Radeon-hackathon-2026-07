from dataclasses import asdict
from pathlib import Path

import torch

from radeonvla.artifact_io import validate_evaluation_payload
from radeonvla.evaluate import (
    EpisodeResult,
    _counts_as_first_attempt,
    _device_display_name,
    _release_is_verified,
    parse_args,
    select_instruction,
    summarize,
)
from radeonvla.tasks import get_task

ROOT = Path(__file__).resolve().parents[1]


def episode(**overrides) -> EpisodeResult:
    values = {
        "episode_id": "banana_white_left_1",
        "seed": 1,
        "task_id": "banana_white_left",
        "instruction": "Pick the banana.",
        "success": True,
        "object_correct": True,
        "target_correct": True,
        "first_attempt_success": True,
        "inference_latency_ms": [10.0, 20.0],
    }
    values.update(overrides)
    return EpisodeResult(**values)


def test_summary_reports_reflex_and_scenario_metrics() -> None:
    results = [
        episode(
            interrupted=True,
            safe_interrupt=True,
            interrupt_response_steps=0,
            scenario="interrupt",
        ),
        episode(
            episode_id="banana_white_left_2",
            seed=2,
            success=False,
            object_correct=False,
            target_correct=False,
            first_attempt_success=False,
            retry_count=1,
            scenario="target_shift",
        ),
    ]
    summary = summarize(results)
    assert summary["final_success"] == 0.5
    assert summary["safe_interrupt_rate"] == 1.0
    assert summary["mean_interrupt_response_steps"] == 0.0
    assert summary["success_by_task"]["banana_white_left"] == 0.5
    assert summary["success_by_scenario"] == {"interrupt": 1.0, "target_shift": 0.0}
    assert summary["p50_inference_latency_ms"] == 15.0


def test_episode_result_and_summary_match_formal_schema() -> None:
    result = episode()
    payload = {
        "experiment_id": "schema_test",
        "git_commit": "a" * 40,
        "environment": {
            "gpu": "cpu",
            "rocm": "none",
            "torch": "test",
            "genesis": "test",
            "lerobot": "test",
        },
        "checkpoint": {"uri": "test", "sha256": "b" * 64},
        "config": {},
        "summary": summarize([result]),
        "episodes": [asdict(result)],
    }
    validate_evaluation_payload(payload, ROOT / "artifacts" / "evaluation.schema.json")


def test_default_evaluation_seed_is_held_out_from_physical_1k() -> None:
    assert parse_args(["--policy-path", "dummy"]).seed_start == 50000


def test_evaluation_defaults_to_exact_collected_language() -> None:
    args = parse_args(["--policy-path", "dummy"])
    assert args.instruction_source == "collected"
    task = get_task("apple_blue_left")
    assert select_instruction(task, args.instruction_source, 0) == (
        "Pick the apple and place it in the blue bowl on the left."
    )
    assert select_instruction(task, args.instruction_source, 1) == (
        "Sort the apple into the blue bowl on the left."
    )


def test_heldout_language_is_explicit_opt_in() -> None:
    args = parse_args(["--policy-path", "dummy", "--instruction-source", "heldout"])
    task = get_task("plum_white_right")
    assert select_instruction(task, args.instruction_source) in task.evaluation_instructions


def test_precision_recovery_is_explicit_and_reported_separately() -> None:
    assert parse_args(["--policy-path", "dummy"]).precision_recovery is False
    assert parse_args(["--policy-path", "dummy", "--precision-recovery"]).precision_recovery is True

    results = [
        episode(),
        episode(
            episode_id="banana_white_left_2",
            seed=2,
            first_attempt_success=False,
            recovery_success=True,
            precision_recovery_attempted=True,
            precision_recovery_success=True,
        ),
    ]
    summary = summarize(results)
    assert summary["first_attempt_success"] == 0.5
    assert summary["final_success"] == 1.0
    assert summary["precision_recovery_attempts"] == 1
    assert summary["precision_recovery_success"] == 1.0
    assert summary["precision_recovery_contribution"] == 0.5


def test_precision_recovery_does_not_count_as_first_attempt() -> None:
    recovered = episode(
        first_attempt_success=False,
        recovery_success=True,
        precision_recovery_attempted=True,
        precision_recovery_success=True,
    )
    summary = summarize([recovered])
    assert summary["first_attempt_success"] == 0.0
    assert summary["final_success"] == 1.0


def test_failed_precision_attempt_cannot_be_reclassified_as_learned_success() -> None:
    assert _counts_as_first_attempt(success=True, retry_count=0, precision_recovery_attempted=False)
    assert not _counts_as_first_attempt(success=True, retry_count=0, precision_recovery_attempted=True)
    assert not _counts_as_first_attempt(success=True, retry_count=1, precision_recovery_attempted=False)


def test_video_success_requires_commanded_and_measured_release() -> None:
    opened_action = [0.0] * 7 + [0.04, 0.04]
    closed_action = [0.0] * 7 + [0.01, 0.01]
    opened_qpos = [0.0] * 7 + [0.03, 0.03]
    closed_qpos = [0.0] * 7 + [0.01, 0.01]

    assert _release_is_verified(opened_action, opened_qpos)
    assert not _release_is_verified(closed_action, opened_qpos)
    assert not _release_is_verified(opened_action, closed_qpos)
    assert not _release_is_verified(opened_action, [0.03])


def test_cpu_device_name_does_not_query_cuda(monkeypatch) -> None:
    def fail_if_called(_device):
        raise AssertionError("CUDA must not be queried for a CPU evaluation")

    monkeypatch.setattr(torch.cuda, "get_device_name", fail_if_called)
    assert _device_display_name(torch.device("cpu")) == "cpu"
