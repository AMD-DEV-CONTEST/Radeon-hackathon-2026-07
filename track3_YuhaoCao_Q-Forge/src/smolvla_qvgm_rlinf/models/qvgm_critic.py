"""Action-sensitive Q-VGM ensemble critic."""

from __future__ import annotations

from dataclasses import asdict, dataclass

import torch
from torch import nn


@dataclass(frozen=True)
class QVGMCriticConfig:
    z_dim: int = 512
    proprio_dim: int = 8
    proprio_feature_dim: int = 64
    action_dim: int = 7
    horizon: int = 5
    hidden_dim: int = 512
    first_hidden_dim: int | None = None
    ensemble_size: int = 5
    joint_state_norm: bool = False


class ActionRepeatQNetwork(nn.Module):
    """Inject the candidate action at every critic stage."""

    def __init__(
        self, state_dim: int, flat_action_dim: int, hidden_dim: int, first_hidden_dim: int
    ):
        super().__init__()
        self.input_layer = nn.Sequential(
            nn.Linear(state_dim + flat_action_dim, first_hidden_dim),
            nn.LayerNorm(first_hidden_dim),
            nn.SiLU(),
        )
        self.hidden_layer = nn.Sequential(
            nn.Linear(first_hidden_dim + flat_action_dim, hidden_dim),
            nn.LayerNorm(hidden_dim),
            nn.SiLU(),
        )
        self.output_layer = nn.Linear(hidden_dim + flat_action_dim, 1)

    def forward(self, state: torch.Tensor, action: torch.Tensor) -> torch.Tensor:
        hidden = self.input_layer(torch.cat([state, action], dim=-1))
        hidden = self.hidden_layer(torch.cat([hidden, action], dim=-1))
        return self.output_layer(torch.cat([hidden, action], dim=-1))


class QVGMCriticEnsemble(nn.Module):
    """Five-head default ensemble over compact state and H-step action chunks."""

    def __init__(self, config: QVGMCriticConfig | None = None):
        super().__init__()
        self.config = config or QVGMCriticConfig()
        if self.config.ensemble_size < 2:
            raise ValueError("ensemble_size must be at least two")
        self.z_norm = nn.LayerNorm(self.config.z_dim)
        self.proprio_encoder = nn.Sequential(
            nn.Linear(self.config.proprio_dim, self.config.proprio_feature_dim),
            nn.LayerNorm(self.config.proprio_feature_dim),
            nn.SiLU(),
        )
        state_dim = self.config.z_dim + self.config.proprio_feature_dim
        self.state_norm = nn.LayerNorm(state_dim) if self.config.joint_state_norm else nn.Identity()
        flat_action_dim = self.config.horizon * self.config.action_dim
        first_hidden_dim = self.config.first_hidden_dim or self.config.hidden_dim
        self.q_networks = nn.ModuleList(
            [
                ActionRepeatQNetwork(
                    state_dim, flat_action_dim, self.config.hidden_dim, first_hidden_dim
                )
                for _ in range(self.config.ensemble_size)
            ]
        )

    @property
    def config_dict(self) -> dict:
        return asdict(self.config)

    def encode_state(self, z_state: torch.Tensor, proprio: torch.Tensor) -> torch.Tensor:
        z = z_state.float() if self.config.joint_state_norm else self.z_norm(z_state.float())
        state = torch.cat([z, self.proprio_encoder(proprio.float())], dim=-1)
        return self.state_norm(state)

    def forward(
        self,
        z_state: torch.Tensor,
        proprio: torch.Tensor,
        action_chunk: torch.Tensor,
        action_mask: torch.Tensor | None = None,
    ) -> torch.Tensor:
        expected = (self.config.horizon, self.config.action_dim)
        if tuple(action_chunk.shape[-2:]) != expected:
            raise ValueError(f"action chunk must end in {expected}, got {tuple(action_chunk.shape)}")
        action = action_chunk.float()
        if action_mask is not None:
            if tuple(action_mask.shape) != tuple(action.shape[:-1]):
                raise ValueError("action_mask shape must match action chunk without action dimension")
            action = action * action_mask.unsqueeze(-1).to(action.dtype)
        action = action.flatten(start_dim=1)
        state = self.encode_state(z_state, proprio)
        return torch.cat([network(state, action) for network in self.q_networks], dim=-1)

    def conservative_value(self, *args, **kwargs) -> torch.Tensor:
        """Legacy pessimistic aggregate retained for API/checkpoint compatibility."""
        return self(*args, **kwargs).min(dim=-1, keepdim=True).values

    def mean_value(self, *args, **kwargs) -> torch.Tensor:
        """Q-VGM paper value: arithmetic mean across ensemble members."""
        return self(*args, **kwargs).mean(dim=-1, keepdim=True)

    def disagreement(self, *args, **kwargs) -> torch.Tensor:
        return self(*args, **kwargs).std(dim=-1, keepdim=True, unbiased=False)
