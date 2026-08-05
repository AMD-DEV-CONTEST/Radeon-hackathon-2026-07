#!/usr/bin/env python3
"""Collect fixed SmolVLA LIBERO rollouts and build an RLinf replay buffer."""

from __future__ import annotations

import argparse
import json
import pickle
from pathlib import Path

import numpy as np
import torch
from omegaconf import OmegaConf

from rlinf.data.replay_buffer import TrajectoryReplayBuffer
from rlinf.envs.libero.libero_env import LiberoEnv
from rlinf.envs.libero.utils import get_benchmark_overridden
from rlinf.envs.wrappers import CollectEpisode
from rlinf.models import get_model
from smolvla_qvgm_rlinf.data.collect_episode import QVGMEpisodeCollector
from smolvla_qvgm_rlinf.data.collected_episode_adapter import (
    episode_to_trajectory,
    load_collected_episode,
)
from smolvla_qvgm_rlinf.extension import register


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--model-path",
        type=Path,
        default=Path("checkpoints/smolvla_libero_task0/public_recipe_20k/checkpoint-final/pretrained_model"),
    )
    parser.add_argument("--task-id", type=int, default=7)
    parser.add_argument("--candidate-states", default="0,1,2,3,4,5,6,7,8,9")
    parser.add_argument("--minimum-successes", type=int, default=2)
    parser.add_argument("--minimum-failures", type=int, default=2)
    parser.add_argument("--minimum-episodes", type=int, default=4)
    parser.add_argument("--max-steps", type=int, default=240)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--pickle-dir", type=Path, default=Path("data/collected_pickle/task7_20k_smoke"))
    parser.add_argument("--lerobot-dir", type=Path, default=Path("data/collected_lerobot/task7_20k_smoke"))
    parser.add_argument("--replay-dir", type=Path, default=Path("data/replay_buffers/task7_20k_smoke"))
    parser.add_argument("--output", type=Path, default=Path("outputs/phase_7/task7_20k_smoke_metrics.json"))
    return parser.parse_args()


def task_global_reset_id(suite_name: str, task_id: int, local_state_id: int) -> int:
    suite = get_benchmark_overridden(suite_name)()
    counts = [len(suite.get_task_init_states(index)) for index in range(suite.get_num_tasks())]
    if not 0 <= task_id < len(counts):
        raise ValueError(f"task ID {task_id} is outside [0, {len(counts) - 1}]")
    if not 0 <= local_state_id < counts[task_id]:
        raise ValueError(f"state ID {local_state_id} is outside [0, {counts[task_id] - 1}]")
    return sum(counts[:task_id]) + local_state_id


def enrich_pickle(path: Path, records: list[dict], metadata: dict) -> dict:
    episode = load_collected_episode(path)
    if len(records) != len(episode["actions"]):
        raise RuntimeError("policy record count does not match collected action count")
    for info, record in zip(episode["infos"][1:], records, strict=True):
        info.update(record)
    episode["qvgm_metadata"] = metadata
    with path.open("wb") as handle:
        pickle.dump(episode, handle)
    return episode


