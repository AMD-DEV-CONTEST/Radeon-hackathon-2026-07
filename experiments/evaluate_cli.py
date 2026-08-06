"""Evaluate deterministic IK and IK-guided residual PPO under one protocol."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import gymnasium as gym
import numpy as np
import torch
import yaml
from gymnasium.spaces.utils import flatdim

from algorithms.ppo_trainer import CleanRLPPOTrainer, PPOConfig
from controller.pick_place_expert import PickPlaceIKExpert
from controller.residual_wrapper import IKResidualWrapper
from experiments.evaluate import compare_policies
from simulation.randomization import TaskRandomizationConfig, make_domain_randomizer
from simulation.task_factory import PickPlaceTaskConfig, initialize_genesis, make_pick_place_env


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("configs/evaluate.yaml"))
    args = parser.parse_args()
    config = yaml.safe_load(args.config.read_text())
    np.random.seed(int(config["seed"]))
    initialize_genesis(backend=config["genesis_backend"])
    task = PickPlaceTaskConfig(**config["task"])
    randomization = config.get("domain_randomization")

    def make_randomizer():
        if randomization is None:
            return None
        # Each policy receives the same deterministic sequence of test tasks.
        return make_domain_randomizer(
            TaskRandomizationConfig(**randomization), seed=int(config["seed"])
        )

    def make_ik_env():
        return make_pick_place_env(config=task, domain_randomizer=make_randomizer())

    sample = make_ik_env()
    state_dim = int(flatdim(sample.observation_space))
    action_dim = int(np.prod(sample.action_space.shape))
    sample.scene.reset()
    checkpoint = torch.load(config["checkpoint"], map_location=config["device"], weights_only=False)
    checkpoint_scale = float(checkpoint.get("extra", {}).get("residual_scale", config.get("residual_scale", 0.10)))
    trainer = CleanRLPPOTrainer(
        state_dim, action_dim, config=PPOConfig(**checkpoint["config"]),
        residual_scale=checkpoint_scale, device=config["device"],
    )
    trainer.load_checkpoint(config["checkpoint"])

    def ik_policy(observation):
        # The evaluator creates one expert per episode through the closure cache.
        return np.asarray(observation["joint_position"], dtype=np.float32)

    def make_residual_env():
        env = make_pick_place_env(config=task, domain_randomizer=make_randomizer())
        return gym.wrappers.FlattenObservation(
            IKResidualWrapper(env, PickPlaceIKExpert(env), residual_scale=float(config.get("residual_scale", 0.10)))
        )

    def residual_policy(observation):
        tensor = torch.as_tensor(observation, dtype=torch.float32, device=trainer.device).unsqueeze(0)
        with torch.inference_mode():
            return trainer.agent.actor_mean(tensor).squeeze(0).cpu().numpy()

    def zero_residual_policy(observation):
        """Control: the residual wrapper then executes the IK expert exactly."""
        del observation
        return np.zeros(action_dim, dtype=np.float32)

    # IK policy has its own stateful expert instance for each fresh environment.
    def ik_factory():
        env = make_ik_env()
        expert = PickPlaceIKExpert(env)
        original_reset = env.reset
        def reset(**kwargs):
            observation, info = original_reset(**kwargs)
            expert.reset()
            return observation, info
        env.reset = reset  # type: ignore[method-assign]
        return env, expert

    def evaluate_ik():
        env, expert = ik_factory()
        from experiments.evaluate import evaluate_success_rate
        return evaluate_success_rate(env, expert.action, int(config["episodes"]))

    results = {
        "ik": evaluate_ik(),
        "ik_zero_residual": compare_policies(
            make_residual_env, {"policy": zero_residual_policy}, int(config["episodes"])
        )["policy"],
        "ik_residual_ppo": compare_policies(
            make_residual_env, {"policy": residual_policy}, int(config["episodes"])
        )["policy"],
    }
    output = Path(config["results_path"])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(results, indent=2) + "\n")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
