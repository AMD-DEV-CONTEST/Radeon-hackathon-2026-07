import argparse
import json
import os
import time
from pathlib import Path

RUNTIME_DIR = Path("/tmp/highway-runtime")
RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
RUNTIME_DIR.chmod(0o700)

os.environ.setdefault("XDG_RUNTIME_DIR", str(RUNTIME_DIR))
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import gymnasium as gym
import highway_env
import imageio.v2 as imageio
import numpy as np
import torch

from stable_baselines3 import DQN


ACTION_NAMES = {
    0: "LANE_LEFT",
    1: "IDLE",
    2: "LANE_RIGHT",
    3: "FASTER",
    4: "SLOWER",
}


def parse_args():
    parser = argparse.ArgumentParser(
        description="Compare random and DQN policies in HighwayEnv."
    )

    parser.add_argument(
        "--model",
        type=Path,
        default=Path("outputs/models/dqn_highway_smoke.zip"),
    )
    parser.add_argument("--episodes", type=int, default=10)
    parser.add_argument("--seed", type=int, default=100)
    parser.add_argument("--duration", type=int, default=20)
    parser.add_argument("--vehicles", type=int, default=30)

    parser.add_argument(
        "--metrics",
        type=Path,
        default=Path("outputs/metrics/eval_smoke.json"),
    )
    parser.add_argument(
        "--random-video",
        type=Path,
        default=Path("outputs/videos/eval_random.mp4"),
    )
    parser.add_argument(
        "--dqn-video",
        type=Path,
        default=Path("outputs/videos/eval_dqn_smoke.mp4"),
    )

    return parser.parse_args()


def create_environment(args):
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

    return env


def write_video(path, frames):
    path.parent.mkdir(parents=True, exist_ok=True)

    writer = imageio.get_writer(
        path,
        fps=5,
        codec="libx264",
        quality=8,
        macro_block_size=2,
    )

    for frame in frames:
        writer.append_data(frame)

    writer.close()


def evaluate_policy(
    policy_name,
    args,
    model=None,
    video_path=None,
):
    env = create_environment(args)

    episode_results = []
    all_inference_times_ms = []

    for episode_index in range(args.episodes):
        episode_seed = args.seed + episode_index

        observation, info = env.reset(seed=episode_seed)
        env.action_space.seed(episode_seed)

        terminated = False
        truncated = False

        rewards = []
        speeds = []
        actions = []
        frames = []

        if episode_index == 0:
            frames.append(env.render())

        while not (terminated or truncated):
            if policy_name == "random":
                action = env.action_space.sample()

            elif policy_name == "dqn":
                torch.cuda.synchronize()
                inference_start = time.perf_counter()

                action, _ = model.predict(
                    observation,
                    deterministic=True,
                )

                torch.cuda.synchronize()
                inference_ms = (
                    time.perf_counter() - inference_start
                ) * 1000

                all_inference_times_ms.append(inference_ms)
                action = int(np.asarray(action).item())

            else:
                raise ValueError(f"Unknown policy: {policy_name}")

            observation, reward, terminated, truncated, info = env.step(
                action
            )

            vehicle = env.unwrapped.vehicle

            rewards.append(float(reward))
            speeds.append(float(vehicle.speed))
            actions.append(int(action))

            if episode_index == 0:
                frames.append(env.render())

        vehicle = env.unwrapped.vehicle

        result = {
            "episode": episode_index,
            "seed": episode_seed,
            "steps": len(rewards),
            "total_reward": float(np.sum(rewards)),
            "mean_reward": float(np.mean(rewards)),
            "mean_speed": float(np.mean(speeds)),
            "max_speed": float(np.max(speeds)),
            "crashed": bool(vehicle.crashed),
            "terminated": bool(terminated),
            "truncated": bool(truncated),
            "action_counts": {
                ACTION_NAMES[action]: actions.count(action)
                for action in ACTION_NAMES
            },
        }

        episode_results.append(result)

        print(
            f"[{policy_name}] "
            f"episode={episode_index:02d} "
            f"reward={result['total_reward']:.2f} "
            f"steps={result['steps']:03d} "
            f"speed={result['mean_speed']:.2f} "
            f"crashed={result['crashed']}"
        )

        if episode_index == 0 and video_path is not None:
            write_video(video_path, frames)

    env.close()

    collision_count = sum(
        int(result["crashed"])
        for result in episode_results
    )

    summary = {
        "policy": policy_name,
        "episodes": args.episodes,
        "mean_total_reward": float(
            np.mean(
                [
                    result["total_reward"]
                    for result in episode_results
                ]
            )
        ),
        "std_total_reward": float(
            np.std(
                [
                    result["total_reward"]
                    for result in episode_results
                ]
            )
        ),
        "mean_episode_steps": float(
            np.mean(
                [
                    result["steps"]
                    for result in episode_results
                ]
            )
        ),
        "mean_speed": float(
            np.mean(
                [
                    result["mean_speed"]
                    for result in episode_results
                ]
            )
        ),
        "collision_count": collision_count,
        "collision_rate": collision_count / args.episodes,
        "mean_inference_ms": (
            float(np.mean(all_inference_times_ms))
            if all_inference_times_ms
            else None
        ),
        "p95_inference_ms": (
            float(np.percentile(all_inference_times_ms, 95))
            if all_inference_times_ms
            else None
        ),
        "video": str(video_path) if video_path else None,
        "episode_results": episode_results,
    }

    return summary


