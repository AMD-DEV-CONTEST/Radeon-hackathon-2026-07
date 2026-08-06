"""torch.compile and synchronized latency/throughput measurement helpers."""

from __future__ import annotations

import time
from typing import Any

import torch


def compile_model(model: torch.nn.Module, *, enabled: bool = True) -> torch.nn.Module:
    """Compile model with Inductor; ROCm PyTorch emits GPU kernels through HIP."""
    return torch.compile(model) if enabled else model


@torch.inference_mode()
def benchmark_model(model: torch.nn.Module, example_input: torch.Tensor, *, warmup: int = 20, iterations: int = 100) -> dict[str, float]:
    for _ in range(warmup):
        model(example_input)
    _synchronize(example_input.device)
    started = time.perf_counter()
    for _ in range(iterations):
        model(example_input)
    _synchronize(example_input.device)
    elapsed = time.perf_counter() - started
    latency_ms = elapsed * 1_000.0 / iterations
    return {"latency_ms": latency_ms, "throughput": example_input.shape[0] / (latency_ms / 1_000.0)}


def _synchronize(device: torch.device) -> None:
    if device.type == "cuda":
        torch.cuda.synchronize(device)
