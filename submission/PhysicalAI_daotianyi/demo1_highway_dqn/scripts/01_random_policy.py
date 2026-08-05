import argparse
import json
import os
from pathlib import Path

# Configure a private runtime directory for headless cloud servers.
RUNTIME_DIR = Path("/tmp/highway-runtime")
RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
RUNTIME_DIR.chmod(0o700)

os.environ.setdefault("XDG_RUNTIME_DIR", str(RUNTIME_DIR))
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import gymnasium as gym
import highway_env
import imageio.v2 as imageio
import numpy as np


ACTION_NAMES = {
    0: "LANE_LEFT",
    1: "IDLE",
    2: "LANE_RIGHT",
    3: "FASTER",
    4: "SLOWER",
}


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run a random policy in HighwayEnv."
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--duration", type=int, default=20)
    parser.add_argument("--vehicles", type=int, default=30)
    parser.add_argument(
        "--video",
        type=Path,
        default=Path("outputs/videos/random_policy.mp4"),
    )
    parser.add_argument(
        "--metrics",
        type=Path,
        default=Path("outputs/metrics/random_policy.json"),
    )
    return parser.parse_args()


def main():
    args = parse_args()

    args.video.parent.mkdir(parents=True, exist_ok=True)
    args.metrics.parent.mkdir(parents=True, exist_ok=True)

    gym.register_envs(highway_env)

    env = gym.make(
        "highway-fast-v0",
        render_mode="rgb_array",
    )

    env.unwrapped.configure(
        {
            "duration": args.duration,
            "vehicles_count": args.vehicles,
            "simulation_frequency": 15,
            "policy_frequency": 5,
            "screen_width": 960,
            "screen_height": 240,
            "offscreen_rendering": True,
            "show_trajectories": False,
        }
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

    writer = imageio.get_writer(
        args.video,
        fps=5,
        codec="libx264",
        quality=8,
        macro_block_size=2,
    )

    for frame in frames:
        writer.append_data(frame)

    writer.close()
    env.close()

    action_counts = {
        ACTION_NAMES[action]: actions.count(action)
        for action in ACTION_NAMES
    }

    metrics = {
        "policy": "random",
        "environment": "highway-fast-v0",
        "seed": args.seed,
        "duration_seconds": args.duration,
        "vehicles_count": args.vehicles,
        "steps": step,
        "total_reward": float(np.sum(rewards)),
        "mean_reward": float(np.mean(rewards)),
        "mean_speed": float(np.mean(speeds)),
        "max_speed": float(np.max(speeds)),
        "crashed": crashed,
        "action_counts": action_counts,
        "video": str(args.video),
    }

    args.metrics.write_text(
        json.dumps(metrics, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print("\n=== Random Policy Summary ===")
    print(json.dumps(metrics, indent=2, ensure_ascii=False))
    print(f"\nVideo saved to:   {args.video}")
    print(f"Metrics saved to: {args.metrics}")


if __name__ == "__main__":
    main()