def main():
    args = parse_args()

    args.metrics.parent.mkdir(parents=True, exist_ok=True)
    args.random_video.parent.mkdir(parents=True, exist_ok=True)
    args.dqn_video.parent.mkdir(parents=True, exist_ok=True)

    gym.register_envs(highway_env)

    if not args.model.exists():
        raise FileNotFoundError(
            f"DQN model not found: {args.model}"
        )

    if not torch.cuda.is_available():
        raise RuntimeError("AMD ROCm GPU is unavailable.")

    print("=== AMD ROCm ===")
    print("PyTorch:", torch.__version__)
    print("HIP:", torch.version.hip)
    print("GPU:", torch.cuda.get_device_name(0))

    print("\n=== Load DQN ===")
    model = DQN.load(
        str(args.model),
        device="cuda",
    )
    print("Model:", args.model)
    print("Device:", model.device)

    print("\n=== Random Policy Evaluation ===")
    random_summary = evaluate_policy(
        policy_name="random",
        args=args,
        video_path=args.random_video,
    )

    print("\n=== DQN Policy Evaluation ===")
    dqn_summary = evaluate_policy(
        policy_name="dqn",
        args=args,
        model=model,
        video_path=args.dqn_video,
    )

    comparison = {
        "environment": "highway-fast-v0",
        "model": str(args.model),
        "evaluation_seed_start": args.seed,
        "episodes": args.episodes,
        "random": random_summary,
        "dqn": dqn_summary,
        "improvement": {
            "reward_difference": (
                dqn_summary["mean_total_reward"]
                - random_summary["mean_total_reward"]
            ),
            "collision_rate_difference": (
                dqn_summary["collision_rate"]
                - random_summary["collision_rate"]
            ),
            "episode_steps_difference": (
                dqn_summary["mean_episode_steps"]
                - random_summary["mean_episode_steps"]
            ),
        },
    }

    args.metrics.write_text(
        json.dumps(comparison, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print("\n=== Comparison ===")
    print(
        f"Random reward: "
        f"{random_summary['mean_total_reward']:.2f}"
    )
    print(
        f"DQN reward:    "
        f"{dqn_summary['mean_total_reward']:.2f}"
    )
    print(
        f"Random collision rate: "
        f"{random_summary['collision_rate']:.1%}"
    )
    print(
        f"DQN collision rate:    "
        f"{dqn_summary['collision_rate']:.1%}"
    )
    print(
        f"DQN mean inference: "
        f"{dqn_summary['mean_inference_ms']:.3f} ms"
    )
    print(
        f"DQN P95 inference:  "
        f"{dqn_summary['p95_inference_ms']:.3f} ms"
    )

    print(f"\nMetrics saved to: {args.metrics}")
    print(f"Random video:     {args.random_video}")
    print(f"DQN video:        {args.dqn_video}")


if __name__ == "__main__":
    main()
