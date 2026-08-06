"""Numerical-consistency and latency checks for exported deployment policies."""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import torch

from .infer import MIGraphXInference, TorchInference


def validate_migraphx(
    model: torch.nn.Module, model_path: str | Path, samples: np.ndarray, *, device: str = "cuda", iterations: int = 100
) -> dict[str, float]:
    """Compare MIGraphX to PyTorch and measure serialized inference latency."""
    torch_runner, migraphx_runner = TorchInference(model, device=device), MIGraphXInference(model_path)
    reference = torch_runner(samples)
    compiled = migraphx_runner(samples)
    max_abs_error = float(np.max(np.abs(reference - compiled)))
    started = time.perf_counter()
    for _ in range(iterations):
        migraphx_runner(samples)
    latency_ms = (time.perf_counter() - started) * 1_000.0 / iterations
    return {"max_abs_error": max_abs_error, "migraphx_latency_ms": latency_ms}
