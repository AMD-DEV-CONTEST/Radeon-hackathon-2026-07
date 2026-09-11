from __future__ import annotations

import argparse
import json
from pathlib import Path

from parcel_sorter.config import load_config
from parcel_sorter.genesis_env import GenesisParcelEnv
from parcel_sorter.metrics import MetricsAccumulator
from parcel_sorter.provenance import runtime_report
from parcel_sorter.robustness import PROFILES, sample_for_profile
from parcel_sorter.runner import run_expert_episode


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate nominal, randomized, and unseen parcel conditions")
    parser.add_argument("--config", default="configs/baseline.toml")
    parser.add_argument("--backend", choices=("rocm", "cuda", "cpu"), default="rocm")
    parser.add_argument("--episodes-per-profile", type=int, default=5)
    parser.add_argument("--output", default=None)
    parser.add_argument("--record-failures", action="store_true")
    args = parser.parse_args()
    if args.episodes_per_profile < 1:
        parser.error("episodes-per-profile must be positive")

    config = load_config(args.config)
    output = Path(args.output or config.output.root_dir) / "robustness"
    output.mkdir(parents=True, exist_ok=True)
    summaries = {}
    all_episodes = []

    for profile_index, profile in enumerate(PROFILES):
        metrics = MetricsAccumulator()
        for local_index in range(args.episodes_per_profile):
            episode_index = profile_index * 1_000_000 + local_index
            sample = sample_for_profile(config, episode_index, profile)
            with GenesisParcelEnv(config, sample, backend=args.backend) as env:
                report = run_expert_episode(env, config, sample, episode_index)
            metrics.add(report.result)
            episode_payload = {"profile": profile, **report.to_dict()}
            all_episodes.append(episode_payload)
            if args.record_failures and not report.result.success:
                video_path = output / "failure_videos" / f"{profile}_{local_index:04d}.mp4"
                with GenesisParcelEnv(config, sample, backend=args.backend, video_path=video_path) as env:
                    run_expert_episode(env, config, sample, episode_index)
        summaries[profile] = metrics.summary()

    payload = {
        "runtime": runtime_report(),
        "episodes_per_profile": args.episodes_per_profile,
        "profiles": summaries,
        "episodes": all_episodes,
    }
    with (output / "robustness.json").open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    print(json.dumps(summaries, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
