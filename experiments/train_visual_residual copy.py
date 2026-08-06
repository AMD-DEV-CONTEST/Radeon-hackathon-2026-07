"""Train PPO residual actions over calibrated visual-servo control."""

from __future__ import annotations

import argparse
import json
from functools import partial
from pathlib import Path

import gymnasium as gym
import numpy as np
import torch
import yaml

from algorithms.ppo_trainer import CleanRLPPOTrainer, PPOConfig
from controller.color_marker_perception import ColorMarkerPerception, MarkerCalibration
from controller.pick_place_expert import ExpertConfig, PickPlaceIKExpert
from controller.visual_servo import VisualServoConfig, VisualServoController
from controller.visual_servo_residual_wrapper import VisualServoResidualWrapper
from simulation.randomization import TaskRandomizationConfig, make_domain_randomizer
from simulation.task_factory import PickPlaceTaskConfig, initialize_genesis, make_pick_place_env


def _factory(config: dict, worker_index: int):
    task_yaml = yaml.safe_load(Path(config["task_config"]).read_text())
    randomizer = make_domain_randomizer(
        TaskRandomizationConfig(**task_yaml["domain_randomization"]), seed=int(config["seed"]) + worker_index,
    )
    env = make_pick_place_env(config=PickPlaceTaskConfig(**task_yaml["task"]), domain_randomizer=randomizer)
    servo_config = dict(config.get("visual_servo", {}))
    if config.get("grasp_offset_calibration"):
        servo_config["grasp_offset"] = tuple(json.loads(Path(config["grasp_offset_calibration"]).read_text())["median_offset"])
    controller = VisualServoController(
        env, PickPlaceIKExpert(env, config=ExpertConfig(**task_yaml["expert"])),
        ColorMarkerPerception(MarkerCalibration.load(config["calibration"])),
        config=VisualServoConfig(**servo_config),
    )
    return VisualServoResidualWrapper(env, controller, residual_scale=float(config["residual_scale"]))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("configs/train_visual_residual_smoke.yaml"))
    args = parser.parse_args()
    config = yaml.safe_load(args.config.read_text())
    np.random.seed(int(config["seed"])); torch.manual_seed(int(config["seed"]))
    task_yaml = yaml.safe_load(Path(config["task_config"]).read_text())
    initialize_genesis(backend=task_yaml["genesis_backend"])
    env = gym.vector.SyncVectorEnv([
        partial(_factory, config, worker_index) for worker_index in range(int(config["num_envs"]))
    ])
    try:
        trainer = CleanRLPPOTrainer(
            int(np.prod(env.single_observation_space.shape)), int(np.prod(env.single_action_space.shape)),
            config=PPOConfig(**config["ppo"]), residual_scale=float(config["residual_scale"]),
            device=config["device"], log_dir=config["log_dir"],
        )
        if config.get("resume"):
            trainer.load_checkpoint(config["resume"])
        metrics = trainer.train(
            env, lambda observation: torch.zeros_like(observation[:, : env.single_action_space.shape[0]]),
            int(config["total_timesteps"]),
        )
        checkpoint = trainer.save_checkpoint(
            config["checkpoint"], global_step=int(config["total_timesteps"]),
            extra={"metrics": metrics[-1], "residual_scale": float(config["residual_scale"]), "base_policy": "color_visual_servo"},
        )
        print(f"Visual residual PPO completed. Checkpoint: {checkpoint}")
    finally:
        env.close()


if __name__ == "__main__":
    main()
