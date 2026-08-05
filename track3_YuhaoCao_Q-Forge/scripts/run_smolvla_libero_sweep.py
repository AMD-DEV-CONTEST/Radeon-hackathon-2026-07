#!/usr/bin/env python3
"""Run a resumable multi-state, multi-seed SmolVLA/Q-guidance sweep."""

from __future__ import annotations

import argparse
import json
import math
import os
import time
from pathlib import Path

import numpy as np
import torch
from omegaconf import OmegaConf

from rlinf.envs.libero.libero_env import LiberoEnv
from rlinf.models import get_model
from smolvla_qvgm_rlinf.data.collection_plan import parse_states
from smolvla_qvgm_rlinf.extension import register
from smolvla_qvgm_rlinf.models.prefix_features import (
    FrozenSmolVLAPrefixExtractor,
    load_rlt_extractor,
)
from smolvla_qvgm_rlinf.models.q_guidance import QGuidanceConfig, guide_action_chunk
from smolvla_qvgm_rlinf.models.q_selection import (
    repeat_policy_batch,
    select_best_action_chunk,
)
from smolvla_qvgm_rlinf.models.qvgm_critic import QVGMCriticConfig, QVGMCriticEnsemble


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--states", default="0-49")
    parser.add_argument("--seeds", default="2001,2002")
    parser.add_argument("--task-id", type=int, default=7)
    parser.add_argument(
        "--task-suite",
        default="libero_spatial",
        help="LIBERO benchmark suite name, for example libero_spatial or libero_10.",
    )
    parser.add_argument("--max-steps", type=int, default=240)
    parser.add_argument(
        "--action-steps",
        type=int,
        default=5,
        help="Execute this many actions from each predicted/guided chunk before replanning.",
    )
    parser.add_argument("--model-path", type=Path, required=True)
    parser.add_argument("--critic-checkpoint", type=Path)
    parser.add_argument(
        "--critic-mode",
        choices=("guidance", "selection"),
        default="guidance",
        help="How to use a provided critic. Ignored when no critic is provided.",
    )
    parser.add_argument(
        "--feature-extractor-checkpoint",
        type=Path,
        help="Trained RLT feature extractor required by paper-aligned critics.",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--guidance-steps", type=int, default=10)
    parser.add_argument("--guidance-step-size", type=float, default=0.02)
    parser.add_argument("--guidance-max-delta", type=float, default=0.05)
    parser.add_argument("--guidance-optimize-prefix-steps", type=int, default=5)
    parser.add_argument("--guidance-optimize-action-dims", type=int, default=7)
    parser.add_argument(
        "--selection-candidates",
        type=int,
        default=4,
        help="Number of independently sampled policy chunks for test-time Q selection.",
    )
    return parser.parse_args()


def metrics_path(output_dir: Path, seed: int, state_id: int) -> Path:
    return output_dir / f"seed_{seed}" / f"reset_{state_id}" / "closed_loop_metrics.json"


def main() -> None:
    args = parse_args()
    states = parse_states(args.states)
    seeds = parse_states(args.seeds)
    if not states or not seeds:
        raise ValueError("states and seeds must be non-empty")
    if args.action_steps <= 0:
        raise ValueError("action-steps must be positive")
    if args.critic_checkpoint is not None and args.critic_mode == "selection":
        if args.selection_candidates < 2:
            raise ValueError("selection-candidates must be at least two")
    os.environ.setdefault("MUJOCO_GL", "egl")
    os.environ.setdefault("PYOPENGL_PLATFORM", "egl")
    args.output_dir.mkdir(parents=True, exist_ok=True)

    register()
    model_cfg = OmegaConf.load("configs/rlinf/libero_smolvla_eval.yaml")
    model_cfg.model_path = str(args.model_path.resolve())
    model_cfg.num_action_chunks = args.action_steps
    model = get_model(model_cfg)

    critic = None
    feature_extractor = None
    if args.critic_checkpoint is not None:
        payload = torch.load(args.critic_checkpoint, map_location="cuda", weights_only=True)
        critic = QVGMCriticEnsemble(QVGMCriticConfig(**payload["config"])).cuda().eval()
        critic.load_state_dict(payload["model"])
        feature_extractor = (
            load_rlt_extractor(model.policy, args.feature_extractor_checkpoint, device="cuda")
            if args.feature_extractor_checkpoint is not None
            else FrozenSmolVLAPrefixExtractor(model.policy).cuda().eval()
        )
    guidance_config = QGuidanceConfig(
        steps=args.guidance_steps,
        step_size=args.guidance_step_size,
        max_delta=args.guidance_max_delta,
        optimize_prefix_steps=args.guidance_optimize_prefix_steps,
        optimize_action_dims=args.guidance_optimize_action_dims,
    )

    env_cfg = OmegaConf.load("configs/rlinf/libero_smolvla_closed_loop.yaml")
    env_cfg.task_suite_name = args.task_suite
    env_cfg.max_episode_steps = args.max_steps
    env_cfg.task_id_filter = [args.task_id]
    env_cfg.specific_reset_id = None
    env = LiberoEnv(
        env_cfg,
        num_envs=1,
        seed_offset=0,
        total_num_processes=1,
        worker_info=None,
    )
    trial_offset = int(sum(env.trial_id_bins[: args.task_id]))
    records = []
    try:
        for seed in seeds:
            for state_id in states:
                output_path = metrics_path(args.output_dir, seed, state_id)
                if output_path.exists():
                    record = json.loads(output_path.read_text())
                    records.append(record)
                    print(json.dumps({"resumed": True, **record}), flush=True)
                    continue

                torch.manual_seed(seed)
                torch.cuda.manual_seed_all(seed)
                np.random.seed(seed)
                model.policy.reset()
                global_state_id = trial_offset + state_id
                observation, _ = env.reset(reset_state_ids=np.array([global_state_id]))
                if (int(env.task_ids[0]), int(env.trial_ids[0])) != (args.task_id, state_id):
                    observation, _ = env.reset(reset_state_ids=np.array([global_state_id]))
                if (int(env.task_ids[0]), int(env.trial_ids[0])) != (args.task_id, state_id):
                    raise RuntimeError(f"reset mismatch for task/state {args.task_id}/{state_id}")

                started = time.perf_counter()
                done = False
                steps = 0
                q_improvements = []
                action_deltas = []
                selection_indices = []
                selection_q_improvements = []
                selection_q_stds = []
                selection_disagreements = []
                action_min = float("inf")
                action_max = float("-inf")
                gripper_min = float("inf")
                gripper_max = float("-inf")
                all_finite = True
                while not done and steps < args.max_steps:
                    if critic is None:
                        base_chunk, _ = model.predict_action_batch(observation)
                        action = base_chunk[:, : args.action_steps].cpu()
                    elif args.critic_mode == "guidance":
                        _, result = model.predict_action_batch(observation)
                        prepared = model._prepare_rollout_batch(observation)
                        with torch.inference_mode(), torch.autocast("cuda", dtype=torch.bfloat16):
                            z_state = feature_extractor(prepared)
                        reference = (
                            result["forward_inputs"]["predicted_action_chunk"][:, : critic.config.horizon]
                            .cuda()
                            .clamp(-1.0, 1.0)
                        )
                        action_mask = torch.ones(
                            reference.shape[:2], dtype=torch.bool, device=reference.device
                        )
                        guided, info = guide_action_chunk(
                            critic,
                            z_state,
                            prepared["observation.state"],
                            reference,
                            action_mask,
                            guidance_config,
                        )
                        action = guided[:, : args.action_steps].cpu()
                        q_improvements.append((info["best_q"] - info["base_q"]).item())
                        action_deltas.append((guided - reference).abs().mean().item())
                    else:
                        prepared = model._prepare_rollout_batch(observation)
                        with torch.inference_mode(), torch.autocast(
                            "cuda", dtype=torch.bfloat16
                        ):
                            z_state = feature_extractor(prepared)
                            repeated = repeat_policy_batch(
                                prepared, args.selection_candidates
                            )
                            sampled = model.sample_predicted_action_chunk(repeated)
                        batch_size = prepared["observation.state"].shape[0]
                        candidates = (
                            sampled[
                                :, : critic.config.horizon, : critic.config.action_dim
                            ]
                            .reshape(
                                batch_size,
                                args.selection_candidates,
                                critic.config.horizon,
                                critic.config.action_dim,
                            )
                            .float()
                            .clamp(-1.0, 1.0)
                        )
                        selected, info = select_best_action_chunk(
                            critic,
                            z_state,
                            prepared["observation.state"],
                            candidates,
                        )
                        action = selected[:, : args.action_steps].cpu()
                        selection_indices.extend(info["selected_index"].cpu().tolist())
                        selection_q_improvements.extend(
                            (info["selected_q"] - info["first_candidate_q"])
                            .cpu()
                            .tolist()
                        )
                        selection_q_stds.extend(info["candidate_q_std"].cpu().tolist())
                        selection_disagreements.extend(
                            info["selected_disagreement"].cpu().tolist()
                        )
                    remaining = args.max_steps - steps
                    action = action[:, :remaining]
                    array = action[0].numpy()
                    all_finite = all_finite and bool(np.isfinite(array).all())
                    action_min = min(action_min, float(array.min()))
                    action_max = max(action_max, float(array.max()))
                    gripper_min = min(gripper_min, float(array[..., -1].min()))
                    gripper_max = max(gripper_max, float(array[..., -1].max()))
                    observation_steps, _, terminated, truncated, _ = env.chunk_step(action)
                    done_indices = np.flatnonzero(
                        np.asarray(terminated[0], dtype=bool)
                        | np.asarray(truncated[0], dtype=bool)
                    )
                    executed = int(done_indices[0]) + 1 if len(done_indices) else action.shape[1]
                    steps += executed
                    done = bool(len(done_indices))
                    observation = observation_steps[executed - 1]

                record = {
                    "suite": args.task_suite,
                    "task_id": args.task_id,
                    "task_reset_state_id": state_id,
                    "global_reset_state_id": global_state_id,
                    "seed": seed,
                    "seed_protocol": "reseed_before_each_episode",
                    "model_path": str(args.model_path.resolve()),
                    "critic_checkpoint": (
                        str(args.critic_checkpoint.resolve()) if args.critic_checkpoint else None
                    ),
                    "feature_extractor_checkpoint": (
                        str(args.feature_extractor_checkpoint.resolve())
                        if args.feature_extractor_checkpoint
                        else None
                    ),
                    "critic_mode": (
                        args.critic_mode if critic is not None else "none"
                    ),
                    "guidance_enabled": (
                        critic is not None and args.critic_mode == "guidance"
                    ),
                    "q_selection_enabled": (
                        critic is not None and args.critic_mode == "selection"
                    ),
                    "action_steps_per_replan": args.action_steps,
                    "max_steps": args.max_steps,
                    "steps": steps,
                    "success": bool(env.success_once[0]),
                    "terminated": bool(terminated[0, 0]),
                    "truncated": bool(truncated[0, 0]),
                    "action_finite": all_finite,
                    "action_min": action_min,
                    "action_max": action_max,
                    "gripper_min": gripper_min,
                    "gripper_max": gripper_max,
                    "guidance": (
                        {
                            "steps": guidance_config.steps,
                            "step_size": guidance_config.step_size,
                            "max_delta": guidance_config.max_delta,
                            "optimize_prefix_steps": guidance_config.optimize_prefix_steps,
                            "optimize_action_dims": guidance_config.optimize_action_dims,
                        }
                        if critic is not None and args.critic_mode == "guidance"
                        else None
                    ),
                    "guidance_q_improvement_mean": (
                        float(np.mean(q_improvements)) if q_improvements else None
                    ),
                    "guidance_delta_abs_mean": (
                        float(np.mean(action_deltas)) if action_deltas else None
                    ),
                    "selection": (
                        {
                            "candidate_count": args.selection_candidates,
                            "aggregation": "ensemble_mean",
                            "action_gradient": False,
                        }
                        if critic is not None and args.critic_mode == "selection"
                        else None
                    ),
                    "selection_selected_index_histogram": (
                        {
                            str(index): int(selection_indices.count(index))
                            for index in sorted(set(selection_indices))
                        }
                        if selection_indices
                        else None
                    ),
                    "selection_q_improvement_over_first_mean": (
                        float(np.mean(selection_q_improvements))
                        if selection_q_improvements
                        else None
                    ),
                    "selection_candidate_q_std_mean": (
                        float(np.mean(selection_q_stds)) if selection_q_stds else None
                    ),
                    "selection_selected_disagreement_mean": (
                        float(np.mean(selection_disagreements))
                        if selection_disagreements
                        else None
                    ),
                    "elapsed_seconds": time.perf_counter() - started,
                }
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text(json.dumps(record, indent=2) + "\n")
                records.append(record)
                print(json.dumps(record), flush=True)
    finally:
        env.env.close()

    successes = [record for record in records if record["success"]]
    success_count = len(successes)
    episode_count = len(records)
    success_rate = success_count / episode_count
    # Wilson score interval is well behaved for finite rollout counts, including
    # the all-success and all-failure cases where a normal approximation is not.
    z = 1.959963984540054
    denominator = 1.0 + z * z / episode_count
    center = (success_rate + z * z / (2.0 * episode_count)) / denominator
    margin = (
        z
        * math.sqrt(
            success_rate * (1.0 - success_rate) / episode_count
            + z * z / (4.0 * episode_count * episode_count)
        )
        / denominator
    )
    successful_steps = [record["steps"] for record in successes]

    summary = {
        "suite": args.task_suite,
        "task_id": args.task_id,
        "episodes": episode_count,
        "states": states,
        "seeds": seeds,
        "successes": success_count,
        "success_rate": success_rate,
        "success_rate_wilson_95": {
            "lower": max(0.0, center - margin),
            "upper": min(1.0, center + margin),
        },
        "failures": [
            {"state": record["task_reset_state_id"], "seed": record["seed"]}
            for record in records
            if not record["success"]
        ],
        "mean_steps": float(np.mean([record["steps"] for record in records])),
        "mean_successful_steps": (
            float(np.mean(successful_steps)) if successful_steps else None
        ),
        "median_successful_steps": (
            float(np.median(successful_steps)) if successful_steps else None
        ),
        "all_actions_finite": all(record["action_finite"] for record in records),
        "critic_mode": (
            args.critic_mode if args.critic_checkpoint is not None else "none"
        ),
        "selection_candidates": (
            args.selection_candidates
            if args.critic_checkpoint is not None and args.critic_mode == "selection"
            else None
        ),
    }
    (args.output_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