def main() -> None:
    args = parse_args()
    output_dirs = (args.pickle_dir, args.lerobot_dir, args.replay_dir)
    if any(path.exists() and any(path.iterdir()) for path in output_dirs):
        raise FileExistsError("collection output already exists and is non-empty; choose new output directories")
    for path in output_dirs:
        path.mkdir(parents=True, exist_ok=True)
    args.pickle_dir = args.pickle_dir.resolve()
    args.lerobot_dir = args.lerobot_dir.resolve()
    args.replay_dir = args.replay_dir.resolve()
    args.output.parent.mkdir(parents=True, exist_ok=True)

    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    register()
    model_cfg = OmegaConf.load("configs/rlinf/libero_smolvla_eval.yaml")
    model_cfg.model_path = str(args.model_path.resolve())
    model_cfg.num_action_chunks = 1
    model = get_model(model_cfg)
    model_weights_id = "smolvla_task7_public_recipe_20k_final"

    states = [int(value) for value in args.candidate_states.split(",") if value.strip()]
    collected: list[tuple[Path, dict]] = []
    success_count = 0
    failure_count = 0
    for state_id in states:
        global_reset_id = task_global_reset_id("libero_spatial", args.task_id, state_id)
        env_cfg = OmegaConf.load("configs/rlinf/libero_smolvla_closed_loop.yaml")
        env_cfg.task_id_filter = [args.task_id]
        env_cfg.specific_reset_id = global_reset_id
        env_cfg.max_episode_steps = args.max_steps
        env = LiberoEnv(env_cfg, num_envs=1, seed_offset=0, total_num_processes=1, worker_info=None)
        pickle_collector = CollectEpisode(
            env,
            save_dir=str(args.pickle_dir),
            rank=state_id,
            num_envs=1,
            export_format="pickle",
            only_success=False,
        )
        collector = QVGMEpisodeCollector(
            pickle_collector,
            save_dir=str(args.lerobot_dir),
            rank=state_id,
            num_envs=1,
            export_format="lerobot",
            only_success=False,
            finalize_interval=0,
        )
        policy_records: list[dict] = []
        try:
            observation, _ = collector.reset()
            if int(env.task_ids[0]) != args.task_id or int(env.trial_ids[0]) != state_id:
                raise RuntimeError("LIBERO reset did not select the requested task/state")
            done = False
            step = 0
            while not done and step < args.max_steps:
                noise_seed = args.seed * 1_000_000 + state_id * args.max_steps + step
                generator = torch.Generator(device=next(model.parameters()).device).manual_seed(noise_seed)
                noise = torch.randn(
                    1,
                    model.config.chunk_size,
                    model.config.max_action_dim,
                    generator=generator,
                    device=next(model.parameters()).device,
                    dtype=next(model.parameters()).dtype,
                )
                action, result = model.predict_action_batch(observation, noise=noise)
                executed = action[:, :1]
                observation_steps, _, terminated, truncated, _ = collector.chunk_step(executed)
                forward = result["forward_inputs"]
                policy_records.append(
                    {
                        "policy_checkpoint": str(args.model_path.resolve()),
                        "task_id": args.task_id,
                        "task_language": observation["task_descriptions"][0],
                        "task_reset_state_id": state_id,
                        "global_reset_state_id": global_reset_id,
                        "predicted_action_chunk": forward["predicted_action_chunk"][0].numpy(),
                        "executed_chunk_prefix": executed[0].numpy(),
                        "model_action_before_clip": forward["model_action"][0].numpy(),
                        "initial_noise_seed": noise_seed,
                        "normalization_key": "checkpoint_embedded_mean_std",
                    }
                )
                step += 1
                done = bool(terminated.any() or truncated.any())
                observation = observation_steps[-1]
        finally:
            collector.close()

        matches = sorted(args.pickle_dir.glob(f"rank_{state_id}_*.pkl"))
        if len(matches) != 1:
            raise RuntimeError(f"expected one pickle for state {state_id}, found {len(matches)}")
        metadata = {
            "task_id": args.task_id,
            "task_reset_state_id": state_id,
            "global_reset_state_id": global_reset_id,
            "seed": args.seed,
            "model_weights_id": model_weights_id,
        }
        episode = enrich_pickle(matches[0], policy_records, metadata)
        collected.append((matches[0], episode))
        if episode["success"]:
            success_count += 1
        else:
            failure_count += 1
        if (
            len(collected) >= args.minimum_episodes
            and success_count >= args.minimum_successes
            and failure_count >= args.minimum_failures
        ):
            break

    if success_count < args.minimum_successes or failure_count < args.minimum_failures:
        raise RuntimeError("candidate states did not provide the required success/failure balance")

    replay = TrajectoryReplayBuffer(
        seed=args.seed,
        enable_cache=True,
        cache_size=max(5, len(collected)),
        sample_window_size=len(collected),
        auto_save=True,
        auto_save_path=str(args.replay_dir),
        trajectory_format="pt",
    )
    trajectories = [episode_to_trajectory(ep, model_weights_id=model_weights_id) for _, ep in collected]
    replay.add_trajectories(trajectories)
    replay.close(wait=True)

    reloaded = TrajectoryReplayBuffer(
        seed=args.seed,
        enable_cache=True,
        cache_size=max(5, len(collected)),
        sample_window_size=len(collected),
        auto_save=False,
        trajectory_format="pt",
    )
    reloaded.load_checkpoint(str(args.replay_dir))
    sample = reloaded.sample(num_chunks=min(8, reloaded.get_stats()["total_samples"]))
    metrics = {
        "task_id": args.task_id,
        "model_path": str(args.model_path.resolve()),
        "episodes": len(collected),
        "successes": success_count,
        "failures": failure_count,
        "states": [ep["qvgm_metadata"]["task_reset_state_id"] for _, ep in collected],
        "pickle_files": [str(path.resolve()) for path, _ in collected],
        "lerobot_dir": str(args.lerobot_dir.resolve()),
        "replay_stats": reloaded.get_stats(),
        "sample_shapes": {
            key: list(value.shape) if torch.is_tensor(value) else {
                nested_key: list(nested.shape) for nested_key, nested in value.items()
            }
            for key, value in sample.items()
        },
    }
    args.output.write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
    reloaded.close(wait=True)
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
