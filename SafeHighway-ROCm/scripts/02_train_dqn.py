"""Train a DQN policy in HighwayEnv using AMD ROCm (or CPU)."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from common import (
    create_highway_env,
    make_run_name,
    model_zip_path,
    monitor_csv_path,
    normalize_model_path,
    print_rocm_info,
    resolve_device,
    resolve_run_paths,
    setup_headless_runtime,
    write_run_meta,
)
from safety import REWARD_PROFILES

setup_headless_runtime()

import numpy as np
import torch
from stable_baselines3 import DQN
from stable_baselines3.common.callbacks import EvalCallback
from stable_baselines3.common.monitor import Monitor
from stable_baselines3.common.utils import set_random_seed
from stable_baselines3.common.vec_env import DummyVecEnv, SubprocVecEnv


def parse_args():
    parser = argparse.ArgumentParser(
        description="Train a DQN policy in HighwayEnv using AMD ROCm."
    )

    parser.add_argument(
        "--run-name",
        type=str,
        default=None,
        help=(
            "Experiment id. Artifacts go to outputs/runs/<run-name>/. "
            "If omitted, a timestamp id is created automatically."
        ),
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
        "--reward-profile",
        choices=tuple(REWARD_PROFILES),
        default="baseline",
        help=(
            "Reward configuration. 'baseline' reproduces the original-demo setup "
            "where normalisation makes a collision worth zero; 'penalty' "
            "turns collisions into a genuine negative reward; 'ttc' adds "
            "dense time-to-collision and headway shaping on top."
        ),
    )
    parser.add_argument(
        "--n-envs",
        type=int,
        default=1,
        help="Parallel environments. Use 4+ to better utilize the GPU.",
    )
    parser.add_argument(
        "--device",
        choices=("auto", "cuda", "cpu"),
        default="auto",
        help="Training device. auto prefers ROCm/HIP when available.",
    )
    parser.add_argument(
        "--gamma",
        type=float,
        default=0.95,
        help="Discount factor. Higher values keep collision penalties visible longer.",
    )
    parser.add_argument(
        "--eval-freq",
        type=int,
        default=2_000,
        help="Evaluate and possibly save the best model every N timesteps.",
    )
    parser.add_argument(
        "--eval-episodes",
        type=int,
        default=5,
        help="Episodes per EvalCallback evaluation.",
    )
    parser.add_argument(
        "--tensorboard",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Enable TensorBoard logs under the run directory.",
    )

    return parser.parse_args()


def _env_factory(
    *,
    rank: int,
    seed: int,
    duration: int,
    vehicles: int,
    reward_profile: str,
    monitor_file: str | None,
):
    def _init():
        setup_headless_runtime()
        env = create_highway_env(
            duration=duration,
            vehicles=vehicles,
            seed=seed + rank,
            reward_profile=reward_profile,
        )
        if monitor_file is not None:
            Path(monitor_file).parent.mkdir(parents=True, exist_ok=True)
            env = Monitor(env, filename=monitor_file)
        else:
            env = Monitor(env)
        return env

    return _init


def make_training_env(args, monitor_file: Path):
    env_fns = [
        _env_factory(
            rank=rank,
            seed=args.seed,
            duration=args.duration,
            vehicles=args.vehicles,
            reward_profile=args.reward_profile,
            monitor_file=str(monitor_file) if rank == 0 else None,
        )
        for rank in range(args.n_envs)
    ]
    vec_cls = SubprocVecEnv if args.n_envs > 1 else DummyVecEnv
    return vec_cls(env_fns)


def make_eval_env(args):
    env_fns = [
        _env_factory(
            rank=0,
            seed=args.seed + 10_000,
            duration=args.duration,
            vehicles=args.vehicles,
            reward_profile=args.reward_profile,
            monitor_file=None,
        )
    ]
    return DummyVecEnv(env_fns)


def main():
    args = parse_args()

    if args.n_envs < 1:
        raise ValueError("--n-envs must be >= 1")

    run_name = make_run_name(
        args.run_name,
        prefix=f"train_{args.reward_profile}_t{args.timesteps}_s{args.seed}",
    )
    run = resolve_run_paths(run_name).ensure()

    model_stem = run.models / "dqn_highway"
    model_zip = model_zip_path(model_stem)
    best_model_dir = run.models / "best"
    summary_path = run.metrics / "train_summary.json"
    monitor_file = monitor_csv_path(run.metrics / "train.monitor.csv")
    best_model_dir.mkdir(parents=True, exist_ok=True)

    tensorboard_log = None
    if args.tensorboard:
        run.tensorboard.mkdir(parents=True, exist_ok=True)
        tensorboard_log = str(run.tensorboard)

    device = resolve_device(args.device)
    set_random_seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)

    print(f"=== Run: {run.run_name} ===")
    print(f"Artifacts: {run.root}")
    print_rocm_info(device)

    write_run_meta(
        run,
        stage="train_start",
        argv=sys.argv,
        params={
            "timesteps": args.timesteps,
            "seed": args.seed,
            "duration": args.duration,
            "vehicles": args.vehicles,
            "reward_profile": args.reward_profile,
            "n_envs": args.n_envs,
            "device": device,
            "gamma": args.gamma,
            "eval_freq": args.eval_freq,
            "eval_episodes": args.eval_episodes,
            "tensorboard": bool(tensorboard_log),
        },
    )

    train_env = make_training_env(args, monitor_file)
    eval_env = make_eval_env(args)

    policy_kwargs = {"net_arch": [256, 256]}

    model = DQN(
        policy="MlpPolicy",
        env=train_env,
        learning_rate=5e-4,
        buffer_size=50_000,
        learning_starts=1_000,
        batch_size=64,
        gamma=args.gamma,
        train_freq=4,
        gradient_steps=1,
        target_update_interval=1_000,
        exploration_fraction=0.3,
        exploration_initial_eps=1.0,
        exploration_final_eps=0.05,
        policy_kwargs=policy_kwargs,
        verbose=1,
        seed=args.seed,
        device=device,
        tensorboard_log=tensorboard_log,
    )

    eval_freq = max(args.eval_freq // args.n_envs, 1)
    eval_callback = EvalCallback(
        eval_env,
        best_model_save_path=str(best_model_dir),
        log_path=str(best_model_dir / "eval_logs"),
        eval_freq=eval_freq,
        n_eval_episodes=args.eval_episodes,
        deterministic=True,
        render=False,
        verbose=1,
    )

    print("\n=== DQN Configuration ===")
    print("Model device:", model.device)
    print("Reward profile:", args.reward_profile, REWARD_PROFILES[args.reward_profile])
    print("Training timesteps:", args.timesteps)
    print("Parallel envs:", args.n_envs)
    print("Gamma:", args.gamma)
    print("Network:", policy_kwargs["net_arch"])
    print("Replay buffer:", model.buffer_size)
    print("Batch size:", model.batch_size)
    print("Eval freq (per env):", eval_freq)

    if device == "cuda":
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()

    start_time = time.perf_counter()
    model.learn(
        total_timesteps=args.timesteps,
        log_interval=4,
        progress_bar=False,
        callback=eval_callback,
    )

    if device == "cuda":
        torch.cuda.synchronize()
    elapsed_seconds = time.perf_counter() - start_time

    model.save(str(model_stem))

    peak_vram_mb = None
    if device == "cuda":
        peak_vram_mb = torch.cuda.max_memory_allocated() / 1024**2

    episode_rewards = []
    episode_lengths = []
    if model.ep_info_buffer is not None:
        for episode in model.ep_info_buffer:
            if "r" in episode:
                episode_rewards.append(float(episode["r"]))
            if "l" in episode:
                episode_lengths.append(int(episode["l"]))

    best_model_zip = best_model_dir / "best_model.zip"

    summary = {
        "run_name": run.run_name,
        "run_dir": str(run.root),
        "environment": "highway-fast-v0",
        "algorithm": "DQN",
        "seed": args.seed,
        "timesteps": args.timesteps,
        "n_envs": args.n_envs,
        "duration_seconds": args.duration,
        "vehicles_count": args.vehicles,
        "reward_profile": args.reward_profile,
        "reward_profile_config": REWARD_PROFILES[args.reward_profile],
        "device": str(model.device),
        "torch_version": torch.__version__,
        "hip_version": torch.version.hip,
        "gpu": (
            torch.cuda.get_device_name(0)
            if torch.cuda.is_available()
            else None
        ),
        "network": [256, 256],
        "learning_rate": 5e-4,
        "buffer_size": int(model.buffer_size),
        "batch_size": int(model.batch_size),
        "gamma": args.gamma,
        "training_time_seconds": elapsed_seconds,
        "steps_per_second": args.timesteps / elapsed_seconds,
        "peak_vram_mb": peak_vram_mb,
        "recent_mean_episode_reward": (
            float(np.mean(episode_rewards)) if episode_rewards else None
        ),
        "recent_mean_episode_length": (
            float(np.mean(episode_lengths)) if episode_lengths else None
        ),
        "model_path": str(model_zip),
        "best_model_path": (
            str(best_model_zip) if best_model_zip.exists() else None
        ),
        "monitor_path": str(monitor_file),
        "tensorboard_log": tensorboard_log,
    }

    summary_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    write_run_meta(
        run,
        stage="train_done",
        argv=sys.argv,
        params=summary,
        extra={
            "model_path": str(model_zip),
            "best_model_path": summary["best_model_path"],
            "train_summary": str(summary_path),
        },
    )

    train_env.close()
    eval_env.close()

    print("\n=== Training Complete ===")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"\nRun dir:     {run.root}")
    print(f"Final model: {model_zip}")
    if best_model_zip.exists():
        print(f"Best model:  {best_model_zip}")
    print(f"Summary:     {summary_path}")
    print(
        "\nNext:\n"
        f"  python scripts/03_evaluate.py --run-name {run.run_name}\n"
        f"  python scripts/04_plot_monitor.py --run-name {run.run_name}\n"
        f"  python scripts/05_list_runs.py"
    )


if __name__ == "__main__":
    main()
