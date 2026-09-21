#!/usr/bin/env python3
"""Collect resumable task-7 rollouts with controlled first-action perturbations."""

from __future__ import annotations

import argparse
import json
import os
import pickle
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np
import torch
from omegaconf import OmegaConf

from rlinf.envs.libero.libero_env import LiberoEnv
from rlinf.models import get_model
from smolvla_qvgm_rlinf.extension import register
from smolvla_qvgm_rlinf.data.collection_plan import CollectionItem, make_plan, parse_states


DEFAULT_FAILURE_STATES = (0, 3, 7, 9, 13, 15, 17, 18, 24, 31, 36, 39, 41)
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--model-path",
        type=Path,
        default=Path("checkpoints/smolvla_libero_task0/public_recipe_20k/checkpoint-final/pretrained_model"),
    )
    parser.add_argument("--output-dir", type=Path, default=Path("data/collected_pickle/task7_critic_diverse_v1"))
    parser.add_argument("--states", default="0-39")
    parser.add_argument("--failure-states", default=",".join(map(str, DEFAULT_FAILURE_STATES)))
    parser.add_argument("--perturb-probability", type=float, default=0.5)
    parser.add_argument(
        "--action-steps",
        type=int,
        default=5,
        help="Execute this many consecutive actions from each SFT-policy chunk.",
    )
    parser.add_argument("--max-steps", type=int, default=240)
    parser.add_argument("--seed", type=int, default=2026)
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


def save_episode(output_dir: Path, item: CollectionItem, episode: dict[str, Any]) -> Path:
    label = "success" if episode["success"] else "fail"
    path = output_dir / f"{item.key}_steps_{len(episode['actions']):03d}_{label}.pkl"
    temporary = path.with_suffix(".pkl.tmp")
    with temporary.open("wb") as handle:
        pickle.dump(episode, handle)
    temporary.replace(path)
    return path


