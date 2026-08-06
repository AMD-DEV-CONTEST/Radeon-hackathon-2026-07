"""Strict paired baseline-vs-residual evaluation on identical seeds."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from .common import initialize, torch_device
from .env import PlumResidualEnv, ResidualEnvConfig
from .models import ResidualScales
from .sac import SACAgent


def residual_enabled(env: PlumResidualEnv, gate: str) -> bool:
    """Whether the residual actor may control the current policy step."""
    if gate == "none":
        return True
    if gate == "after-lift":
        # `ever_lifted` is latched, so residual control cannot turn back on if
        # the fruit drops after the handover to the frozen base policy.
        return not env.tracker.ever_lifted
    raise ValueError(f"unknown residual gate: {gate}")


def rollout(env: PlumResidualEnv, seed: int, agent: SACAgent | None, residual_gate: str = "none") -> dict:
    state, _ = env.reset(seed)
    terminated = truncated = False
    total_reward = 0.0
    info = {}
    gate_step = None
    residual_steps = 0
    while not (terminated or truncated):
        enabled = agent is not None and residual_enabled(env, residual_gate)
        if enabled:
            residual = agent.act(state, deterministic=True)
            residual_steps += 1
        else:
            residual = np.zeros(9, dtype=np.float32)
            if agent is not None and gate_step is None:
                gate_step = env.policy_steps
        state, reward, terminated, truncated, info = env.step(residual)
        total_reward += reward
    return {
        "seed": seed,
        "success": bool(info["success"]),
        "steps": int(info["policy_steps"]),
        "return": total_reward,
        "residual_gate": residual_gate if agent is not None else "baseline",
        "residual_steps": residual_steps,
        "gate_step": gate_step,
        **env.tracker.summary(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Paired SmolVLA vs residual-SAC plum evaluation.")
    parser.add_argument("--policy-path", required=True)
    parser.add_argument("--residual-checkpoint", required=True)
    parser.add_argument("--repo-id", required=True)
    parser.add_argument("--dataset-root", required=True)
    parser.add_argument("--episodes", type=int, default=100)
    parser.add_argument("--seed", type=int, default=2000)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--jitter", type=float, default=0.03)
    parser.add_argument("--arm-scale", type=float, default=0.015)
    parser.add_argument("--finger-scale", type=float, default=0.003)
    parser.add_argument(
        "--residual-gate",
        choices=("none", "after-lift"),
        default="none",
        help="Disable the residual permanently after the tracker first detects a successful lift.",
    )
    parser.add_argument("--out", default="outputs/rl/plum_residual_sac/paired_100ep.json")
    args = parser.parse_args()

    bundle, base_policy = initialize(args.policy_path, args.repo_id, args.dataset_root, args.device)
    env = PlumResidualEnv(
        bundle,
        base_policy,
        ResidualEnvConfig(
            jitter=args.jitter,
            task_mode="full",
            terminate_on_drop=False,
            residual_scales=ResidualScales(args.arm_scale, args.finger_scale),
        ),
    )
    # Materialize obs_dim before loading so checkpoint/environment mismatches fail early.
    env.reset(args.seed)
    agent = SACAgent.from_checkpoint(args.residual_checkpoint, torch_device(args.device))
    if agent.actor.obs_dim != env.obs_dim:
        raise ValueError(f"checkpoint obs_dim={agent.actor.obs_dim}, environment obs_dim={env.obs_dim}")

    baseline = []
    residual = []
    for episode in range(args.episodes):
        seed = args.seed + episode
        a = rollout(env, seed, None)
        b = rollout(env, seed, agent, args.residual_gate)
        baseline.append(a)
        residual.append(b)
        print(f"[paired] seed={seed} baseline={a['success']} residual={b['success']}")

    both_success = sum(a["success"] and b["success"] for a, b in zip(baseline, residual, strict=True))
    baseline_only = sum(a["success"] and not b["success"] for a, b in zip(baseline, residual, strict=True))
    residual_only = sum(not a["success"] and b["success"] for a, b in zip(baseline, residual, strict=True))
    both_fail = args.episodes - both_success - baseline_only - residual_only
    result = {
        "episodes": args.episodes,
        "baseline_success": sum(row["success"] for row in baseline),
        "residual_success": sum(row["success"] for row in residual),
        "both_success": both_success,
        "baseline_only": baseline_only,
        "residual_only": residual_only,
        "both_fail": both_fail,
        "gated_episodes": sum(row["gate_step"] is not None for row in residual),
        "mean_gate_step": (
            sum(row["gate_step"] for row in residual if row["gate_step"] is not None)
            / max(1, sum(row["gate_step"] is not None for row in residual))
        ),
        "params": vars(args),
        "baseline": baseline,
        "residual": residual,
    }
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2))
    print(f"[paired] results -> {path}")


if __name__ == "__main__":
    main()
