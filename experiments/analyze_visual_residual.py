"""Report where a visual residual policy corrects the nominal skill action."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import torch
import yaml

from algorithms.ppo_trainer import CleanRLPPOTrainer, PPOConfig
from controller.visual_servo_residual_wrapper import _PHASES
from experiments.train_visual_residual import _factory
from simulation.task_factory import initialize_genesis


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase-by-joint residual analysis.")
    parser.add_argument("--config", type=Path, default=Path("configs/evaluate_visual_residual_action_robust.yaml"))
    parser.add_argument("--results-path", type=Path, default=Path("results/residual_phase_analysis.json"))
    args = parser.parse_args()
    config = yaml.safe_load(args.config.read_text())
    task_yaml = yaml.safe_load(Path(config["task_config"]).read_text())
    initialize_genesis(backend=task_yaml["genesis_backend"])
    env = _factory(config, worker_index=0)
    try:
        payload = torch.load(config["checkpoint"], map_location=config["device"], weights_only=False)
        trainer = CleanRLPPOTrainer(
            int(np.prod(env.observation_space.shape)), int(np.prod(env.action_space.shape)),
            config=PPOConfig(**payload["config"]),
            residual_scale=float(payload.get("extra", {}).get("residual_scale", config["residual_scale"])),
            device=config["device"], log_dir=config.get("log_dir", "logs/residual_phase_analysis"),
        )
        trainer.load_checkpoint(config["checkpoint"])
        sums = {phase: np.zeros(env.action_space.shape, dtype=np.float64) for phase in _PHASES}
        counts = {phase: 0 for phase in _PHASES}
        for episode in range(int(config["episodes"])):
            observation, _ = env.reset(seed=10_000 + episode)
            terminated = truncated = False
            while not (terminated or truncated):
                phase = env.controller.expert.phase
                with torch.inference_mode():
                    tensor = torch.as_tensor(observation, dtype=torch.float32, device=trainer.device).unsqueeze(0)
                    residual = trainer.agent.actor_mean(tensor).squeeze(0).cpu().numpy()
                sums[phase] += np.abs(residual)
                counts[phase] += 1
                observation, _, terminated, truncated, _ = env.step(residual)
        result = {
            "checkpoint": str(config["checkpoint"]),
            "episodes": int(config["episodes"]),
            "phase_step_counts": counts,
            "mean_abs_residual_by_phase_joint": {
                phase: (sums[phase] / max(counts[phase], 1)).tolist() for phase in _PHASES
            },
        }
        args.results_path.parent.mkdir(parents=True, exist_ok=True)
        args.results_path.write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result, indent=2))
    finally:
        env.close()


if __name__ == "__main__":
    main()
