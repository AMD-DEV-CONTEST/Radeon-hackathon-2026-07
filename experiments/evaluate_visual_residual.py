"""Held-out comparison of color visual servo with and without PPO residuals."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Callable

import numpy as np
import torch
import yaml

from algorithms.ppo_trainer import CleanRLPPOTrainer, PPOConfig
from experiments.train_visual_residual import _factory
from simulation.task_factory import initialize_genesis


def _evaluate(env, policy: Callable[[np.ndarray], np.ndarray], episodes: int) -> dict[str, float]:
    successes = 0
    lengths: list[int] = []
    distances: list[float] = []
    residual_norms: list[float] = []
    for episode in range(episodes):
        observation, _ = env.reset(seed=10_000 + episode)
        terminated = truncated = False
        info: dict[str, Any] = {}
        while not (terminated or truncated):
            residual = policy(observation)
            residual_norms.append(float(np.linalg.norm(residual)))
            observation, _, terminated, truncated, info = env.step(residual)
        successes += int(bool(info.get("is_success", False)))
        lengths.append(int(info.get("episode_step", 0)))
        distances.append(float(info.get("distance_to_goal", np.nan)))
    return {
        "success_rate": successes / episodes,
        "mean_episode_length": float(np.mean(lengths)),
        "mean_final_distance_m": float(np.nanmean(distances)),
        "mean_residual_l2": float(np.mean(residual_norms)),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("configs/evaluate_visual_residual.yaml"))
    args = parser.parse_args()
    config = yaml.safe_load(args.config.read_text())
    task_yaml = yaml.safe_load(Path(config["task_config"]).read_text())
    initialize_genesis(backend=task_yaml["genesis_backend"])
    base_env = _factory(config, worker_index=0)
    # Independent environments receive identical randomizer sequences for a
    # fair base-versus-residual comparison.
    residual_env = _factory(config, worker_index=0)
    try:
        payload = torch.load(config["checkpoint"], map_location=config["device"], weights_only=False)
        trainer = CleanRLPPOTrainer(
            int(np.prod(residual_env.observation_space.shape)), int(np.prod(residual_env.action_space.shape)),
            config=PPOConfig(**payload["config"]),
            residual_scale=float(payload.get("extra", {}).get("residual_scale", config["residual_scale"])),
            device=config["device"], log_dir=config.get("log_dir", "logs/evaluate_visual_residual"),
        )
        trainer.load_checkpoint(config["checkpoint"])
        zero = lambda observation: np.zeros(base_env.action_space.shape, dtype=np.float32)

        @torch.inference_mode()
        def learned(observation: np.ndarray) -> np.ndarray:
            tensor = torch.as_tensor(observation, dtype=torch.float32, device=trainer.device).unsqueeze(0)
            return trainer.agent.actor_mean(tensor).squeeze(0).cpu().numpy()

        results = {
            "color_visual_servo": _evaluate(base_env, zero, int(config["episodes"])),
            "color_visual_servo_residual_ppo": _evaluate(residual_env, learned, int(config["episodes"])),
        }
        output = Path(config["results_path"])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(results, indent=2) + "\n")
        print(json.dumps(results, indent=2))
    finally:
        base_env.close()
        residual_env.close()


if __name__ == "__main__":
    main()
