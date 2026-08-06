"""AMP helpers for FP16 ROCm training, with a comparable FP32 path."""

from __future__ import annotations

from contextlib import nullcontext
from typing import Iterator

import torch


class AMPTrainer:
    def __init__(self, enabled: bool = True, *, device: str = "cuda") -> None:
        self.device = torch.device(device)
        self.enabled = enabled and self.device.type == "cuda"
        self.scaler = torch.amp.GradScaler("cuda", enabled=self.enabled)

    def autocast(self) -> Iterator[None]:
        """Use FP16 on CUDA-compatible ROCm; FP32 otherwise."""
        if not self.enabled:
            return nullcontext()
        return torch.autocast(device_type="cuda", dtype=torch.float16)

    def backward_step(self, loss: torch.Tensor, optimizer: torch.optim.Optimizer) -> None:
        self.scaler.scale(loss).backward()
        self.scaler.step(optimizer)
        self.scaler.update()
        optimizer.zero_grad(set_to_none=True)
