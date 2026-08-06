"""Collect deterministic Franka IK demonstrations for imitation and distillation."""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml

from controller.pick_place_expert import ExpertConfig, PickPlaceIKExpert, collect_expert_demonstrations
from simulation.randomization import TaskRandomizationConfig, make_domain_randomizer
from simulation.task_factory import PickPlaceTaskConfig, initialize_genesis, make_pick_place_env


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect phase-based IK demonstrations.")
    parser.add_argument("--config", type=Path, default=Path("configs/collect_expert.yaml"))
    parser.add_argument("--episodes", type=int, help="Override the configured episode count for a smoke run.")
    parser.add_argument("--output-dir", type=Path, help="Override the output directory.")
    args = parser.parse_args()
    config = yaml.safe_load(args.config.read_text())

    initialize_genesis(backend=config["genesis_backend"])
    randomizer = None
    if "domain_randomization" in config:
        randomizer = make_domain_randomizer(
            TaskRandomizationConfig(**config["domain_randomization"]), seed=int(config["seed"])
        )
    env = make_pick_place_env(config=PickPlaceTaskConfig(**config["task"]), domain_randomizer=randomizer)
    expert = PickPlaceIKExpert(env, config=ExpertConfig(**config["expert"]))
    metadata = collect_expert_demonstrations(
        env,
        expert,
        episodes=args.episodes if args.episodes is not None else int(config["episodes"]),
        output_dir=args.output_dir if args.output_dir is not None else config["output_dir"],
        seed=int(config["seed"]),
    )
    print("Expert collection completed:")
    for name, value in metadata.items():
        print(f"  {name}: {value}")


if __name__ == "__main__":
    main()
