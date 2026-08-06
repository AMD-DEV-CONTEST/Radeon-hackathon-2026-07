"""Evaluate RGB task-state estimation followed by the calibrated IK expert."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import torch
import yaml

from algorithms.vision_state_estimator import VisualTaskStateEstimator
from controller.pick_place_expert import ExpertConfig, PickPlaceIKExpert
from simulation.randomization import TaskRandomizationConfig, make_domain_randomizer
from simulation.task_factory import PickPlaceTaskConfig, initialize_genesis, make_pick_place_env


def _proprio(observation: dict[str, np.ndarray]) -> np.ndarray:
    return np.concatenate((
        observation["joint_position"], observation["joint_velocity"], observation["end_effector_pose"],
    )).astype(np.float32)


def _estimated_observation(
    observation: dict[str, np.ndarray], estimated_positions: np.ndarray,
) -> dict[str, np.ndarray]:
    """Replace only hidden task positions; orientation is irrelevant to this task."""
    estimated = dict(observation)
    object_pose = np.array(observation["object_pose"], dtype=np.float32, copy=True)
    target_pose = np.array(observation["target_pose"], dtype=np.float32, copy=True)
    object_pose[:3], target_pose[:3] = estimated_positions[:3], estimated_positions[3:]
    estimated["object_pose"], estimated["target_pose"] = object_pose, target_pose
    return estimated


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("configs/evaluate_visual_ik.yaml"))
    args = parser.parse_args()
    config = yaml.safe_load(args.config.read_text())
    task_yaml = yaml.safe_load(Path(config["task_config"]).read_text())
    initialize_genesis(backend=task_yaml["genesis_backend"])
    payload = torch.load(config["checkpoint"], map_location=config["device"], weights_only=False)
    model = VisualTaskStateEstimator(
        image_height=payload["image_height"], image_width=payload["image_width"],
        proprio_dim=payload["proprio_dim"],
    ).to(config["device"]).eval()
    model.load_state_dict(payload["state_dict"])
    position_mean = payload["position_mean"].detach().cpu().numpy().astype(np.float32)
    position_std = payload["position_std"].detach().cpu().numpy().astype(np.float32)
    randomizer = make_domain_randomizer(
        TaskRandomizationConfig(**task_yaml["domain_randomization"]), seed=int(config["seed"]),
    )
    env = make_pick_place_env(
        config=PickPlaceTaskConfig(**task_yaml["task"]), domain_randomizer=randomizer,
    )
    expert = PickPlaceIKExpert(env, config=ExpertConfig(**task_yaml["expert"]))
    successes = 0
    squared_error_sum = np.zeros(6, dtype=np.float64)
    initial_squared_error_sum = np.zeros(6, dtype=np.float64)
    prediction_count = 0
    perception_ema = float(config.get("perception_ema", 0.25))
    grasp_offset = np.asarray(task_yaml["task"]["grasp_offset"], dtype=np.float32)
    for episode in range(int(config["episodes"])):
        observation, _ = env.reset(seed=int(config["seed"]) + episode)
        expert.reset()
        terminated = truncated = False
        info: dict[str, object] = {}
        filtered_object: np.ndarray | None = None
        frozen_target: np.ndarray | None = None
        while not (terminated or truncated):
            with torch.inference_mode():
                rgb = torch.as_tensor(np.ascontiguousarray(observation["camera"]), device=config["device"]).unsqueeze(0)
                proprio = torch.as_tensor(_proprio(observation), device=config["device"]).unsqueeze(0)
                estimate = model(rgb, proprio).squeeze(0).cpu().numpy() * position_std + position_mean
            truth = np.concatenate((observation["object_pose"][:3], observation["target_pose"][:3]))
            squared_error_sum += np.square(estimate - truth)
            if filtered_object is None:
                initial_squared_error_sum += np.square(estimate - truth)
                frozen_target = estimate[3:].astype(np.float32, copy=True)
                filtered_object = estimate[:3].astype(np.float32, copy=True)
            elif env.is_grasped:
                # Once the contact-confirmed latch is active, perception need
                # not re-estimate an often-occluded object. Propagate it from
                # proprioception and the known grasp geometry instead.
                filtered_object = observation["end_effector_pose"][:3] + grasp_offset
            else:
                filtered_object = (
                    (1.0 - perception_ema) * filtered_object + perception_ema * estimate[:3]
                ).astype(np.float32)
            prediction_count += 1
            controller_positions = np.concatenate((filtered_object, frozen_target))
            action = expert.action(_estimated_observation(observation, controller_positions))
            observation, _, terminated, truncated, info = env.step(action)
        successes += bool(info.get("is_success", False))
    rmse = np.sqrt(squared_error_sum / max(prediction_count, 1))
    initial_rmse = np.sqrt(initial_squared_error_sum / int(config["episodes"]))
    print({
        "visual_ik": {
            "success_rate": successes / int(config["episodes"]),
            "object_position_rmse_m": float(np.linalg.norm(rmse[:3])),
            "target_position_rmse_m": float(np.linalg.norm(rmse[3:])),
            "initial_object_position_rmse_m": float(np.linalg.norm(initial_rmse[:3])),
            "initial_target_position_rmse_m": float(np.linalg.norm(initial_rmse[3:])),
        }
    })


if __name__ == "__main__":
    main()
