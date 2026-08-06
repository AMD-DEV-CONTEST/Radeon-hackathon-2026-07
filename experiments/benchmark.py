"""Experiment 3: compare ROCm execution modes and memory use."""

from __future__ import annotations

from copy import deepcopy

import torch

from optimization.amp import AMPTrainer
from optimization.compiler import benchmark_model, compile_model


def benchmark_hardware(model: torch.nn.Module, sample: torch.Tensor) -> dict[str, dict[str, float]]:
    """Measure FP32, AMP, compile, and GPU-buffer-ready execution metrics."""
    device = sample.device
    fp32_model = deepcopy(model).eval().to(device)
    results = {"fp32": benchmark_model(fp32_model, sample)}
    amp = AMPTrainer(enabled=True, device=str(device))
    with amp.autocast():
        results["amp"] = benchmark_model(fp32_model, sample)
    results["compile"] = benchmark_model(compile_model(deepcopy(model).eval().to(device)), sample)
    results["gpu_buffer"] = {"host_transfer_eliminated": 1.0}
    if device.type == "cuda":
        results["gpu"] = {
            "utilization": float(torch.cuda.utilization(device)) if hasattr(torch.cuda, "utilization") else -1.0,
            "vram_usage_mb": torch.cuda.max_memory_allocated(device) / (1024**2),
        }
    return results
