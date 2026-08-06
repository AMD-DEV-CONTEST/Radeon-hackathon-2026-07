"""Learned residual policy layered on top of physics-guided IK actions."""

from __future__ import annotations

import torch
from torch import nn


class ResidualPolicy(nn.Module):
    """MLP that maps a flattened observation to a bounded residual action."""

    def __init__(
        self,
        observation_dim: int,
        action_dim: int,
        hidden_dim: int = 256,
        residual_scale: float = 0.10,
        context_dim: int = 0,
    ) -> None:
        super().__init__()
        self.residual_scale = residual_scale
        self.context_dim = context_dim
        self.model = nn.Sequential(
            nn.Linear(observation_dim + context_dim, hidden_dim),
            nn.Tanh(),
            nn.Linear(hidden_dim, hidden_dim),
            nn.Tanh(),
            nn.Linear(hidden_dim, action_dim),
        )
        nn.init.orthogonal_(self.model[-1].weight, gain=0.01)
        nn.init.zeros_(self.model[-1].bias)

    def forward(self, obs: torch.Tensor, context: torch.Tensor | None = None) -> torch.Tensor:
        """Return a bounded correction, not an absolute robot action."""
        if self.context_dim:
            if context is None:
                raise ValueError("context is required when context_dim is non-zero")
            obs = torch.cat((obs, context), dim=-1)
        return torch.tanh(self.model(obs)) * self.residual_scale


def fuse_actions(
    ik_action: torch.Tensor,
    delta_action: torch.Tensor,
    *,
    action_low: torch.Tensor | None = None,
    action_high: torch.Tensor | None = None,
) -> torch.Tensor:
    """Fuse explicit IK and implicit residual actions, respecting action limits."""
    final_action = ik_action + delta_action
    if action_low is not None or action_high is not None:
        if action_low is None or action_high is None:
            raise ValueError("action_low and action_high must be supplied together")
        final_action = torch.maximum(torch.minimum(final_action, action_high), action_low)
    return final_action
