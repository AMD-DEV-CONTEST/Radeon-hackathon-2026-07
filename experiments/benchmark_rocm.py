"""Collect reproducible AMD ROCm training and inference evidence."""

from __future__ import annotations

import argparse
import json
import platform
import subprocess
import time
from pathlib import Path
from typing import Any

import numpy as np
import torch
import yaml

from algorithms.ppo_trainer import CleanRLPPOTrainer, PPOConfig
from experiments.train_visual_residual import _factory
from simulation.task_factory import initialize_genesis


def _sync(device: torch.device) -> None:
    if device.type == "cuda":
        torch.cuda.synchronize(device)


def _environment_metadata(device: torch.device, genesis: Any) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "torch": torch.__version__,
        "hip": torch.version.hip,
        "torch_cuda_field": torch.version.cuda,
        "cuda_api_available": torch.cuda.is_available(),
        "genesis": getattr(genesis, "__version__", "unknown"),
    }
    if device.type == "cuda" and torch.cuda.is_available():
        properties = torch.cuda.get_device_properties(device)
        device_index = torch.cuda.current_device()
        torch_name = torch.cuda.get_device_name(device)
        metadata["gpu"] = {
            "name": torch_name or "unreported_by_torch",
            "total_memory_gb": properties.total_memory / (1024**3),
            "device_index": device_index,
        }
        # Some ROCm images expose an empty name through the CUDA-compatible
        # PyTorch API. Preserve ROCm SMI output as reportable hardware evidence.
        try:
            process = subprocess.run(
                ["rocm-smi", "--showproductname"], capture_output=True, text=True, timeout=10, check=False,
            )
            metadata["rocm_smi_product_info"] = process.stdout.strip() or process.stderr.strip()
        except (FileNotFoundError, subprocess.TimeoutExpired) as error:
            metadata["rocm_smi_product_info"] = f"unavailable: {error}"
    return metadata


def _model_inference_benchmark(trainer: CleanRLPPOTrainer, observation: np.ndarray, iterations: int) -> dict[str, float]:
    tensor = torch.as_tensor(observation, dtype=torch.float32, device=trainer.device).unsqueeze(0)
    for _ in range(20):
        trainer.agent.actor_mean(tensor)
    _sync(trainer.device)
    started = time.perf_counter()
    with torch.inference_mode():
        for _ in range(iterations):
            trainer.agent.actor_mean(tensor)
    _sync(trainer.device)
    elapsed = time.perf_counter() - started
    return {
        "iterations": iterations,
        "total_seconds": elapsed,
        "mean_latency_ms": elapsed * 1000.0 / iterations,
        "throughput_hz": iterations / elapsed,
    }


def _end_to_end_benchmark(env, trainer: CleanRLPPOTrainer, episodes: int) -> dict[str, float]:
    steps = successes = 0
    started = time.perf_counter()
    for episode in range(episodes):
        observation, _ = env.reset(seed=20_000 + episode)
        terminated = truncated = False
        info: dict[str, Any] = {}
        while not (terminated or truncated):
            with torch.inference_mode():
                tensor = torch.as_tensor(observation, dtype=torch.float32, device=trainer.device).unsqueeze(0)
                residual = trainer.agent.actor_mean(tensor).squeeze(0).cpu().numpy()
            observation, _, terminated, truncated, info = env.step(residual)
            steps += 1
        successes += int(bool(info.get("is_success", False)))
    _sync(trainer.device)
    elapsed = time.perf_counter() - started
    return {
        "episodes": episodes,
        "steps": steps,
        "total_seconds": elapsed,
        "control_fps": steps / elapsed,
        "success_rate": successes / episodes,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("configs/benchmark_rocm.yaml"))
    args = parser.parse_args()
    config = yaml.safe_load(args.config.read_text())
    device = torch.device(config["device"])
    if device.type != "cuda" or not torch.cuda.is_available() or torch.version.hip is None:
        raise RuntimeError("benchmark_rocm requires a usable ROCm PyTorch GPU")
    task_yaml = yaml.safe_load(Path(config["task_config"]).read_text())
    genesis = initialize_genesis(backend=task_yaml["genesis_backend"])
    env = _factory(config, worker_index=0)
    try:
        payload = torch.load(config["checkpoint"], map_location=device, weights_only=False)
        trainer = CleanRLPPOTrainer(
            int(np.prod(env.observation_space.shape)), int(np.prod(env.action_space.shape)),
            config=PPOConfig(**payload["config"]),
            residual_scale=float(payload.get("extra", {}).get("residual_scale", config["residual_scale"])),
            device=config["device"], log_dir=config.get("log_dir", "logs/benchmark_rocm"),
        )
        trainer.load_checkpoint(config["checkpoint"])
        warmup_observation, _ = env.reset(seed=19_999)
        # Compile Genesis kernels and warm the policy before timed measurements.
        _end_to_end_benchmark(env, trainer, int(config.get("warmup_episodes", 1)))
        torch.cuda.reset_peak_memory_stats(device)
        model_benchmark = _model_inference_benchmark(trainer, warmup_observation, int(config["inference_iterations"]))
        end_to_end = _end_to_end_benchmark(env, trainer, int(config["episodes"]))
        result = {
            "environment": _environment_metadata(device, genesis),
            "checkpoint": str(config["checkpoint"]),
            "training_final_metrics": payload.get("extra", {}).get("metrics", {}),
            "model_inference": model_benchmark,
            "end_to_end_visual_servo_residual": end_to_end,
            "peak_gpu_memory_mb": torch.cuda.max_memory_allocated(device) / (1024**2),
        }
        output = Path(config["results_path"])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result, indent=2))
    finally:
        env.close()


if __name__ == "__main__":
    main()
