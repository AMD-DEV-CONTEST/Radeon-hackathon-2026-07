"""
Train a PPO policy for the SafeSort-RL PyBullet environment.

This entry point is intentionally compact so evaluators can reproduce the
baseline from the command line or Docker image.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from stable_baselines3 import PPO
from stable_baselines3.common.callbacks import CheckpointCallback
from stable_baselines3.common.env_util import make_vec_env

from env import WasteSortingEnv


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train SafeSort-RL with PPO.")
    parser.add_argument("--timesteps", type=int, default=500_000)
    parser.add_argument("--n-envs", type=int, default=4)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--model-out", default="models/safesort_policy")
    parser.add_argument("--checkpoint-dir", default="models/checkpoints")
    parser.add_argument("--log-dir", default="logs")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--verbose", type=int, default=1)
    return parser.parse_args()


def make_env() -> WasteSortingEnv:
    return WasteSortingEnv(use_gui=False)


def main() -> None:
    args = parse_args()
    model_out = Path(args.model_out)
    checkpoint_dir = Path(args.checkpoint_dir)
    log_dir = Path(args.log_dir)
    model_out.parent.mkdir(parents=True, exist_ok=True)
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)

    env = make_vec_env(make_env, n_envs=args.n_envs, seed=args.seed)
    checkpoint_callback = CheckpointCallback(
        save_freq=max(args.timesteps // 10, 1),
        save_path=str(checkpoint_dir),
        name_prefix="safesort_policy",
    )

    model = PPO(
        "CnnPolicy",
        env,
        device=args.device,
        tensorboard_log=str(log_dir),
        verbose=args.verbose,
        seed=args.seed,
    )
    model.learn(total_timesteps=args.timesteps, callback=checkpoint_callback)
    model.save(str(model_out))
    env.close()

    print(f"Saved trained policy to {model_out}.zip")


if __name__ == "__main__":
    main()
