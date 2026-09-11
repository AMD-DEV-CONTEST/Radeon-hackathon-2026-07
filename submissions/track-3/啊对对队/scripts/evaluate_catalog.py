from __future__ import annotations

import argparse
from dataclasses import asdict, replace
import json
from pathlib import Path

from parcel_sorter.config import load_config
from parcel_sorter.genesis_env import GenesisParcelEnv
from parcel_sorter.metrics import MetricsAccumulator
from parcel_sorter.provenance import runtime_report
from parcel_sorter.randomization import DomainRandomizer
from parcel_sorter.runner import run_expert_episode


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate every configured parcel geometry as a separate stratum"
    )
    parser.add_argument("--config", default="configs/catalog_v1.toml")
    parser.add_argument("--backend", choices=("rocm", "cuda", "cpu"), default="rocm")
    parser.add_argument("--episodes-per-profile", type=int, default=3)
    parser.add_argument(
        "--profile",
        action="append",
        dest="selected_profiles",
        help="evaluate only this profile id; repeat the flag to select multiple profiles",
    )
    parser.add_argument("--include-evaluation-only", action="store_true")
    parser.add_argument(
        "--tri-suction",
        action="store_true",
        help="enable the physical three-cup suction end effector",
    )
    parser.add_argument("--output", default="outputs/catalog-v1")
    args = parser.parse_args()
    if args.episodes_per_profile < 1:
        parser.error("episodes-per-profile must be positive")

    config = load_config(args.config)
    if args.tri_suction:
        config = replace(
            config,
            task=replace(config.task, tri_suction_enabled=True),
        )
        config.validate()
    known_profile_ids = {profile.profile_id for profile in config.parcel_profiles}
    catalog_profile_index = {
        profile.profile_id: index for index, profile in enumerate(config.parcel_profiles)
    }
    selected_profile_ids = set(args.selected_profiles or ())
    unknown_profile_ids = sorted(selected_profile_ids - known_profile_ids)
    if unknown_profile_ids:
        parser.error(f"unknown parcel profile(s): {', '.join(unknown_profile_ids)}")
    profiles = tuple(
        profile
        for profile in config.parcel_profiles
        if (args.include_evaluation_only or not profile.evaluation_only)
        and (not selected_profile_ids or profile.profile_id in selected_profile_ids)
    )
    if not profiles:
        parser.error("the selected config has no parcel profiles to evaluate")

    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    randomizer = DomainRandomizer(config.randomization, config.seed, config.parcel_profiles)
    profile_results = {}
    episodes = []

    for profile in profiles:
        metrics = MetricsAccumulator()
        for local_index in range(args.episodes_per_profile):
            episode_index = catalog_profile_index[profile.profile_id] * 1_000_000 + local_index
            sample = randomizer.sample_profile(profile.profile_id, episode_index)
            with GenesisParcelEnv(config, sample, backend=args.backend) as env:
                report = run_expert_episode(env, config, sample, episode_index)
            metrics.add(report.result)
            episodes.append(
                {
                    "profile_id": profile.profile_id,
                    "handling_class": profile.handling_class,
                    **report.to_dict(),
                }
            )
            print(
                json.dumps(
                    {
                        "profile": profile.profile_id,
                        "episode": local_index,
                        "success": report.result.success,
                        "terminal_stage": report.terminal_stage,
                    },
                    ensure_ascii=False,
                )
            )
        profile_results[profile.profile_id] = {
            "profile": asdict(profile),
            "summary": metrics.summary(),
        }

    payload = {
        "runtime": runtime_report(),
        "config": asdict(config),
        "episodes_per_profile": args.episodes_per_profile,
        "profiles": profile_results,
        "episodes": episodes,
    }
    result_path = output / "catalog-evaluation.json"
    with result_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    print(result_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
