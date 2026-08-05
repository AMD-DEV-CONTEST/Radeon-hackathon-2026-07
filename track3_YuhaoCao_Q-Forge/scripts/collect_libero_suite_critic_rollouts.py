#!/usr/bin/env python3
"""Collect an exact, resumable fixed-policy rollout set across a LIBERO suite."""

from __future__ import annotations

import argparse
import json
import os
import pickle
import time
from pathlib import Path
from typing import Any

import numpy as np
import torch
from omegaconf import OmegaConf

from rlinf.envs.libero.libero_env import LiberoEnv
from rlinf.models import get_model
from smolvla_qvgm_rlinf.data.collection_plan import make_suite_plan, parse_states
from smolvla_qvgm_rlinf.extension import register


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite", default="libero_10")
    parser.add_argument("--task-ids", default="0-9")
    parser.add_argument("--states", default="0-29")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--expected-total", type=int, default=300)
    parser.add_argument("--model-path", type=Path, required=True)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/collected_pickle/libero_long_sft_rollouts_300_v1"),
    )
    parser.add_argument("--action-steps", type=int, default=5)
    parser.add_argument("--max-steps", type=int, default=600)
    parser.add_argument("--seed", type=int, default=3000)
    parser.add_argument("--worker-id", type=int, default=0)
    parser.add_argument("--num-workers", type=int, default=1)
    parser.add_argument("--max-new-episodes", type=int)
    return parser.parse_args()


def slice_observation(observation: dict[str, Any]) -> dict[str, Any]:
    output = {}
    for key, value in observation.items():
        if torch.is_tensor(value):
            output[key] = value[0].detach().cpu().clone()
        elif isinstance(value, np.ndarray):
            output[key] = np.array(value[0], copy=True)
        elif isinstance(value, (list, tuple)):
            output[key] = value[0]
        else:
            output[key] = value
    return output


def existing_keys(output_dir: Path) -> set[str]:
    keys = set()
    for path in output_dir.glob("*.pkl"):
        try:
            with path.open("rb") as handle:
                episode = pickle.load(handle)
            key = episode.get("qvgm_metadata", {}).get("collection_key")
            if key:
                keys.add(str(key))
        except (OSError, EOFError, pickle.UnpicklingError):
            continue
    return keys


def task_offsets(env: LiberoEnv) -> list[int]:
    counts = [int(value) for value in env.trial_id_bins]
    return [sum(counts[:task_id]) for task_id in range(len(counts))]


def save_episode(output_dir: Path, key: str, episode: dict[str, Any]) -> Path:
    label = "success" if episode["success"] else "fail"
    path = output_dir / f"{key}_steps_{len(episode['actions']):03d}_{label}.pkl"
    temporary = path.with_suffix(".pkl.tmp")
    with temporary.open("wb") as handle:
        pickle.dump(episode, handle)
    temporary.replace(path)
    return path


