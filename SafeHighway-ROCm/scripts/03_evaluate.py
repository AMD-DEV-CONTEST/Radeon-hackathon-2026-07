"""Compare random and DQN policies in HighwayEnv."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from common import (
    ACTION_NAMES,
    create_highway_env,
    find_run_from_model,
    make_run_name,
    model_zip_path,
    print_rocm_info,
    resolve_device,
    resolve_run_paths,
    setup_headless_runtime,
    write_run_meta,
    write_video,
)
from safety import (
    REWARD_PROFILES,
    TTC_REPORTING_CAP,
    TTC_VIOLATION_THRESHOLD,
)

setup_headless_runtime()

import gymnasium as gym
import highway_env
import numpy as np
import torch
from stable_baselines3 import DQN


def parse_args():
    parser = argparse.ArgumentParser(
        description="Compare random and DQN policies in HighwayEnv."
    )

    parser.add_argument(
        "--run-name",
        type=str,
        default=None,
        help=(
            "Write eval artifacts into outputs/runs/<run-name>/. "
            "If omitted but --model is under a run dir, that run is reused; "
            "otherwise a new timestamped eval run is created."
        ),
    )
    parser.add_argument(
        "--model",
        type=Path,
        default=None,
        help=(
            "DQN model .zip or stem. Default: "
            "<run>/models/best/best_model.zip if present, else "
            "<run>/models/dqn_highway.zip"
        ),
    )
    parser.add_argument("--episodes", type=int, default=10)
    parser.add_argument("--seed", type=int, default=100)
    parser.add_argument("--duration", type=int, default=20)
    parser.add_argument("--vehicles", type=int, default=30)
    parser.add_argument(
        "--reward-profile",
        choices=tuple(REWARD_PROFILES),
        default="baseline",
        help=(
            "Reward configuration used for scoring. Keep the default so that "
            "models trained under different shaping schemes are compared on "
            "one common reward scale; safety metrics are profile-independent."
        ),
    )
    parser.add_argument(
        "--device",
        choices=("auto", "cuda", "cpu"),
        default="auto",
    )
    parser.add_argument(
        "--warmup",
        type=int,
        default=30,
        help="Warmup DQN predict() calls before timing.",
    )
    parser.add_argument(
        "--video-mode",
        choices=("best_survivor", "longest_crash", "fixed"),
        default="best_survivor",
        help=(
            "Which episode to record. best_survivor (default) prefers a "
            "crash-free high-reward rollout; longest_crash prefers a crash "
            "with the most steps so the collision is visible; fixed uses "
            "--video-episode."
        ),
    )
    parser.add_argument(
        "--video-episode",
        type=int,
        default=None,
        help="Episode index used when --video-mode fixed.",
    )

    return parser.parse_args()


def resolve_eval_run_and_model(args):
    if args.run_name:
        run = resolve_run_paths(args.run_name).ensure()
    elif args.model is not None:
        detected = find_run_from_model(args.model)
        if detected is not None:
            run = detected.ensure()
        else:
            run = resolve_run_paths(make_run_name(prefix="eval")).ensure()
    else:
        raise ValueError(
            "Provide --run-name (recommended) or --model. "
            "List runs with: python scripts/05_list_runs.py"
        )

    if args.model is not None:
        model_zip = model_zip_path(args.model)
    else:
        best = run.models / "best" / "best_model.zip"
        final = run.models / "dqn_highway.zip"
        if best.exists():
            model_zip = best
        elif final.exists():
            model_zip = final
        else:
            raise FileNotFoundError(
                f"No model found under {run.models}. "
                "Pass --model explicitly."
            )

    return run, model_zip


def select_video_episode(
    episode_results: list[dict],
    *,
    mode: str = "best_survivor",
    fixed_episode: int | None = None,
) -> int:
    if mode == "fixed":
        if fixed_episode is None:
            raise ValueError("--video-mode fixed requires --video-episode")
        if not 0 <= fixed_episode < len(episode_results):
            raise ValueError(
                f"--video-episode {fixed_episode} out of range "
                f"[0, {len(episode_results) - 1}]"
            )
        return int(fixed_episode)

    if mode == "longest_crash":
        crashes = [r for r in episode_results if r["crashed"]]
        if crashes:
            return int(max(crashes, key=lambda r: r["steps"])["episode"])
        # Fall through if somehow nothing crashed.
        mode = "best_survivor"

    survivors = [r for r in episode_results if not r["crashed"]]
    pool = survivors if survivors else episode_results
    best = max(pool, key=lambda r: r["total_reward"])
    return int(best["episode"])


def run_episode(
    *,
    env: gym.Env,
    policy_name: str,
    episode_seed: int,
    model: DQN | None = None,
    record_frames: bool = False,
    measure_inference: bool = False,
):
    observation, info = env.reset(seed=episode_seed)
    env.action_space.seed(episode_seed)

    terminated = False
    truncated = False
    rewards = []
    speeds = []
    actions = []
    frames = []
    inference_times_ms = []
    ttcs = []

    if record_frames:
        frames.append(env.render())

    while not (terminated or truncated):
        if policy_name == "random":
            action = env.action_space.sample()
        elif policy_name == "dqn":
            if measure_inference:
                if model.device.type == "cuda":
                    torch.cuda.synchronize()
                inference_start = time.perf_counter()

            action, _ = model.predict(observation, deterministic=True)

            if measure_inference:
                if model.device.type == "cuda":
                    torch.cuda.synchronize()
                inference_times_ms.append(
                    (time.perf_counter() - inference_start) * 1000
                )

            action = int(np.asarray(action).item())
        else:
            raise ValueError(f"Unknown policy: {policy_name}")

        observation, reward, terminated, truncated, info = env.step(action)
        vehicle = env.unwrapped.vehicle

        rewards.append(float(reward))
        speeds.append(float(vehicle.speed))
        actions.append(int(action))
        ttcs.append(float(info.get("ttc", float("inf"))))

        if record_frames:
            frames.append(env.render())

    vehicle = env.unwrapped.vehicle
    # An infinite TTC means "no leading vehicle closing in" and must not be
    # averaged in directly, so summaries use finite values only.
    finite_ttcs = [t for t in ttcs if np.isfinite(t)]
    crashed = bool(vehicle.crashed)

    result = {
        "seed": episode_seed,
        "steps": len(rewards),
        "total_reward": float(np.sum(rewards)),
        "mean_step_reward": float(np.mean(rewards)) if rewards else 0.0,
        "mean_reward": float(np.mean(rewards)) if rewards else 0.0,
        "mean_speed": float(np.mean(speeds)) if speeds else 0.0,
        "max_speed": float(np.max(speeds)) if speeds else 0.0,
        "crashed": crashed,
        "survived": not crashed,
        "min_ttc": float(np.min(finite_ttcs)) if finite_ttcs else None,
        "mean_ttc": (
            float(np.mean(np.clip(finite_ttcs, 0.0, TTC_REPORTING_CAP)))
            if finite_ttcs
            else None
        ),
        "ttc_violation_steps": sum(
            1 for t in ttcs if t < TTC_VIOLATION_THRESHOLD
        ),
        "terminated": bool(terminated),
        "truncated": bool(truncated),
        "action_counts": {
            ACTION_NAMES[action]: actions.count(action)
            for action in ACTION_NAMES
        },
    }
    return result, frames, inference_times_ms


def warmup_dqn(model: DQN, env: gym.Env, warmup_steps: int) -> None:
    if warmup_steps <= 0:
        return

    observation, _ = env.reset(seed=0)
    for _ in range(warmup_steps):
        action, _ = model.predict(observation, deterministic=True)
        observation, _, terminated, truncated, _ = env.step(
            int(np.asarray(action).item())
        )
        if terminated or truncated:
            observation, _ = env.reset()

    if model.device.type == "cuda":
        torch.cuda.synchronize()


def evaluate_policy(
    policy_name: str,
    args,
    model: DQN | None = None,
    video_path: Path | None = None,
):
    env = create_highway_env(
        duration=args.duration,
        vehicles=args.vehicles,
        render_mode="rgb_array",
        reward_profile=args.reward_profile,
    )

    if policy_name == "dqn" and model is not None:
        warmup_dqn(model, env, args.warmup)

    episode_results = []
    all_inference_times_ms = []

    for episode_index in range(args.episodes):
        episode_seed = args.seed + episode_index
        result, _, inference_times = run_episode(
            env=env,
            policy_name=policy_name,
            episode_seed=episode_seed,
            model=model,
            record_frames=False,
            measure_inference=(policy_name == "dqn"),
        )
        result["episode"] = episode_index
        episode_results.append(result)
        all_inference_times_ms.extend(inference_times)

        print(
            f"[{policy_name}] "
            f"episode={episode_index:02d} "
            f"reward={result['total_reward']:.2f} "
            f"step_rew={result['mean_step_reward']:.3f} "
            f"steps={result['steps']:03d} "
            f"speed={result['mean_speed']:.2f} "
            f"crashed={result['crashed']}"
        )

    if video_path is not None:
        video_episode = select_video_episode(
            episode_results,
            mode=args.video_mode,
            fixed_episode=args.video_episode,
        )
        video_seed = args.seed + video_episode
        result, frames, _ = run_episode(
            env=env,
            policy_name=policy_name,
            episode_seed=video_seed,
            model=model,
            record_frames=True,
            measure_inference=False,
        )
        write_video(video_path, frames)
        print(
            f"[{policy_name}] video episode={video_episode:02d} "
            f"seed={video_seed} crashed={result['crashed']} "
            f"steps={result['steps']} -> {video_path}"
        )
    else:
        video_episode = None

    env.close()

    collision_count = sum(int(r["crashed"]) for r in episode_results)
    total_rewards = [r["total_reward"] for r in episode_results]
    step_rewards = [r["mean_step_reward"] for r in episode_results]
    steps = [r["steps"] for r in episode_results]
    speeds = [r["mean_speed"] for r in episode_results]

    total_steps = sum(steps)
    violation_steps = sum(r["ttc_violation_steps"] for r in episode_results)
    min_ttcs = [
        r["min_ttc"] for r in episode_results if r["min_ttc"] is not None
    ]

    return {
        "policy": policy_name,
        "episodes": args.episodes,
        "mean_total_reward": float(np.mean(total_rewards)),
        "std_total_reward": float(np.std(total_rewards)),
        "mean_step_reward": float(np.mean(step_rewards)),
        "std_step_reward": float(np.std(step_rewards)),
        "mean_episode_steps": float(np.mean(steps)),
        "mean_speed": float(np.mean(speeds)),
        "collision_count": collision_count,
        "collision_rate": collision_count / args.episodes,
        "survival_rate": 1.0 - collision_count / args.episodes,
        "mean_min_ttc": float(np.mean(min_ttcs)) if min_ttcs else None,
        "ttc_violation_rate": (
            violation_steps / total_steps if total_steps else 0.0
        ),
        "ttc_violation_threshold_s": TTC_VIOLATION_THRESHOLD,
        "inference_warmup_steps": (
            args.warmup if policy_name == "dqn" else None
        ),
        "mean_inference_ms": (
            float(np.mean(all_inference_times_ms))
            if all_inference_times_ms
            else None
        ),
        "median_inference_ms": (
            float(np.median(all_inference_times_ms))
            if all_inference_times_ms
            else None
        ),
        "p95_inference_ms": (
            float(np.percentile(all_inference_times_ms, 95))
            if all_inference_times_ms
            else None
        ),
        "video": str(video_path) if video_path else None,
        "video_episode": video_episode,
        "episode_results": episode_results,
    }


def main():
    args = parse_args()
    run, model_zip = resolve_eval_run_and_model(args)

    metrics_path = run.metrics / "eval.json"
    random_video = run.videos / "eval_random.mp4"
    dqn_video = run.videos / "eval_dqn.mp4"

    if not model_zip.exists():
        raise FileNotFoundError(f"DQN model not found: {model_zip}")

    device = resolve_device(args.device)
    print(f"=== Run: {run.run_name} ===")
    print(f"Artifacts: {run.root}")
    print_rocm_info(device)

    print("\n=== Load DQN ===")
    model = DQN.load(str(model_zip), device=device)
    print("Model:", model_zip)
    print("Device:", model.device)

    print("\n=== Random Policy Evaluation ===")
    random_summary = evaluate_policy(
        policy_name="random",
        args=args,
        video_path=random_video,
    )

    print("\n=== DQN Policy Evaluation ===")
    dqn_summary = evaluate_policy(
        policy_name="dqn",
        args=args,
        model=model,
        video_path=dqn_video,
    )

    comparison = {
        "run_name": run.run_name,
        "run_dir": str(run.root),
        "environment": "highway-fast-v0",
        "model": str(model_zip),
        "device": device,
        "evaluation_seed_start": args.seed,
        "episodes": args.episodes,
        "eval_reward_profile": args.reward_profile,
        "eval_reward_profile_config": REWARD_PROFILES[args.reward_profile],
        "random": random_summary,
        "dqn": dqn_summary,
        "improvement": {
            "total_reward_difference": (
                dqn_summary["mean_total_reward"]
                - random_summary["mean_total_reward"]
            ),
            "step_reward_difference": (
                dqn_summary["mean_step_reward"]
                - random_summary["mean_step_reward"]
            ),
            "collision_rate_difference": (
                dqn_summary["collision_rate"]
                - random_summary["collision_rate"]
            ),
            "episode_steps_difference": (
                dqn_summary["mean_episode_steps"]
                - random_summary["mean_episode_steps"]
            ),
            "survival_rate_difference": (
                dqn_summary["survival_rate"] - random_summary["survival_rate"]
            ),
            "ttc_violation_rate_difference": (
                dqn_summary["ttc_violation_rate"]
                - random_summary["ttc_violation_rate"]
            ),
        },
    }

    metrics_path.write_text(
        json.dumps(comparison, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    write_run_meta(
        run,
        stage="eval_done",
        argv=sys.argv,
        params={
            "eval_episodes": args.episodes,
            "eval_seed": args.seed,
            "eval_device": device,
            "eval_model": str(model_zip),
        },
        extra={
            "eval_metrics": str(metrics_path),
            "eval_random_video": str(random_video),
            "eval_dqn_video": str(dqn_video),
        },
    )

    print("\n=== Comparison ===")
    print(
        f"Random total reward: {random_summary['mean_total_reward']:.2f}  "
        f"(step={random_summary['mean_step_reward']:.3f})"
    )
    print(
        f"DQN total reward:    {dqn_summary['mean_total_reward']:.2f}  "
        f"(step={dqn_summary['mean_step_reward']:.3f})"
    )
    print(
        f"Random collision rate: {random_summary['collision_rate']:.1%}"
    )
    print(
        f"DQN collision rate:    {dqn_summary['collision_rate']:.1%}"
    )
    print(
        f"DQN survival rate:     {dqn_summary['survival_rate']:.1%}  "
        f"(random {random_summary['survival_rate']:.1%})"
    )
    print(
        f"DQN TTC violation:     {dqn_summary['ttc_violation_rate']:.1%} "
        f"of steps below {TTC_VIOLATION_THRESHOLD}s  "
        f"(random {random_summary['ttc_violation_rate']:.1%})"
    )
    if dqn_summary["mean_min_ttc"] is not None:
        print(
            f"DQN mean min TTC:      {dqn_summary['mean_min_ttc']:.2f} s"
        )
    print(
        f"DQN mean/median/P95 inference: "
        f"{dqn_summary['mean_inference_ms']:.3f} / "
        f"{dqn_summary['median_inference_ms']:.3f} / "
        f"{dqn_summary['p95_inference_ms']:.3f} ms"
    )

    print(f"\nRun dir:      {run.root}")
    print(f"Metrics:      {metrics_path}")
    print(f"Random video: {random_video}")
    print(f"DQN video:    {dqn_video}")


if __name__ == "__main__":
    main()
