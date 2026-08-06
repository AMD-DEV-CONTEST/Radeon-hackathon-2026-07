#!/usr/bin/env python
"""Evaluate shooting accuracy and other metrics from a trained policy.

Runs the policy on a single environment and prints shot statistics:
  - 射门次数 (shots taken)
  - 射正次数 (shots on target)
  - 进球数 (goals scored)
  - 射正率 (on-target rate)
  - 进球率 (goal rate)

Usage:
    python scripts/stats.py -e t1_chase --task chase --steps 1200
    python scripts/stats.py -e t1_shoot --task shoot --steps 1200
"""
import argparse
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yaml
import genesis as gs
from rsl_rl.runners import OnPolicyRunner
from envs.soccer_env import SoccerEnv


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-e", "--exp_name", required=True)
    parser.add_argument("--task", type=str, default="shoot")
    parser.add_argument("--steps", type=int, default=1200)
    parser.add_argument("--config", default="configs/soccer_agent.yaml")
    args = parser.parse_args()

    with open(args.config) as f:
        cfg = yaml.safe_load(f)

    env_cfg = dict(cfg["env"])
    env_cfg["task"] = args.task
    train_cfg = cfg["train"]
    log_dir = f"runs/{args.exp_name}"

    model_files = sorted(glob.glob(f"{log_dir}/model_*.pt"), key=os.path.getmtime)
    if not model_files:
        raise FileNotFoundError(f"No model_*.pt found in {log_dir}")
    latest = model_files[-1]
    print(f"Loading: {latest}")

    gs.init(backend=gs.gpu, precision="32", logging_level="warning", seed=42)

    env = SoccerEnv(
        num_envs=1,
        env_cfg=env_cfg,
        obs_cfg=cfg["obs"],
        reward_cfg=cfg["reward"],
        command_cfg=cfg["command"],
        show_viewer=False,
    )

    runner = OnPolicyRunner(env, train_cfg, log_dir, device=gs.device)
    runner.load(latest)
    policy = runner.get_inference_policy(device=gs.device)

    obs = env.reset()
    for i in range(args.steps):
        actions = policy(obs)
        obs, rews, dones, _ = env.step(actions)
        if (i + 1) % 200 == 0:
            print(f"step {i + 1}/{args.steps}")

    stats = env.get_stats()
    print()
    print("=" * 50)
    print(f"Shooting Stats — {args.exp_name} ({args.task})")
    print("=" * 50)
    print(f"  Shots taken:      {stats['shots_taken']}")
    print(f"  Shots on target:   {stats['shots_on_target']}")
    print(f"  Goals scored:      {stats['goals_scored']}")
    print(f"  On-target rate:    {stats['on_target_rate']:.1%}")
    print(f"  Goal rate:         {stats['goal_rate']:.1%}")
    print("=" * 50)


if __name__ == "__main__":
    main()