def main() -> None:
    args = parse_args()
    task_ids, states = parse_states(args.task_ids), parse_states(args.states)
    full_plan = make_suite_plan(task_ids, states, repeats=args.repeats)
    if len(full_plan) != args.expected_total:
        raise ValueError(
            f"collection plan has {len(full_plan)} episodes, expected {args.expected_total}"
        )
    if args.action_steps <= 0 or args.max_steps <= 0:
        raise ValueError("action-steps and max-steps must be positive")
    if not 0 <= args.worker_id < args.num_workers:
        raise ValueError("worker-id must be in [0,num-workers)")

    os.environ.setdefault("MUJOCO_GL", "egl")
    os.environ.setdefault("PYOPENGL_PLATFORM", "egl")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    completed = existing_keys(args.output_dir)
    worker_plan = [
        item for index, item in enumerate(full_plan)
        if index % args.num_workers == args.worker_id
    ]
    pending = [item for item in worker_plan if item.key not in completed]
    if args.max_new_episodes is not None:
        pending = pending[: args.max_new_episodes]

    register()
    model_cfg = OmegaConf.load("configs/rlinf/libero_smolvla_eval.yaml")
    model_cfg.model_path = str(args.model_path.resolve())
    model_cfg.num_action_chunks = args.action_steps
    model = get_model(model_cfg)

    env_cfg = OmegaConf.load("configs/rlinf/libero_smolvla_closed_loop.yaml")
    env_cfg.task_suite_name = args.suite
    env_cfg.task_id_filter = task_ids
    env_cfg.specific_reset_id = None
    env_cfg.max_episode_steps = args.max_steps
    env = LiberoEnv(
        env_cfg, num_envs=1, seed_offset=0, total_num_processes=1, worker_info=None
    )
    offsets = task_offsets(env)
    started = time.perf_counter()
    new_records = []
    try:
        for item in pending:
            global_state_id = offsets[item.task_id] + item.state_id
            observation, _ = env.reset(reset_state_ids=np.array([global_state_id]))
            if (int(env.task_ids[0]), int(env.trial_ids[0])) != (
                item.task_id,
                item.state_id,
            ):
                observation, _ = env.reset(reset_state_ids=np.array([global_state_id]))
            if (int(env.task_ids[0]), int(env.trial_ids[0])) != (
                item.task_id,
                item.state_id,
            ):
                raise RuntimeError(f"reset mismatch for {item.key}")

            task_language = str(observation["task_descriptions"][0])
            observations = [slice_observation(observation)]
            actions: list[torch.Tensor] = []
            rewards: list[float] = [0.0]
            terminated_values: list[bool] = [False]
            truncated_values: list[bool] = [False]
            infos: list[dict[str, Any]] = [{}]
            done, step = False, 0
            while not done and step < args.max_steps:
                noise_seed = (
                    args.seed * 10**10
                    + item.task_id * 10**8
                    + item.state_id * 10**6
                    + item.repeat_id * 10**4
                    + step
                )
                generator = torch.Generator(device="cuda").manual_seed(noise_seed)
                noise = torch.randn(
                    1,
                    model.config.chunk_size,
                    model.config.max_action_dim,
                    generator=generator,
                    device="cuda",
                    dtype=next(model.parameters()).dtype,
                )
                predicted_action, result = model.predict_action_batch(
                    observation, noise=noise
                )
                executed = predicted_action[:, : args.action_steps].clamp(-1.0, 1.0)
                executed = executed[:, : args.max_steps - step]
                observation_steps, step_rewards, terminations, truncations, _ = (
                    env.chunk_step(executed)
                )
                predicted_chunk = result["forward_inputs"]["predicted_action_chunk"][0]
                for chunk_offset in range(executed.shape[1]):
                    terminated = bool(terminations[0, chunk_offset])
                    truncated = bool(truncations[0, chunk_offset])
                    actions.append(executed[0, chunk_offset].cpu())
                    rewards.append(float(step_rewards[0, chunk_offset]))
                    terminated_values.append(terminated)
                    truncated_values.append(truncated)
                    infos.append(
                        {
                            "policy_checkpoint": str(args.model_path.resolve()),
                            "suite": args.suite,
                            "task_id": item.task_id,
                            "task_language": task_language,
                            "task_reset_state_id": item.state_id,
                            "global_reset_state_id": global_state_id,
                            "collection_key": item.key,
                            "predicted_action_chunk": predicted_chunk[chunk_offset:].numpy(),
                            "executed_chunk_prefix": executed[0].numpy(),
                            "initial_noise_seed": noise_seed,
                            "chunk_offset": chunk_offset,
                        }
                    )
                    observations.append(slice_observation(observation_steps[chunk_offset]))
                    step += 1
                    if terminated or truncated:
                        done = True
                        break
                observation = observation_steps[min(executed.shape[1], chunk_offset + 1) - 1]

            episode = {
                "rank": args.worker_id,
                "env_idx": 0,
                "episode_id": item.repeat_id,
                "step": len(actions),
                "success": bool(env.success_once[0]),
                "observations": observations,
                "actions": actions,
                "rewards": rewards,
                "terminated": terminated_values,
                "truncated": truncated_values,
                "infos": infos,
                "qvgm_metadata": {
                    "collection_key": item.key,
                    "suite": args.suite,
                    "task_id": item.task_id,
                    "task_language": task_language,
                    "task_reset_state_id": item.state_id,
                    "global_reset_state_id": global_state_id,
                    "repeat_id": item.repeat_id,
                    "seed": args.seed,
                    "worker_id": args.worker_id,
                    "action_steps_per_replan": args.action_steps,
                    "perturb_probability": 0.0,
                    "model_weights_id": "smolvla_libero_long_public_recipe_20k_final",
                },
            }
            path = save_episode(args.output_dir, item.key, episode)
            record = {
                "key": item.key,
                "task_id": item.task_id,
                "state_id": item.state_id,
                "success": episode["success"],
                "steps": len(actions),
                "path": str(path.resolve()),
            }
            new_records.append(record)
            print(json.dumps(record), flush=True)
    finally:
        env.env.close()

    all_completed = existing_keys(args.output_dir)
    summary = {
        "suite": args.suite,
        "expected_total": args.expected_total,
        "full_plan_episodes": len(full_plan),
        "completed_total": len(all_completed),
        "worker_id": args.worker_id,
        "num_workers": args.num_workers,
        "planned_for_worker": len(worker_plan),
        "new_episodes": len(new_records),
        "new_successes": sum(record["success"] for record in new_records),
        "new_failures": sum(not record["success"] for record in new_records),
        "elapsed_seconds": time.perf_counter() - started,
        "complete": len(all_completed) == args.expected_total,
    }
    (args.output_dir / f"worker_{args.worker_id}_latest_summary.json").write_text(
        json.dumps(summary, indent=2) + "\n"
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
