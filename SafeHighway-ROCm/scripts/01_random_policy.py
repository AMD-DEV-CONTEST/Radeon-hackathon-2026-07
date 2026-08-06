"""Run a random policy in HighwayEnv and export video + metrics."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from common import (
    ACTION_NAMES,
    create_highway_env,
    make_run_name,
    resolve_run_paths,
    setup_headless_runtime,
    write_run_meta,
    write_video,
)

setup_headless_runtime()

import numpy as np


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run a random policy in HighwayEnv."
    )
    parser.add_argument(
        "--run-name",
        type=str,
        default=None,
        help="Experiment id under outputs/runs/. Auto timestamp if omitted.",
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--duration", type=int, default=20)
    parser.add_argument("--vehicles", type=int, default=30)
    return parser.parse_args()


def main():
    args = parse_args()
    run = resolve_run_paths(
        make_run_name(args.run_name, prefix="random")
    ).ensure()

    video_path = run.videos / "random_policy.mp4"
    metrics_path = run.metrics / "random_policy.json"

    print(f"=== Run: {run.run_name} ===")
    print(f"Artifacts: {run.root}")

    env = create_highway_env(
        duration=args.duration,
        vehicles=args.vehicles,
        render_mode="rgb_array",
        seed=args.seed,
    )

    observation, info = env.reset(seed=args.seed)
    frames = [env.render()]
    rewards = []
    speeds = []
    actions = []

    terminated = False
    truncated = False
    step = 0

    while not (terminated or truncated):
        action = env.action_space.sample()
        observation, reward, terminated, truncated, info = env.step(action)
        vehicle = env.unwrapped.vehicle

        rewards.append(float(reward))
        speeds.append(float(vehicle.speed))
        actions.append(int(action))
        frames.append(env.render())
        step += 1

        print(
            f"step={step:03d} "
            f"action={ACTION_NAMES[int(action)]:>10s} "
            f"reward={reward:+.3f} "
            f"speed={vehicle.speed:.2f} "
            f"crashed={vehicle.crashed}"
        )

    vehicle = env.unwrapped.vehicle
    crashed = bool(vehicle.crashed)

    write_video(video_path, frames)
    env.close()

    action_counts = {
        ACTION_NAMES[action]: actions.count(action)
        for action in ACTION_NAMES
    }

    metrics = {
        "run_name": run.run_name,
        "run_dir": str(run.root),
        "policy": "random",
        "environment": "highway-fast-v0",
        "seed": args.seed,
        "duration_seconds": args.duration,
        "vehicles_count": args.vehicles,
        "steps": step,
        "total_reward": float(np.sum(rewards)),
        "mean_step_reward": float(np.mean(rewards)) if rewards else 0.0,
        "mean_reward": float(np.mean(rewards)) if rewards else 0.0,
        "mean_speed": float(np.mean(speeds)) if speeds else 0.0,
        "max_speed": float(np.max(speeds)) if speeds else 0.0,
        "crashed": crashed,
        "action_counts": action_counts,
        "video": str(video_path),
    }

    metrics_path.write_text(
        json.dumps(metrics, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    write_run_meta(
        run,
        stage="random_done",
        argv=sys.argv,
        params={
            "seed": args.seed,
            "duration": args.duration,
            "vehicles": args.vehicles,
        },
        extra={"random_metrics": str(metrics_path), "random_video": str(video_path)},
    )

    print("\n=== Random Policy Summary ===")
    print(json.dumps(metrics, indent=2, ensure_ascii=False))
    print(f"\nRun dir: {run.root}")
    print(f"Video:   {video_path}")
    print(f"Metrics: {metrics_path}")


if __name__ == "__main__":
    main()
