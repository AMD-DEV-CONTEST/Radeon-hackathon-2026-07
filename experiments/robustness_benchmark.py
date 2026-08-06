"""Held-out robustness benchmark for the contact-confirmed IK controller."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from controller.pick_place_expert import ExpertConfig, PickPlaceIKExpert
from simulation.perturbations import ActionNoiseWrapper, ObservationNoiseWrapper
from simulation.randomization import TaskRandomizationConfig, make_domain_randomizer
from simulation.task_factory import PickPlaceTaskConfig, initialize_genesis, make_pick_place_env


def _evaluate_ik_scenario(
    scenario: dict[str, Any], common: dict[str, Any], *, seed: int
) -> dict[str, float]:
    randomizer = make_domain_randomizer(
        TaskRandomizationConfig(**scenario["domain_randomization"]), seed=seed,
    )
    env = make_pick_place_env(
        config=PickPlaceTaskConfig(**common["task"]), domain_randomizer=randomizer,
    )
    observation_noise = scenario.get("observation_noise", {})
    action_noise_std = float(scenario.get("action_noise", {}).get("joint_position_std", 0.0))
    if observation_noise:
        env = ObservationNoiseWrapper(env, observation_noise, seed=seed + 1)
    if action_noise_std:
        env = ActionNoiseWrapper(env, action_noise_std, seed=seed + 2)
    expert = PickPlaceIKExpert(env.unwrapped, config=ExpertConfig(**common["expert"]))
    successes = grasped = lifted = 0
    lengths: list[int] = []
    final_distances: list[float] = []
    for episode in range(int(scenario["episodes"])):
        observation, _ = env.reset(seed=seed + episode)
        expert.reset()
        terminated = truncated = False
        info: dict[str, Any] = {}
        while not (terminated or truncated):
            observation, _, terminated, truncated, info = env.step(expert.action(observation))
        successes += int(bool(info["is_success"]))
        grasped += int(bool(info["is_grasped"]) or int(info.get("max_consecutive_dual_finger_contact_steps", 0)) > 0)
        lifted += int(bool(info["object_was_lifted"]))
        lengths.append(int(info["episode_step"]))
        final_distances.append(float(info["distance_to_goal"]))
    episode_count = int(scenario["episodes"])
    return {
        "success_rate": successes / episode_count,
        "grasp_evidence_rate": grasped / episode_count,
        "lift_rate": lifted / episode_count,
        "mean_episode_length": float(np.mean(lengths)),
        "mean_final_distance_m": float(np.mean(final_distances)),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run held-out robustness scenarios for IK.")
    parser.add_argument("--config", type=Path, default=Path("configs/robustness_benchmark.yaml"))
    args = parser.parse_args()
    config = yaml.safe_load(args.config.read_text())
    initialize_genesis(backend=config["genesis_backend"])
    results: dict[str, Any] = {"seed": int(config["seed"]), "policy": "contact_confirmed_ik", "scenarios": {}}
    for index, scenario in enumerate(config["scenarios"]):
        name = scenario["name"]
        results["scenarios"][name] = _evaluate_ik_scenario(
            scenario, config, seed=int(config["seed"]) + index * 10_000,
        )
        print(f"{name}: {results['scenarios'][name]}")
    output = Path(config["results_path"])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(results, indent=2) + "\n")
    print(f"Robustness benchmark written to {output}")


if __name__ == "__main__":
    main()
