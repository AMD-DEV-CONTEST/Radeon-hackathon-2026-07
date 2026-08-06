"""Run the frozen baseline and write stage-level failure diagnostics."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import numpy as np

from .common import initialize
from .env import PlumResidualEnv, ResidualEnvConfig


def main() -> None:
    parser = argparse.ArgumentParser(description="Diagnose frozen SmolVLA plum failures by task stage.")
    parser.add_argument("--policy-path", required=True)
    parser.add_argument("--repo-id", required=True)
    parser.add_argument("--dataset-root", required=True)
    parser.add_argument("--episodes", type=int, default=100)
    parser.add_argument("--seed", type=int, default=2000)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--jitter", type=float, default=0.03)
    parser.add_argument("--out", default="outputs/rl/plum_diagnostics_100ep.json")
    args = parser.parse_args()

    bundle, policy = initialize(args.policy_path, args.repo_id, args.dataset_root, args.device)
    env = PlumResidualEnv(
        bundle,
        policy,
        ResidualEnvConfig(jitter=args.jitter, terminate_on_drop=False, task_mode="full"),
    )
    rows = []
    zero = np.zeros(9, dtype=np.float32)
    for episode in range(args.episodes):
        seed = args.seed + episode
        _, _ = env.reset(seed)
        done = truncated = False
        info = {}
        total_reward = 0.0
        while not (done or truncated):
            _, reward, done, truncated, info = env.step(zero)
            total_reward += reward
        row = {
            "episode": episode,
            "seed": seed,
            "success": bool(info["success"]),
            "steps": int(info["policy_steps"]),
            "return": total_reward,
            **env.tracker.summary(),
        }
        rows.append(row)
        print(f"[diagnose] ep={episode:03d} seed={seed} stage={row['failure_stage']} success={row['success']}")

    counts = Counter(row["failure_stage"] for row in rows)
    output = {
        "episodes": args.episodes,
        "n_success": sum(row["success"] for row in rows),
        "failure_stages": dict(counts),
        "params": vars(args),
        "episodes_detail": rows,
    }
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(output, indent=2))
    print(f"[diagnose] results -> {path}")


if __name__ == "__main__":
    main()
