"""Render same-seed contrast videos for README / demo comparison.

The default evaluate.py video picker prefers high-reward survivors, so random
and baseline clips often show no crash even when those policies crash most of
the time. This script re-records one shared traffic seed for:

- random
- baseline DQN
- ttc DQN

Pick a seed where baseline/random crash and ttc survives when possible.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from common import (
    create_highway_env,
    print_rocm_info,
    resolve_device,
    setup_headless_runtime,
    write_video,
)

setup_headless_runtime()

import numpy as np
import torch
from stable_baselines3 import DQN

# Reuse the episode runner from evaluate.py
sys.path.insert(0, str(Path(__file__).resolve().parent))
from importlib import import_module

evaluate = import_module("03_evaluate")  # noqa: E402


DEFAULT_BASELINE = Path(
    "/persistent/PhysicalAI-ROCm-Quickstart/demo1_highway_dqn/"
    "outputs/runs/abl_baseline_s42/models/best/best_model.zip"
)
DEFAULT_TTC = Path("models/best_ttc_s42.zip")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Render same-seed crash/survive contrast videos."
    )
    parser.add_argument("--seed", type=int, default=102)
    parser.add_argument("--duration", type=int, default=20)
    parser.add_argument("--vehicles", type=int, default=30)
    parser.add_argument(
        "--device",
        choices=("auto", "cuda", "cpu"),
        default="auto",
    )
    parser.add_argument(
        "--baseline-model",
        type=Path,
        default=DEFAULT_BASELINE,
    )
    parser.add_argument(
        "--ttc-model",
        type=Path,
        default=DEFAULT_TTC,
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("videos"),
    )
    parser.add_argument(
        "--also-search",
        action="store_true",
        help=(
            "Scan seeds [seed, seed+29] and pick the first where random and "
            "baseline crash while ttc survives."
        ),
    )
    return parser.parse_args()


def render_one(env, policy_name, episode_seed, model, out_path: Path):
    result, frames, _ = evaluate.run_episode(
        env=env,
        policy_name=policy_name,
        episode_seed=episode_seed,
        model=model,
        record_frames=True,
        measure_inference=False,
    )
    write_video(out_path, frames)
    print(
        f"{policy_name:8s} seed={episode_seed} "
        f"crashed={result['crashed']} steps={result['steps']:3d} "
        f"reward={result['total_reward']:.1f} -> {out_path}"
    )
    return result


def probe(env, policy_name, episode_seed, model):
    result, _, _ = evaluate.run_episode(
        env=env,
        policy_name=policy_name,
        episode_seed=episode_seed,
        model=model,
        record_frames=False,
        measure_inference=False,
    )
    return result


def find_contrast_seed(env, baseline, ttc, start_seed: int) -> int:
    for offset in range(30):
        seed = start_seed + offset
        r = probe(env, "random", seed, None)
        b = probe(env, "dqn", seed, baseline)
        t = probe(env, "dqn", seed, ttc)
        print(
            f"probe seed={seed}: "
            f"random_crash={r['crashed']} "
            f"baseline_crash={b['crashed']} "
            f"ttc_crash={t['crashed']}"
        )
        if r["crashed"] and b["crashed"] and not t["crashed"]:
            return seed
    raise RuntimeError(
        "No seed in range where random+baseline crash and ttc survives"
    )


def main():
    args = parse_args()
    device = resolve_device(args.device)
    print_rocm_info(device)

    if not args.baseline_model.exists():
        raise FileNotFoundError(args.baseline_model)
    if not args.ttc_model.exists():
        raise FileNotFoundError(args.ttc_model)

    baseline = DQN.load(str(args.baseline_model), device=device)
    ttc = DQN.load(str(args.ttc_model), device=device)

    env = create_highway_env(
        duration=args.duration,
        vehicles=args.vehicles,
        render_mode="rgb_array",
        reward_profile="baseline",
    )

    seed = args.seed
    if args.also_search:
        seed = find_contrast_seed(env, baseline, ttc, args.seed)
        print(f"Selected contrast seed: {seed}")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    results = {}
    results["random"] = render_one(
        env,
        "random",
        seed,
        None,
        args.output_dir / "random_policy.mp4",
    )
    results["baseline"] = render_one(
        env,
        "dqn",
        seed,
        baseline,
        args.output_dir / "baseline_policy.mp4",
    )
    results["ttc"] = render_one(
        env,
        "dqn",
        seed,
        ttc,
        args.output_dir / "ttc_policy.mp4",
    )

    # Also keep explicit crash/survive filenames for the demo reel.
    render_one(
        env,
        "random",
        seed,
        None,
        args.output_dir / "random_crash.mp4",
    )
    render_one(
        env,
        "dqn",
        seed,
        baseline,
        args.output_dir / "baseline_crash.mp4",
    )
    render_one(
        env,
        "dqn",
        seed,
        ttc,
        args.output_dir / "ttc_survive.mp4",
    )

    meta = {
        "seed": seed,
        "note": (
            "Same HighwayEnv seed for all clips so traffic is comparable. "
            "Prefer seeds where random/baseline crash and ttc survives."
        ),
        "results": {
            name: {
                "crashed": r["crashed"],
                "steps": r["steps"],
                "total_reward": r["total_reward"],
                "mean_speed": r["mean_speed"],
                "action_counts": r["action_counts"],
            }
            for name, r in results.items()
        },
    }
    meta_path = args.output_dir / "contrast_seed.json"
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print("Wrote", meta_path)

    env.close()


if __name__ == "__main__":
    main()