def main() -> None:
    args = parse_args()
    if not 0.0 <= args.perturb_probability <= 1.0:
        raise ValueError("perturb probability must be in [0,1]")
    if args.action_steps <= 0:
        raise ValueError("action-steps must be positive")
    if not 0 <= args.worker_id < args.num_workers:
        raise ValueError("worker-id must be in [0,num-workers)")
    os.environ.setdefault("MUJOCO_GL", "egl")
    os.environ.setdefault("PYOPENGL_PLATFORM", "egl")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    failure_states = set(parse_states(args.failure_states))
    full_plan = make_plan(parse_states(args.states), failure_states)
    plan = [item for index, item in enumerate(full_plan) if index % args.num_workers == args.worker_id]
    completed = existing_keys(args.output_dir)
    pending = [item for item in plan if item.key not in completed]
    if args.max_new_episodes is not None:
        pending = pending[: args.max_new_episodes]

    register()
    model_cfg = OmegaConf.load("configs/rlinf/libero_smolvla_eval.yaml")
    model_cfg.model_path = str(args.model_path.resolve())
    model_cfg.num_action_chunks = args.action_steps
    model = get_model(model_cfg)
    env_cfg = OmegaConf.load("configs/rlinf/libero_smolvla_closed_loop.yaml")
    env_cfg.task_id_filter = [7]
    env_cfg.specific_reset_id = None
    env_cfg.max_episode_steps = args.max_steps
    # Each CLI worker owns an independent one-process LiberoEnv. worker_id is
    # already encoded in the sharded collection plan and explicit rollout
    # seeds; RLinf's seed_offset is a process-array index and must remain zero.
    env = LiberoEnv(env_cfg, num_envs=1, seed_offset=0, total_num_processes=1, worker_info=None)
    started = time.perf_counter()
    new_records = []
    try:
        for item in pending:
            global_state_id = 350 + item.state_id
            observation, _ = env.reset(reset_state_ids=np.array([global_state_id]))
            if (int(env.task_ids[0]), int(env.trial_ids[0])) != (7, item.state_id):
                observation, _ = env.reset(reset_state_ids=np.array([global_state_id]))
            if (int(env.task_ids[0]), int(env.trial_ids[0])) != (7, item.state_id):
                raise RuntimeError(f"reset mismatch for {item.key}")

            observations = [slice_observation(observation)]
            actions: list[torch.Tensor] = []
            rewards: list[float] = [0.0]
            terminated_values: list[bool] = [False]
            truncated_values: list[bool] = [False]
            infos: list[dict[str, Any]] = [{}]
            done = False
            step = 0
            while not done and step < args.max_steps:
                seed_base = args.seed * 10**9 + item.state_id * 10**6 + item.repeat_id * 10**4 + step
                flow_generator = torch.Generator(device="cuda").manual_seed(seed_base)
                flow_noise = torch.randn(
                    1,
                    model.config.chunk_size,
                    model.config.max_action_dim,
                    generator=flow_generator,
                    device="cuda",
                    dtype=next(model.parameters()).dtype,
                )
                base_action, result = model.predict_action_batch(observation, noise=flow_noise)
                base_prefix = base_action[:, : args.action_steps].clone()
                perturb_generator = torch.Generator(device="cpu").manual_seed(seed_base + 1)
                apply_perturbation = bool(
                    item.sigma > 0
                    and torch.rand((), generator=perturb_generator).item() < args.perturb_probability
                )
                perturbation = torch.zeros_like(base_prefix)
                if apply_perturbation:
                    perturbation[..., :6] = (
                        torch.randn(
                            (1, base_prefix.shape[1], 6), generator=perturb_generator
                        )
                        * item.sigma
                    )
                executed = (base_prefix + perturbation).clamp(-1.0, 1.0)
                remaining = args.max_steps - step
                executed = executed[:, :remaining]
                observation_steps, step_rewards, terminations, truncations, step_infos = env.chunk_step(executed)
                forward = result["forward_inputs"]
                predicted = forward["predicted_action_chunk"][0].numpy()
                for chunk_offset in range(executed.shape[1]):
                    terminated = bool(terminations[0, chunk_offset])
                    truncated = bool(truncations[0, chunk_offset])
                    reward = float(step_rewards[0, chunk_offset])
                    info = {
                        "policy_checkpoint": str(args.model_path.resolve()),
                        "task_id": 7,
                        "task_reset_state_id": item.state_id,
                        "global_reset_state_id": global_state_id,
                        "collection_key": item.key,
                        "predicted_action_chunk": predicted[chunk_offset:],
                        "base_executed_action": base_prefix[0, chunk_offset].numpy(),
                        "executed_chunk_prefix": executed[0].numpy(),
                        "action_perturbation": perturbation[0, chunk_offset].numpy(),
                        "perturbation_sigma": item.sigma,
                        "perturbation_applied": apply_perturbation,
                        "initial_noise_seed": seed_base,
                        "perturbation_seed": seed_base + 1,
                        "chunk_offset": chunk_offset,
                    }
                    actions.append(executed[0, chunk_offset].cpu())
                    rewards.append(reward)
                    terminated_values.append(terminated)
                    truncated_values.append(truncated)
                    infos.append(info)
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
                    **asdict(item),
                    "collection_key": item.key,
                    "task_id": 7,
                    "global_reset_state_id": global_state_id,
                    "seed": args.seed,
                    "worker_id": args.worker_id,
                    "perturb_probability": args.perturb_probability,
                    "action_steps_per_replan": args.action_steps,
                    "model_weights_id": "smolvla_task7_public_recipe_20k_final",
                },
            }
            path = save_episode(args.output_dir, item, episode)
            record = {
                "key": item.key,
                "state": item.state_id,
                "sigma": item.sigma,
                "success": episode["success"],
                "steps": len(actions),
                "path": str(path.resolve()),
            }
            new_records.append(record)
            print(json.dumps(record), flush=True)
    finally:
        env.env.close()

    summary = {
        "worker_id": args.worker_id,
        "num_workers": args.num_workers,
        "planned_for_worker": len(plan),
        "already_complete": len(completed),
        "new_episodes": len(new_records),
        "new_successes": sum(record["success"] for record in new_records),
        "new_failures": sum(not record["success"] for record in new_records),
        "elapsed_seconds": time.perf_counter() - started,
    }
    summary_path = args.output_dir / f"worker_{args.worker_id}_latest_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
