import argparse
import json
import os
import time
from pathlib import Path

# Configure a private runtime directory for headless cloud servers.
RUNTIME_DIR = Path("/tmp/highway-runtime")
RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
RUNTIME_DIR.chmod(0o700)

os.environ.setdefault("XDG_RUNTIME_DIR", str(RUNTIME_DIR))
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import gymnasium as gym
import highway_env
import numpy as np
import torch

from stable_baselines3 import DQN
from stable_baselines3.common.monitor import Monitor
from stable_baselines3.common.utils import set_random_seed


def parse_args():
    parser = argparse.ArgumentParser(
        description="Train a DQN policy in HighwayEnv using AMD ROCm."
    )

    parser.add_argument(
        "--timesteps",
        type=int,
        default=20_000,
        help="Total environment interaction steps.",
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--duration", type=int, default=20)
    parser.add_argument("--vehicles", type=int, default=30)

    parser.add_argument(
        "--model",
        type=Path,
        default=Path("outputs/models/dqn_highway"),
    )
    parser.add_argument(
        "--summary",
        type=Path,
        default=Path("outputs/metrics/train_summary.json"),
    )
    parser.add_argument(
        "--monitor",
        type=Path,
        default=Path("outputs/metrics/train_monitor.csv"),
    )

    return parser.parse_args()


def create_environment(args):
    gym.register_envs(highway_env)

    env = gym.make("highway-fast-v0")

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

    env.reset(seed=args.seed)

    return Monitor(
        env,
        filename=str(args.monitor),
    )


def main():
    args = parse_args()

    args.model.parent.mkdir(parents=True, exist_ok=True)
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.monitor.parent.mkdir(parents=True, exist_ok=True)

    set_random_seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)

    if not torch.cuda.is_available():
        raise RuntimeError(
            "AMD GPU is not available through PyTorch ROCm."
        )

    print("=== AMD ROCm Environment ===")
    print("PyTorch:", torch.__version__)
    print("HIP:", torch.version.hip)
    print("GPU:", torch.cuda.get_device_name(0))
    print("GPU count:", torch.cuda.device_count())

    env = create_environment(args)

    policy_kwargs = {
        "net_arch": [256, 256],
    }

    model = DQN(
        policy="MlpPolicy",
        env=env,
        learning_rate=5e-4,
        buffer_size=15_000,
        learning_starts=200,
        batch_size=64,
        gamma=0.8,
        train_freq=1,
        gradient_steps=1,
        target_update_interval=50,
        exploration_fraction=0.5,
        exploration_initial_eps=1.0,
        exploration_final_eps=0.05,
        policy_kwargs=policy_kwargs,
        verbose=1,
        seed=args.seed,
        device="cuda",
    )

    print("\n=== DQN Configuration ===")
    print("Model device:", model.device)
    print("Training timesteps:", args.timesteps)
    print("Network:", policy_kwargs["net_arch"])
    print("Replay buffer:", model.buffer_size)
    print("Batch size:", model.batch_size)

    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats()

    start_time = time.perf_counter()

    model.learn(
        total_timesteps=args.timesteps,
        log_interval=4,
        progress_bar=False,
    )

    torch.cuda.synchronize()
    elapsed_seconds = time.perf_counter() - start_time

    model.save(str(args.model))

    peak_vram_mb = (
        torch.cuda.max_memory_allocated() / 1024**2
    )

    episode_rewards = []
    episode_lengths = []

    if model.ep_info_buffer is not None:
        for episode in model.ep_info_buffer:
            if "r" in episode:
                episode_rewards.append(float(episode["r"]))
            if "l" in episode:
                episode_lengths.append(int(episode["l"]))

    summary = {
        "environment": "highway-fast-v0",
        "algorithm": "DQN",
        "seed": args.seed,
        "timesteps": args.timesteps,
        "duration_seconds": args.duration,
        "vehicles_count": args.vehicles,
        "device": str(model.device),
        "torch_version": torch.__version__,
        "hip_version": torch.version.hip,
        "gpu": torch.cuda.get_device_name(0),
        "network": [256, 256],
        "learning_rate": 5e-4,
        "buffer_size": 15_000,
        "batch_size": 64,
        "gamma": 0.8,
        "training_time_seconds": elapsed_seconds,
        "steps_per_second": args.timesteps / elapsed_seconds,
        "peak_vram_mb": peak_vram_mb,
        "recent_mean_episode_reward": (
            float(np.mean(episode_rewards))
            if episode_rewards
            else None
        ),
        "recent_mean_episode_length": (
            float(np.mean(episode_lengths))
            if episode_lengths
            else None
        ),
        "model_path": str(args.model) + ".zip",
        "monitor_path": str(args.monitor),
    }

    args.summary.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    env.close()

    print("\n=== Training Complete ===")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"\nModel saved to:   {args.model}.zip")
    print(f"Summary saved to: {args.summary}")


if __name__ == "__main__":
    main()
