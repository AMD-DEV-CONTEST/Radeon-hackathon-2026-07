"""Compare eager, AMP and torch.compile residual-policy inference on ROCm.

This is deliberately a policy-only microbenchmark.  Genesis rendering and
physics are separately measured by ``experiments.benchmark_rocm``.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
import torch
import yaml

from algorithms.ppo_trainer import CleanRLPPOTrainer, PPOConfig
from experiments.train_visual_residual import _factory
from simulation.task_factory import initialize_genesis


def _measure(model, sample: torch.Tensor, *, amp: bool, iterations: int) -> dict[str, float]:
    for _ in range(50):
        with torch.autocast("cuda", dtype=torch.float16, enabled=amp):
            model(sample)
    torch.cuda.synchronize(sample.device)
    started = time.perf_counter()
    with torch.inference_mode():
        for _ in range(iterations):
            with torch.autocast("cuda", dtype=torch.float16, enabled=amp):
                model(sample)
    torch.cuda.synchronize(sample.device)
    elapsed = time.perf_counter() - started
    return {"latency_ms": elapsed * 1000.0 / iterations, "throughput_hz": iterations / elapsed}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("configs/benchmark_rocm.yaml"))
    parser.add_argument("--results-path", type=Path, default=Path("results/rocm_policy_optimization.json"))
    parser.add_argument("--iterations", type=int, default=10_000)
    args = parser.parse_args()
    config = yaml.safe_load(args.config.read_text())
    if not torch.cuda.is_available() or torch.version.hip is None:
        raise RuntimeError("This benchmark requires a ROCm PyTorch GPU.")
    task_yaml = yaml.safe_load(Path(config["task_config"]).read_text())
    initialize_genesis(backend=task_yaml["genesis_backend"])
    env = _factory(config, worker_index=0)
    try:
        payload = torch.load(config["checkpoint"], map_location=config["device"], weights_only=False)
        trainer = CleanRLPPOTrainer(
            int(np.prod(env.observation_space.shape)), int(np.prod(env.action_space.shape)),
            config=PPOConfig(**payload["config"]), residual_scale=float(config["residual_scale"]),
            device=config["device"], log_dir=config.get("log_dir", "logs/rocm_policy_optimization"),
        )
        trainer.load_checkpoint(config["checkpoint"])
        observation, _ = env.reset(seed=19_999)
        sample = torch.as_tensor(observation, dtype=torch.float32, device=trainer.device).unsqueeze(0)
        model = trainer.agent.actor_mean.eval()
        results: dict[str, object] = {
            "torch": torch.__version__, "hip": torch.version.hip, "iterations": args.iterations,
            "eager_fp32": _measure(model, sample, amp=False, iterations=args.iterations),
            "amp_fp16": _measure(model, sample, amp=True, iterations=args.iterations),
        }
        try:
            compiled = torch.compile(model)
            results["torch_compile_fp32"] = _measure(compiled, sample, amp=False, iterations=args.iterations)
        except Exception as error:  # Report unsupported compiler paths faithfully.
            results["torch_compile_error"] = f"{type(error).__name__}: {error}"
        args.results_path.parent.mkdir(parents=True, exist_ok=True)
        args.results_path.write_text(json.dumps(results, indent=2) + "\n")
        print(json.dumps(results, indent=2))
    finally:
        env.close()


if __name__ == "__main__":
    main()
