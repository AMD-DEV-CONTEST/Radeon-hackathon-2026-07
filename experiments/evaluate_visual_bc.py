"""Closed-loop Genesis evaluation for an RGB + proprioception BC policy."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import torch
import yaml

from algorithms.vision_actor_critic import VisualActorCritic
from experiments.evaluate import evaluate_success_rate
from simulation.randomization import TaskRandomizationConfig, make_domain_randomizer
from simulation.task_factory import PickPlaceTaskConfig, initialize_genesis, make_pick_place_env


def _proprio(observation: dict[str, np.ndarray]) -> np.ndarray:
    return np.concatenate((observation["joint_position"], observation["joint_velocity"], observation["end_effector_pose"])).astype(np.float32)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("configs/evaluate_visual_bc_smoke.yaml"))
    args = parser.parse_args()
    config = yaml.safe_load(args.config.read_text())
    task_config = yaml.safe_load(Path(config["task_config"]).read_text())
    initialize_genesis(backend=task_config["genesis_backend"])
    payload = torch.load(config["checkpoint"], map_location=config["device"], weights_only=False)
    model = VisualActorCritic(
        image_height=payload["image_height"], image_width=payload["image_width"],
        proprio_dim=payload["proprio_dim"], action_dim=payload["action_dim"],
    ).to(config["device"]).eval()
    model.load_state_dict(payload["state_dict"])

    def env_factory():
        randomizer = make_domain_randomizer(
            TaskRandomizationConfig(**task_config["domain_randomization"]), seed=int(config["seed"])
        )
        return make_pick_place_env(config=PickPlaceTaskConfig(**task_config["task"]), domain_randomizer=randomizer)

    @torch.inference_mode()
    def policy(observation: dict[str, np.ndarray]) -> np.ndarray:
        rgb = torch.as_tensor(
            np.ascontiguousarray(observation["camera"]), device=config["device"]
        ).unsqueeze(0)
        proprio = torch.as_tensor(_proprio(observation), device=config["device"]).unsqueeze(0)
        predicted = model.mean_action(rgb, proprio).squeeze(0).cpu().numpy().astype(np.float32)
        current = np.asarray(observation["joint_position"], dtype=np.float32)
        # BC predicts absolute qpos targets.  A slew-rate limiter prevents a
        # poorly extrapolated visual prediction from injecting infeasible joint
        # jumps into Genesis' rigid constraint solver.
        predicted = np.where(np.isfinite(predicted), predicted, 0.0)
        max_delta = float(config.get("max_joint_delta", 0.05))
        if payload.get("action_representation") == "normalized_delta_qpos":
            action_mean = payload["action_delta_mean"].detach().cpu().numpy().astype(np.float32)
            action_std = payload["action_delta_std"].detach().cpu().numpy().astype(np.float32)
            action = current + np.clip(predicted * action_std + action_mean, -max_delta, max_delta)
        elif payload.get("action_representation") == "delta_qpos":
            action = current + np.clip(predicted, -max_delta, max_delta)
        else:
            action = current + np.clip(predicted - current, -max_delta, max_delta)
        action[-2:] = np.clip(action[-2:], 0.0, 0.04)
        return action

    result = {"visual_bc": evaluate_success_rate(env_factory(), policy, int(config["episodes"]))}
    if config.get("results_path"):
        output = Path(config["results_path"])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2) + "\n")
    print(result)


if __name__ == "__main__":
    main()
