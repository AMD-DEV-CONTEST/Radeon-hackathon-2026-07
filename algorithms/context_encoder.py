"""History-based context inference for dynamics-adaptive residual control."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import torch
from torch import nn


class ContextEncoder(nn.Module):
    """Encode recent state/action history as a latent dynamics context ``z``.

    Inputs use batch-major shapes ``states: [B, T, state_dim]`` and ``actions:
    [B, T, action_dim]``.  The resulting ``z`` is concatenated with the current
    observation before the residual-policy MLP.
    """

    def __init__(self, state_dim: int, action_dim: int, latent_dim: int = 16, hidden_dim: int = 128) -> None:
        super().__init__()
        self.latent_dim = latent_dim
        self.history_encoder = nn.GRU(state_dim + action_dim, hidden_dim, batch_first=True)
        self.to_latent = nn.Sequential(nn.Linear(hidden_dim, hidden_dim), nn.Tanh(), nn.Linear(hidden_dim, latent_dim))

    def forward(self, states: torch.Tensor, actions: torch.Tensor) -> torch.Tensor:
        if states.ndim != 3 or actions.ndim != 3:
            raise ValueError("states and actions must both have shape [batch, history, features]")
        if states.shape[:2] != actions.shape[:2]:
            raise ValueError("state and action histories must have matching batch and time dimensions")
        _, hidden = self.history_encoder(torch.cat((states, actions), dim=-1))
        return self.to_latent(hidden[-1])


@dataclass(frozen=True)
class DomainRandomizationConfig:
    """Safe episode-level ranges for unknown object dynamics."""

    mass_range: tuple[float, float] = (0.05, 1.00)
    friction_range: tuple[float, float] = (0.20, 1.50)
    position_low: tuple[float, float, float] = (0.45, -0.20, 0.04)
    position_high: tuple[float, float, float] = (0.75, 0.20, 0.04)


class ContextAdaptation:
    """Coordinates privileged-context supervision and history-only deployment."""

    def __init__(self, encoder: ContextEncoder, *, device: str = "cuda") -> None:
        self.encoder = encoder
        self.device = torch.device(device)

    def sample_domain(self, config: DomainRandomizationConfig = DomainRandomizationConfig()) -> dict[str, torch.Tensor]:
        """Sample mass, friction, and an initial object position on the target device."""
        low = torch.tensor(config.position_low, device=self.device)
        high = torch.tensor(config.position_high, device=self.device)
        return {
            "mass": torch.empty((), device=self.device).uniform_(*config.mass_range),
            "friction": torch.empty((), device=self.device).uniform_(*config.friction_range),
            "object_position": low + torch.rand(3, device=self.device) * (high - low),
        }

    @staticmethod
    def apply_domain_randomization(object_entity: Any, parameters: dict[str, torch.Tensor]) -> None:
        """Apply episode dynamics to a built Genesis rigid object entity."""
        object_entity.set_mass(float(parameters["mass"].item()))
        object_entity.set_friction(float(parameters["friction"].item()))
        object_entity.set_pos(parameters["object_position"])

    def stage1_privileged_loss(
        self, states: torch.Tensor, actions: torch.Tensor, mass: torch.Tensor, friction: torch.Tensor
    ) -> torch.Tensor:
        """Stage 1: train the first two latent values to estimate mass/friction."""
        latent = self.encoder(states.to(self.device), actions.to(self.device))
        target = torch.stack((mass, friction), dim=-1).to(self.device)
        return nn.functional.mse_loss(latent[..., :2], target)

    def stage2_estimate(self, states: torch.Tensor, actions: torch.Tensor) -> torch.Tensor:
        """Stage 2: infer ``z`` entirely from history; no privileged inputs used."""
        return self.encoder(states.to(self.device), actions.to(self.device))
