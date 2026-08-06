"""One-step flow-matching policy for generative residual robot actions."""

from __future__ import annotations

import torch
from torch import nn


class FlowResidualPolicy(nn.Module):
    """Predict the residual-action flow velocity conditioned on state and context."""

    def __init__(
        self,
        state_dim: int,
        action_dim: int,
        context_dim: int,
        hidden_dim: int = 256,
        residual_scale: float = 0.10,
    ) -> None:
        super().__init__()
        self.action_dim = action_dim
        self.residual_scale = residual_scale
        self.velocity_model = nn.Sequential(
            nn.Linear(state_dim + context_dim + action_dim + 1, hidden_dim),
            nn.SiLU(),
            nn.Linear(hidden_dim, hidden_dim),
            nn.SiLU(),
            nn.Linear(hidden_dim, action_dim),
        )
        nn.init.zeros_(self.velocity_model[-1].bias)

    def velocity(
        self, state: torch.Tensor, context: torch.Tensor, noisy_action: torch.Tensor, time: torch.Tensor
    ) -> torch.Tensor:
        """Predict ``dx/dt`` for the linear noise-to-action probability path."""
        if time.ndim == state.ndim - 1:
            time = time.unsqueeze(-1)
        return self.velocity_model(torch.cat((state, context, noisy_action, time), dim=-1))

    def forward(self, state: torch.Tensor, context: torch.Tensor, noise: torch.Tensor) -> torch.Tensor:
        """One-step sample: integrate from Gaussian noise at ``t=0`` to a residual."""
        time = torch.zeros((*noise.shape[:-1], 1), device=noise.device, dtype=noise.dtype)
        delta_action = noise + self.velocity(state, context, noise, time)
        return delta_action.clamp(-self.residual_scale, self.residual_scale)

    def flow_matching_loss(
        self, state: torch.Tensor, context: torch.Tensor, target_delta_action: torch.Tensor
    ) -> torch.Tensor:
        """Velocity-prediction loss for conditional flow matching."""
        noise = torch.randn_like(target_delta_action)
        time = torch.rand((*target_delta_action.shape[:-1], 1), device=target_delta_action.device)
        noisy_action = (1.0 - time) * noise + time * target_delta_action
        target_velocity = target_delta_action - noise
        predicted_velocity = self.velocity(state, context, noisy_action, time)
        return nn.functional.mse_loss(predicted_velocity, target_velocity)
