"""Train a privileged-state SAC residual on top of frozen SmolVLA."""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict
from pathlib import Path

import numpy as np
import torch

from .common import append_jsonl, initialize, torch_device
from .env import PlumResidualEnv, ResidualEnvConfig
from .models import ResidualScales
from .replay import ReplayBuffer
from .sac import SACAgent, SACConfig


def main() -> None:
    parser = argparse.ArgumentParser(description="Train plum residual SAC over a frozen SmolVLA policy.")
    parser.add_argument("--policy-path", required=True)
    parser.add_argument("--repo-id", required=True)
    parser.add_argument("--dataset-root", required=True)
    parser.add_argument("--output-dir", default="outputs/rl/plum_residual_sac")
    parser.add_argument(
        "--init-actor-checkpoint",
        default=None,
        help="Initialize only the residual actor from a previous SAC checkpoint; critics are reset for the new reward.",
    )
    parser.add_argument("--total-steps", type=int, default=300_000)
    parser.add_argument("--warmup-steps", type=int, default=10_000)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--replay-size", type=int, default=500_000)
    parser.add_argument("--updates-per-step", type=int, default=1)
    parser.add_argument("--save-every", type=int, default=10_000)
    parser.add_argument("--seed", type=int, default=3000)
    parser.add_argument("--seed-count", type=int, default=2000)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--jitter", type=float, default=0.03)
    parser.add_argument("--task-mode", choices=("lift", "full"), default="lift")
    parser.add_argument("--arm-scale", type=float, default=0.015)
    parser.add_argument("--finger-scale", type=float, default=0.003)
    parser.add_argument("--warmup-range", type=float, default=0.25)
    parser.add_argument("--gamma", type=float, default=0.99)
    parser.add_argument("--tau", type=float, default=0.005)
    parser.add_argument("--lr", type=float, default=3e-4)
    args = parser.parse_args()

    output = Path(args.output_dir)
    checkpoint_dir = output / "checkpoints"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    (output / "config.json").write_text(json.dumps(vars(args), indent=2))

    bundle, base_policy = initialize(args.policy_path, args.repo_id, args.dataset_root, args.device)
    scales = ResidualScales(args.arm_scale, args.finger_scale)
    env = PlumResidualEnv(
        bundle,
        base_policy,
        ResidualEnvConfig(
            jitter=args.jitter,
            task_mode=args.task_mode,
            terminate_on_drop=True,
            residual_scales=scales,
        ),
    )
    seed_rng = np.random.default_rng(args.seed)
    state, _ = env.reset(args.seed)
    device = torch_device(args.device)
    sac_cfg = SACConfig(
        gamma=args.gamma,
        tau=args.tau,
        actor_lr=args.lr,
        critic_lr=args.lr,
        alpha_lr=args.lr,
    )
    agent = SACAgent(state.size, env.action_dim, device, sac_cfg)
    if args.init_actor_checkpoint:
        data = torch.load(args.init_actor_checkpoint, map_location=device, weights_only=False)
        if data["obs_dim"] != state.size or data["action_dim"] != env.action_dim:
            raise ValueError(
                "initial actor checkpoint shape does not match environment: "
                f"checkpoint=({data['obs_dim']}, {data['action_dim']}), env=({state.size}, {env.action_dim})"
            )
        agent.actor.load_state_dict(data["actor"])
        print(f"[residual-sac] initialized actor from {args.init_actor_checkpoint}")
    replay = ReplayBuffer(args.replay_size, state.size, env.action_dim, seed=args.seed)
    episode_return = 0.0
    episode_index = 0
    episode_started = time.perf_counter()
    last_metrics: dict[str, float] = {}

    for step in range(1, args.total_steps + 1):
        if step <= args.warmup_steps:
            residual = seed_rng.uniform(-args.warmup_range, args.warmup_range, size=env.action_dim).astype(np.float32)
        else:
            residual = agent.act(state)
        next_state, reward, terminated, truncated, info = env.step(residual)
        replay.add(state, residual, reward, next_state, terminated)
        state = next_state
        episode_return += reward

        if replay.size >= args.batch_size and step > args.warmup_steps:
            for _ in range(args.updates_per_step):
                last_metrics = agent.update(replay.sample(args.batch_size, device))

        if terminated or truncated:
            row = {
                "episode": episode_index,
                "global_step": step,
                "seed": info["seed"],
                "return": episode_return,
                "success": bool(info["success"]),
                "steps": info["policy_steps"],
                "failure_stage": info.get("failure_stage"),
                "wall_seconds": time.perf_counter() - episode_started,
                **last_metrics,
            }
            append_jsonl(output / "train_metrics.jsonl", row)
            print(
                f"[residual-sac] step={step} ep={episode_index} seed={info['seed']} "
                f"return={episode_return:.2f} success={info['success']} stage={info.get('failure_stage')}"
            )
            episode_index += 1
            episode_return = 0.0
            episode_started = time.perf_counter()
            next_seed = args.seed + int(seed_rng.integers(0, args.seed_count))
            state, _ = env.reset(next_seed)

        if step % args.save_every == 0 or step == args.total_steps:
            path = checkpoint_dir / f"{step:06d}.pt"
            torch.save(
                agent.checkpoint(
                    step=step,
                    obs_dim=env.obs_dim,
                    extra={"env_config": asdict(env.cfg), "residual_scales": scales.to_dict()},
                ),
                path,
            )
            torch.save(agent.checkpoint(step=step, obs_dim=env.obs_dim), checkpoint_dir / "last.pt")
            print(f"[residual-sac] checkpoint -> {path}")


if __name__ == "__main__":
    main()
