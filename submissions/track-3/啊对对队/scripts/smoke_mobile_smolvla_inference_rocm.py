"""Evaluate one representative frame per task stage with a mobile SmolVLA checkpoint."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import statistics
import time
from typing import Any

from parcel_sorter.mobile_dataset import MOBILE_STAGE_NAMES
from parcel_sorter.mobile_harness import select_mobile_harness_action
from parcel_sorter.mobile_task import decode_mobile_bimanual_action, limit_mobile_arm_step
from parcel_sorter.provenance import runtime_report


def _stage_frame_indices(dataset_root: Path) -> dict[tuple[int, str], int]:
    import pyarrow.parquet as pq

    parquet_files = sorted((dataset_root / "data").rglob("*.parquet"))
    if not parquet_files:
        raise FileNotFoundError(f"mobile dataset has no parquet files: {dataset_root}")
    stage_ids: list[int] = []
    episode_ids: list[int] = []
    for path in parquet_files:
        table = pq.read_table(
            path, columns=["observation.stage_id", "episode_index"]
        )
        for item in table["observation.stage_id"].combine_chunks():
            value = item.as_py()
            stage_ids.append(int(value[0] if isinstance(value, list) else value))
        episode_ids.extend(
            int(item.as_py()) for item in table["episode_index"].combine_chunks()
        )
    selected: dict[tuple[int, str], int] = {}
    for episode_id in sorted(set(episode_ids)):
        for stage_id, stage_name in enumerate(MOBILE_STAGE_NAMES):
            candidates = [
                index
                for index, (episode, stage) in enumerate(
                    zip(episode_ids, stage_ids, strict=True)
                )
                if episode == episode_id and stage == stage_id
            ]
            if not candidates:
                raise ValueError(
                    f"dataset contains no frame for episode {episode_id} stage {stage_name}"
                )
            selected[(episode_id, stage_name)] = candidates[len(candidates) // 2]
    return selected


def _batch(sample: dict[str, Any], config: Any, torch: Any) -> dict[str, Any]:
    return {
        key: (value.unsqueeze(0).cuda() if torch.is_tensor(value) else [value])
        for key, value in sample.items()
        if key in config.input_features or key == "task"
    }


def _reset(*components: Any) -> None:
    for component in components:
        reset = getattr(component, "reset", None)
        if callable(reset):
            reset()


def _percentile_95(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)]


def _error_metrics(action: list[float] | tuple[float, ...], expert: list[float]) -> dict[str, float]:
    errors = [actual - expected for actual, expected in zip(action, expert, strict=True)]
    return {
        "mae": statistics.fmean(abs(value) for value in errors),
        "mse": statistics.fmean(value * value for value in errors),
    }


def _within_envelope(
    action: list[float] | tuple[float, ...], state: list[float]
) -> bool:
    base_speed = math.hypot(action[0], action[1])
    quaternion_norms = (
        math.sqrt(sum(value * value for value in action[6:10])),
        math.sqrt(sum(value * value for value in action[14:18])),
    )
    return bool(
        base_speed <= 0.050001
        and abs(action[2]) <= 1.0
        and max(abs(value - 1.0) for value in quaternion_norms) <= 1e-3
        and math.dist(action[3:6], state[24:27]) <= 0.040001
        and math.dist(action[11:14], state[31:34]) <= 0.040001
        and all(value in (-1.0, 1.0) for value in (action[10], action[18]))
    )


def _action_metrics(
    predicted: list[float], expert: list[float], state: list[float]
) -> tuple[dict[str, Any], tuple[float, ...]]:
    errors = [actual - expected for actual, expected in zip(predicted, expert, strict=True)]
    base_speed = math.hypot(predicted[0], predicted[1])
    quaternion_norms = (
        math.sqrt(sum(value * value for value in predicted[6:10])),
        math.sqrt(sum(value * value for value in predicted[14:18])),
    )
    left_step = math.dist(predicted[3:6], state[24:27])
    right_step = math.dist(predicted[11:14], state[31:34])
    decoded = decode_mobile_bimanual_action(
        predicted,
        max_base_linear_speed_m_s=0.05,
    )
    bounded_left = limit_mobile_arm_step(decoded.left, tuple(state[24:27]))
    bounded_right = limit_mobile_arm_step(decoded.right, tuple(state[31:34]))
    decoded_base_speed = math.hypot(*decoded.base_velocity_xy_yaw[:2])
    clipped_action = (
        *decoded.base_velocity_xy_yaw,
        *bounded_left.position_m,
        *bounded_left.quaternion_wxyz,
        bounded_left.gripper,
        *bounded_right.position_m,
        *bounded_right.quaternion_wxyz,
        bounded_right.gripper,
    )
    return {
        "mae": statistics.fmean(abs(value) for value in errors),
        "mse": statistics.fmean(value * value for value in errors),
        "base_mae": statistics.fmean(abs(value) for value in errors[:3]),
        "left_arm_mae": statistics.fmean(abs(value) for value in errors[3:11]),
        "right_arm_mae": statistics.fmean(abs(value) for value in errors[11:19]),
        "raw_base_linear_speed_m_s": base_speed,
        "raw_base_yaw_rate_rad_s": predicted[2],
        "raw_quaternion_norms": list(quaternion_norms),
        "raw_cartesian_step_m": [left_step, right_step],
        "raw_tool_commands": [predicted[10], predicted[18]],
        "expert_tool_commands": [expert[10], expert[18]],
        "tool_command_sign_match": [
            (predicted[10] >= 0) == (expert[10] >= 0),
            (predicted[18] >= 0) == (expert[18] >= 0),
        ],
        "raw_action_within_expert_envelope": _within_envelope(predicted, state),
        "executor": {
            "accepted": True,
            "base_linear_speed_m_s": decoded_base_speed,
            "base_yaw_rate_rad_s": decoded.base_velocity_xy_yaw[2],
            "left_cartesian_step_m": math.dist(
                bounded_left.position_m, tuple(state[24:27])
            ),
            "right_cartesian_step_m": math.dist(
                bounded_right.position_m, tuple(state[31:34])
            ),
            "tool_commands": [decoded.left.gripper, decoded.right.gripper],
        },
    }, clipped_action


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20260727)
    args = parser.parse_args()

    import torch
    from lerobot.configs.policies import PreTrainedConfig
    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    from lerobot.policies import make_pre_post_processors
    from lerobot.policies.factory import get_policy_class

    config = PreTrainedConfig.from_pretrained(args.checkpoint, local_files_only=True)
    if config.input_features["observation.state"].shape != (43,):
        raise RuntimeError("checkpoint does not use the audited 43-D mobile state")
    action_width = int(config.output_features["action"].shape[0])
    if action_width not in (19, 20):
        raise RuntimeError("checkpoint must produce 19-D control with optional progress")
    config.device = "cuda"
    config.n_action_steps = 1
    policy = get_policy_class(config.type).from_pretrained(
        args.checkpoint,
        config=config,
        local_files_only=True,
    ).eval()
    preprocessor, postprocessor = make_pre_post_processors(
        policy.config,
        pretrained_path=str(args.checkpoint),
    )
    dataset = LeRobotDataset(
        "local/mobile-bimanual-parcel-expert",
        root=args.dataset_root,
        depth_output_unit="m",
    )
    selected = _stage_frame_indices(args.dataset_root)

    # Warm model kernels once; all reported stage timings are warm inference timings.
    warm_sample = dataset[next(iter(selected.values()))]
    torch.manual_seed(args.seed - 1)
    torch.cuda.manual_seed_all(args.seed - 1)
    _reset(policy, preprocessor, postprocessor)
    with torch.inference_mode():
        policy.select_action(preprocessor(_batch(warm_sample, config, torch)))
        torch.cuda.synchronize()

    stage_results = []
    for evaluation_index, ((episode_index, stage_name), frame_index) in enumerate(
        selected.items()
    ):
        sample = dataset[frame_index]
        stage_seed = args.seed + evaluation_index
        torch.manual_seed(stage_seed)
        torch.cuda.manual_seed_all(stage_seed)
        _reset(policy, preprocessor, postprocessor)
        batch = _batch(sample, config, torch)
        with torch.inference_mode():
            torch.cuda.synchronize()
            started = time.perf_counter()
            action = postprocessor(policy.select_action(preprocessor(batch)))
            torch.cuda.synchronize()
            latency_ms = (time.perf_counter() - started) * 1000.0
        policy_output = [float(value) for value in action.detach().cpu().reshape(-1)]
        expert_output = [float(value) for value in sample["action"].reshape(-1)]
        predicted = policy_output[:19]
        expert = expert_output[:19]
        state = [float(value) for value in sample["observation.state"].reshape(-1)]
        finite = len(policy_output) == action_width and all(
            math.isfinite(value) for value in policy_output
        )
        result: dict[str, Any] = {
            "stage": stage_name,
            "episode_index": episode_index,
            "seed": stage_seed,
            "frame_index": frame_index,
            "latency_ms": latency_ms,
            "action_shape": list(action.shape),
            "finite": finite,
            "primitive_progress": (
                {
                    "predicted": policy_output[19],
                    "target": expert_output[19],
                    "absolute_error": abs(policy_output[19] - expert_output[19]),
                }
                if action_width == 20
                else None
            ),
        }
        if finite:
            try:
                metrics, clipped_action = _action_metrics(predicted, expert, state)
                _, expert_executable = _action_metrics(expert, expert, state)
                decision = select_mobile_harness_action(
                    state=state,
                    expert_action=expert,
                    vla_action=predicted,
                    stage=stage_name,
                )
                clipped_error = _error_metrics(clipped_action, expert)
                harness_error = _error_metrics(decision.selected.action, expert)
                metrics["ablation"] = {
                    "expert_executor": {
                        **_error_metrics(expert_executable, expert),
                        "within_envelope": _within_envelope(expert_executable, state),
                    },
                    "raw_vla": {
                        **_error_metrics(predicted, expert),
                        "within_envelope": _within_envelope(predicted, state),
                    },
                    "safety_clipped_vla": {
                        **clipped_error,
                        "within_envelope": _within_envelope(clipped_action, state),
                    },
                    "harness_lite": {
                        **harness_error,
                        "within_envelope": _within_envelope(decision.selected.action, state),
                        "selected_scale": decision.selected.scale,
                        "candidate_count": len(decision.candidates),
                        "fallback_to_expert": decision.fallback_to_expert,
                        "emergency_stop": decision.emergency_stop,
                        "rejected_vla": decision.rejected_vla,
                        "tool_command_corrections": decision.selected.tool_command_corrections,
                        "reasons": list(decision.selected.reasons),
                    },
                }
                result.update(metrics)
            except ValueError as exc:
                result["executor"] = {"accepted": False, "error": str(exc)}
        stage_results.append(result)

    latencies = [float(item["latency_ms"]) for item in stage_results]
    valid = all(
        item["finite"]
        and item["action_shape"] == [1, action_width]
        and item.get("executor", {}).get("accepted", False)
        for item in stage_results
    )
    raw_envelope_pass_count = sum(
        bool(item.get("raw_action_within_expert_envelope")) for item in stage_results
    )
    ablation = {}
    for policy_name in (
        "expert_executor",
        "raw_vla",
        "safety_clipped_vla",
        "harness_lite",
    ):
        rows = [item["ablation"][policy_name] for item in stage_results]
        ablation[policy_name] = {
            "mean_mae": statistics.fmean(float(row["mae"]) for row in rows),
            "mean_mse": statistics.fmean(float(row["mse"]) for row in rows),
            "envelope_pass_count": sum(bool(row["within_envelope"]) for row in rows),
        }
    harness_rows = [item["ablation"]["harness_lite"] for item in stage_results]
    ablation["harness_lite"].update(
        {
            "mean_selected_scale": statistics.fmean(
                float(row["selected_scale"]) for row in harness_rows
            ),
            "expert_fallback_count": sum(
                bool(row["fallback_to_expert"]) for row in harness_rows
            ),
            "emergency_stop_count": sum(
                bool(row["emergency_stop"]) for row in harness_rows
            ),
            "tool_command_correction_count": sum(
                int(row["tool_command_corrections"]) for row in harness_rows
            ),
        }
    )
    payload = {
        "schema_version": 3,
        "status": (
            "passed_offline_action_raw_envelope"
            if valid and raw_envelope_pass_count == len(stage_results)
            else "passed_offline_action_requires_safety_clipping"
            if valid
            else "failed"
        ),
        "runtime": runtime_report(),
        "checkpoint": str(args.checkpoint.resolve()),
        "dataset_root": str(args.dataset_root.resolve()),
        "policy_type": config.type,
        "input_features": sorted(config.input_features),
        "observation_modality": (
            "rgbd"
            if "observation.images.overhead_depth_rgb" in config.input_features
            else "rgb"
        ),
        "state_shape": list(config.input_features["observation.state"].shape),
        "action_shape": list(config.output_features["action"].shape),
        "primitive_progress_enabled": action_width == 20,
        "mean_primitive_progress_absolute_error": (
            statistics.fmean(
                float(item["primitive_progress"]["absolute_error"])
                for item in stage_results
            )
            if action_width == 20
            else None
        ),
        "max_state_dim": int(config.max_state_dim),
        "max_action_dim": int(config.max_action_dim),
        "selection": (
            "middle frame of every episode-stage pair; policy queue reset per sample"
        ),
        "episodes_evaluated": len({item[0] for item in selected}),
        "base_seed": args.seed,
        "latency_ms": {
            "mean": statistics.fmean(latencies),
            "p95": _percentile_95(latencies),
            "maximum": max(latencies),
        },
        "offline_action_error": {
            "mean_stage_mae": statistics.fmean(
                float(item["mae"]) for item in stage_results
            ),
            "mean_stage_mse": statistics.fmean(
                float(item["mse"]) for item in stage_results
            ),
        },
        "offline_ablation": ablation,
        "stages": stage_results,
        "raw_action_envelope_pass_count": raw_envelope_pass_count,
        "claim_boundary": (
            f"offline checkpoint evaluation on {len({item[0] for item in selected})} "
            "expert episode(s); "
            "not closed-loop task success or generalization"
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload))
    return 0 if valid else 2


if __name__ == "__main__":
    raise SystemExit(main())
