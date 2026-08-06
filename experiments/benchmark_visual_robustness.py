"""Held-out robustness comparison for visual servo and visual residual PPO."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import torch
import yaml

from algorithms.ppo_trainer import CleanRLPPOTrainer, PPOConfig
from experiments.evaluate_visual_residual import _evaluate
from experiments.train_visual_residual import _factory
from simulation.task_factory import initialize_genesis


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("configs/benchmark_visual_robustness.yaml"))
    args = parser.parse_args()
    benchmark = yaml.safe_load(args.config.read_text())
    base = yaml.safe_load(Path(benchmark["base_config"]).read_text())
    task_yaml = yaml.safe_load(Path(base["task_config"]).read_text())
    initialize_genesis(backend=task_yaml["genesis_backend"])
    payload = torch.load(base["checkpoint"], map_location=base["device"], weights_only=False)
    results = {"seed": int(benchmark["seed"]), "scenarios": {}}
    for index, scenario in enumerate(benchmark["scenarios"]):
        config = dict(base)
        config["seed"] = int(benchmark["seed"]) + index * 10_000
        config["domain_randomization"] = scenario["domain_randomization"]
        config["action_noise_std"] = float(scenario.get("action_noise_std", 0.0))
        base_env, residual_env = _factory(config, 0), _factory(config, 0)
        try:
            trainer = CleanRLPPOTrainer(
                int(np.prod(residual_env.observation_space.shape)), int(np.prod(residual_env.action_space.shape)),
                config=PPOConfig(**payload["config"]),
                residual_scale=float(payload["extra"]["residual_scale"]), device=config["device"],
                log_dir="logs/benchmark_visual_robustness",
            )
            trainer.load_checkpoint(base["checkpoint"])
            zero = lambda observation: np.zeros(base_env.action_space.shape, dtype=np.float32)
            @torch.inference_mode()
            def learned(observation: np.ndarray) -> np.ndarray:
                tensor = torch.as_tensor(observation, dtype=torch.float32, device=trainer.device).unsqueeze(0)
                return trainer.agent.actor_mean(tensor).squeeze(0).cpu().numpy()
            results["scenarios"][scenario["name"]] = {
                "color_visual_servo": _evaluate(base_env, zero, int(scenario["episodes"])),
                "color_visual_servo_residual_ppo": _evaluate(residual_env, learned, int(scenario["episodes"])),
            }
            print(f"{scenario['name']}: {results['scenarios'][scenario['name']]}")
        finally:
            base_env.close()
            residual_env.close()
    output = Path(benchmark["results_path"])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(results, indent=2) + "\n")
    print(f"Visual robustness benchmark written to {output}")


if __name__ == "__main__":
    main()
