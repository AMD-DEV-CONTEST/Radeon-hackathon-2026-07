#!/usr/bin/env python3
"""Run and record one deterministic SmolVLA episode in RLinf LIBERO."""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

import imageio.v2 as imageio
import numpy as np
import torch
from omegaconf import OmegaConf

from rlinf.envs.libero.libero_env import LiberoEnv
from rlinf.models import get_model
from smolvla_qvgm_rlinf.extension import register
from smolvla_qvgm_rlinf.models.prefix_features import (
    FrozenSmolVLAPrefixExtractor,
    load_rlt_extractor,
)
from smolvla_qvgm_rlinf.models.q_guidance import QGuidanceConfig, guide_action_chunk
from smolvla_qvgm_rlinf.models.qvgm_critic import QVGMCriticConfig, QVGMCriticEnsemble


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-steps", type=int, default=240)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--task-id", type=int, default=0)
    parser.add_argument(
        "--task-reset-state-id",
        type=int,
        default=0,
        help="Reset state index local to --task-id.",
    )
    parser.add_argument("--critic-checkpoint", type=Path)
    parser.add_argument("--feature-extractor-checkpoint", type=Path)
    parser.add_argument("--guidance-steps", type=int, default=20)
    parser.add_argument("--guidance-step-size", type=float, default=0.05)
    parser.add_argument("--guidance-max-delta", type=float, default=0.2)
    parser.add_argument("--guidance-optimize-prefix-steps", type=int)
    parser.add_argument(
        "--guidance-optimize-action-dims",
        type=int,
        help="Only optimize the first N action dimensions (use 6 to preserve gripper).",
    )
    parser.add_argument("--no-video", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/phase_5"))
    parser.add_argument("--model-path", type=Path)
    parser.add_argument(
        "--action-steps",
        type=int,
        default=None,
        help="Number of predicted actions to execute before replanning.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    os.environ.setdefault("MUJOCO_GL", "egl")
    os.environ.setdefault("PYOPENGL_PLATFORM", "egl")
    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    register()
    model_cfg = OmegaConf.load("configs/rlinf/libero_smolvla_eval.yaml")
    if args.model_path is not None:
        model_cfg.model_path = str(args.model_path.resolve())
    if args.action_steps is not None:
        model_cfg.num_action_chunks = args.action_steps
    model = get_model(model_cfg)
    critic = None
    feature_extractor = None
    if args.critic_checkpoint is not None:
        # Critic construction initializes parameters. Preserve RNG state so
        # SmolVLA flow noise remains paired with the unguided seed protocol.
        cpu_rng_state = torch.random.get_rng_state()
        cuda_rng_state = torch.cuda.get_rng_state_all()
        critic_payload = torch.load(
            args.critic_checkpoint, map_location="cuda", weights_only=True
        )
        critic = QVGMCriticEnsemble(
            QVGMCriticConfig(**critic_payload["config"])
        ).cuda().eval()
        critic.load_state_dict(critic_payload["model"])
        feature_extractor = (
            load_rlt_extractor(model.policy, args.feature_extractor_checkpoint, device="cuda")
            if args.feature_extractor_checkpoint is not None
            else FrozenSmolVLAPrefixExtractor(model.policy).cuda().eval()
        )
        torch.random.set_rng_state(cpu_rng_state)
        torch.cuda.set_rng_state_all(cuda_rng_state)
    env_cfg = OmegaConf.load("configs/rlinf/libero_smolvla_closed_loop.yaml")
    env_cfg.max_episode_steps = args.max_steps
    env_cfg.task_id_filter = [args.task_id]
    # A configured global reset ID overrides task_id_filter during the first
    # reset. Disable it and pass the requested task-local state explicitly.
    env_cfg.specific_reset_id = None
    env = LiberoEnv(env_cfg, num_envs=1, seed_offset=0, total_num_processes=1, worker_info=None)
    frames: list[np.ndarray] = []
    actions_seen: list[np.ndarray] = []
    started = time.perf_counter()
    try:
        if not 0 <= args.task_id < len(env.trial_id_bins):
            raise ValueError(f"task ID {args.task_id} is outside [0, {len(env.trial_id_bins) - 1}]")
        task_trial_count = int(env.trial_id_bins[args.task_id])
        if not 0 <= args.task_reset_state_id < task_trial_count:
            raise ValueError(
                f"task reset state ID {args.task_reset_state_id} is outside "
                f"[0, {task_trial_count - 1}] for task {args.task_id}"
            )
        global_reset_state_id = int(sum(env.trial_id_bins[: args.task_id])) + args.task_reset_state_id
        observation, _ = env.reset(reset_state_ids=np.array([global_reset_state_id]))
        actual_task_id = int(env.task_ids[0])
        actual_trial_id = int(env.trial_ids[0])
        # LiberoEnv intentionally replaces the caller's reset IDs during its
        # first reset. If the requested state is not the filtered pool's first
        # state, reset once more now that environment initialization is done.
        if (actual_task_id, actual_trial_id) != (args.task_id, args.task_reset_state_id):
            observation, _ = env.reset(reset_state_ids=np.array([global_reset_state_id]))
            actual_task_id = int(env.task_ids[0])
            actual_trial_id = int(env.trial_ids[0])
        if (actual_task_id, actual_trial_id) != (args.task_id, args.task_reset_state_id):
            raise RuntimeError(
                "LIBERO reset mismatch: requested "
                f"task/state {args.task_id}/{args.task_reset_state_id}, got "
                f"{actual_task_id}/{actual_trial_id}"
            )
        frames.append(observation["main_images"][0].cpu().numpy())

        # Compare an explicit-noise native LeRobot call with the adapter call.
        # This diagnostic must not consume the rollout RNG stream: the paired
        # sweep reseeds immediately before each episode and performs no such
        # probe. Preserve and restore all RNGs so recorded episodes reproduce
        # the exact sweep protocol.
        cpu_rng_state = torch.random.get_rng_state()
        cuda_rng_state = torch.cuda.get_rng_state_all()
        numpy_rng_state = np.random.get_state()
        prepared = model._prepare_rollout_batch(observation)
        noise = torch.randn(
            1,
            model.config.chunk_size,
            model.config.max_action_dim,
            device=next(model.parameters()).device,
            dtype=next(model.parameters()).dtype,
        )
        model.policy.reset()
        with torch.autocast("cuda", dtype=torch.bfloat16):
            native = model.policy.select_action(dict(prepared), noise=noise.clone()).float().cpu()
        model.policy.reset()
        adapter_chunk, _ = model.predict_action_batch(observation, noise=noise.clone())
        native_executable = native.clamp(-1.0, 1.0) if model.clip_actions else native
        native_adapter_max_error = float(
            (native_executable - adapter_chunk[:, 0]).abs().max()
        )
        torch.random.set_rng_state(cpu_rng_state)
        torch.cuda.set_rng_state_all(cuda_rng_state)
        np.random.set_state(numpy_rng_state)
        model.policy.reset()

        done = False
        guidance_records = []
        while not done and len(actions_seen) < args.max_steps:
            chunk, result = model.predict_action_batch(observation)
            if critic is not None:
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
                guided, guidance_info = guide_action_chunk(
                    critic,
                    z_state,
                    prepared["observation.state"],
                    reference,
                    action_mask,
                    QGuidanceConfig(
                        steps=args.guidance_steps,
                        step_size=args.guidance_step_size,
                        max_delta=args.guidance_max_delta,
                        optimize_prefix_steps=args.guidance_optimize_prefix_steps,
                        optimize_action_dims=args.guidance_optimize_action_dims,
                    ),
                )
                guidance_records.append(
                    {
                        "q_base": guidance_info["base_q"].item(),
                        "q_guided": guidance_info["best_q"].item(),
                        "delta_abs_mean": (guided - reference).abs().mean().item(),
                    }
                )
                chunk = guided[:, : int(model_cfg.num_action_chunks)].cpu()
            remaining = args.max_steps - len(actions_seen)
            chunk = chunk[:, :remaining]
            observation_steps, rewards, terminated, truncated, infos = env.chunk_step(chunk)
            executed = 0
            for index in range(chunk.shape[1]):
                actions_seen.append(chunk[0, index].numpy())
                frames.append(observation_steps[index]["main_images"][0].cpu().numpy())
                executed = index + 1
                if bool(terminated[0, index] or truncated[0, index]):
                    done = True
                    break
            observation = observation_steps[executed - 1]

        actions = np.asarray(actions_seen, dtype=np.float32)
        metrics = {
            "suite": "libero_spatial",
            "task_id": args.task_id,
            "task_reset_state_id": args.task_reset_state_id,
            "global_reset_state_id": global_reset_state_id,
            "task_description": observation["task_descriptions"][0],
            "seed": args.seed,
            "model_path": str(Path(model_cfg.model_path).resolve()),
            "action_steps_per_replan": int(model_cfg.num_action_chunks),
            "steps": len(actions_seen),
            "terminated": bool(terminated.any()),
            "truncated": bool(truncated.any()),
            "success": bool(env.success_once[0]),
            "action_shape": list(actions.shape),
            "action_finite": bool(np.isfinite(actions).all()),
            "action_min": float(actions.min()),
            "action_max": float(actions.max()),
            "gripper_min": float(actions[:, -1].min()),
            "gripper_max": float(actions[:, -1].max()),
            "native_adapter_first_action_max_abs_error": native_adapter_max_error,
            "guidance_enabled": critic is not None,
            "critic_checkpoint": (
                str(args.critic_checkpoint.resolve()) if args.critic_checkpoint else None
            ),
            "guidance_q_improvement_mean": (
                float(np.mean([item["q_guided"] - item["q_base"] for item in guidance_records]))
                if guidance_records
                else None
            ),
            "guidance_delta_abs_mean": (
                float(np.mean([item["delta_abs_mean"] for item in guidance_records]))
                if guidance_records
                else None
            ),
            "elapsed_seconds": time.perf_counter() - started,
        }
        (args.output_dir / "closed_loop_metrics.json").write_text(
            json.dumps(metrics, indent=2) + "\n", encoding="utf-8"
        )
        if not args.no_video:
            imageio.mimsave(
                args.output_dir / f"smolvla_task{args.task_id}_episode{args.task_reset_state_id}.mp4",
                frames,
                fps=20,
            )
        print(json.dumps(metrics, indent=2))
    finally:
        env.env.close()


if __name__ == "__main__":
    main()
