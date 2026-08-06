"""Residual-fusion hotspot prepared for a single compiler-generated HIP kernel."""

from __future__ import annotations

import torch


class ResidualFusion(torch.nn.Module):
    """Fuse scale, add, and clip; compile this module only after profiling.

    With ROCm PyTorch, ``torch.compile``/Inductor lowers this pointwise expression
    to one generated HIP GPU kernel, avoiding intermediate action tensors.
    """

    def __init__(self, action_low: float = -1.0, action_high: float = 1.0) -> None:
        super().__init__()
        self.action_low, self.action_high = action_low, action_high

    def forward(self, ik_action: torch.Tensor, delta_action: torch.Tensor, scale: torch.Tensor | float = 1.0) -> torch.Tensor:
        return torch.clamp(ik_action + delta_action * scale, self.action_low, self.action_high)
