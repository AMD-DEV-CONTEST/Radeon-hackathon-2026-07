"""Configuration-driven entry point for IK-guided residual PPO training."""

from __future__ import annotations

import argparse
from functools import partial
from pathlib import Path

import numpy as np
import torch
import yaml

from algorithms.ppo_trainer import CleanRLPPOTrainer, PPOConfig
from experiments.train import make_residual_vector_env
from simulation.randomization import TaskRandomizationConfig, make_domain_randomizer
from simulation.task_factory import PickPlaceTaskConfig, initialize_genesis, make_pick_place_env


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("configs/train.yaml"))
    args = parser.parse_args()
    config = yaml.safe_load(args.config.read_text())
    _seed_everything(int(config["seed"]))
    initialize_genesis(backend=config["genesis_backend"])
    task = PickPlaceTaskConfig(**config["task"])
    randomization = config.get("domain_randomization")
    factories = []
    for worker_index in range(int(config["num_envs"])):
        randomizer = None
        if randomization is not None:
            randomizer = make_domain_randomizer(
                TaskRandomizationConfig(**randomization), seed=int(config["seed"]) + worker_index
            )
        factories.append(partial(make_pick_place_env, config=task, domain_randomizer=randomizer))
    env = make_residual_vector_env(factories, residual_scale=float(config["residual_scale"]))
    try:
        trainer = CleanRLPPOTrainer(
            int(np.prod(env.single_observation_space.shape)),
            int(np.prod(env.single_action_space.shape)),
            config=PPOConfig(**config["ppo"]),
            residual_scale=float(config["residual_scale"]),
            device=config["device"],
            log_dir=config["log_dir"],
        )
        if config.get("resume"):
            trainer.load_checkpoint(config["resume"])
        # IK fusion runs inside IKResidualWrapper. PPO therefore emits Δa directly.
        metrics = trainer.train(
            env, lambda observation: torch.zeros_like(observation[:, : env.single_action_space.shape[0]]),
            int(config["total_timesteps"]),
        )
        checkpoint = trainer.save_checkpoint(
            config["checkpoint"],
            global_step=int(config["total_timesteps"]),
            extra={"metrics": metrics[-1], "residual_scale": float(config["residual_scale"])},
        )
        print(f"Training completed. Checkpoint: {checkpoint}")
    finally:
        env.close()


def _seed_everything(seed: int) -> None:
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


if __name__ == "__main__":
    main()
