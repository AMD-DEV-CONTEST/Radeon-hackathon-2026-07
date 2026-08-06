"""Neural networks and action composition for residual SAC."""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import torch
from torch import nn
from torch.distributions import Normal


LOG_STD_MIN = -5.0
LOG_STD_MAX = 1.0


def _mlp(in_dim: int, out_dim: int, hidden: tuple[int, ...]) -> nn.Sequential:
    layers: list[nn.Module] = []
    last = in_dim
    for width in hidden:
        layers += [nn.Linear(last, width), nn.LayerNorm(width), nn.SiLU()]
        last = width
    layers.append(nn.Linear(last, out_dim))
    return nn.Sequential(*layers)


class ResidualActor(nn.Module):
    def __init__(self, obs_dim: int, action_dim: int = 9, hidden: tuple[int, ...] = (256, 256, 128)):
        super().__init__()
        self.obs_dim = obs_dim
        self.action_dim = action_dim
        self.backbone = _mlp(obs_dim, 2 * action_dim, hidden)

    def distribution(self, obs: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        mean, log_std = self.backbone(obs).chunk(2, dim=-1)
        log_std = torch.clamp(log_std, LOG_STD_MIN, LOG_STD_MAX)
        return mean, log_std

    def forward(self, obs: torch.Tensor) -> torch.Tensor:
        """Return the deterministic, normalized residual action."""
        mean, _ = self.distribution(obs)
        return torch.tanh(mean)

    def sample(self, obs: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        mean, log_std = self.distribution(obs)
        dist = Normal(mean, log_std.exp())
        raw = dist.rsample()
        action = torch.tanh(raw)
        log_prob = dist.log_prob(raw) - torch.log(1.0 - action.square() + 1e-6)
        return action, log_prob.sum(dim=-1, keepdim=True), torch.tanh(mean)

    @torch.no_grad()
    def act(self, obs: np.ndarray, device: torch.device, deterministic: bool = False) -> np.ndarray:
        tensor = torch.as_tensor(obs, dtype=torch.float32, device=device).unsqueeze(0)
        sampled, _, mean = self.sample(tensor)
        return (mean if deterministic else sampled).squeeze(0).cpu().numpy().astype(np.float32)


class ResidualCritic(nn.Module):
    def __init__(self, obs_dim: int, action_dim: int = 9, hidden: tuple[int, ...] = (256, 256, 128)):
        super().__init__()
        self.q1 = _mlp(obs_dim + action_dim, 1, hidden)
        self.q2 = _mlp(obs_dim + action_dim, 1, hidden)

    def forward(self, obs: torch.Tensor, action: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        value = torch.cat([obs, action], dim=-1)
        return self.q1(value), self.q2(value)


@dataclass(frozen=True)
class ResidualScales:
    arm: float = 0.015
    finger: float = 0.003

    def vector(self) -> np.ndarray:
        return np.asarray([self.arm] * 7 + [self.finger] * 2, dtype=np.float32)

    def to_dict(self) -> dict:
        return asdict(self)


PANDA_LOW = np.asarray([-2.8973, -1.7628, -2.8973, -3.0718, -2.8973, -0.0175, -2.8973, 0.0, 0.0])
PANDA_HIGH = np.asarray([2.8973, 1.7628, 2.8973, -0.0698, 2.8973, 3.7525, 2.8973, 0.04, 0.04])


def combine_action(
    base_action: np.ndarray,
    normalized_residual: np.ndarray,
    scales: ResidualScales | None = None,
) -> np.ndarray:
    """Add a bounded normalized residual to a physical 9-D joint target."""
    scales = scales or ResidualScales()
    base = np.asarray(base_action, dtype=np.float32).reshape(9)
    residual = np.clip(np.asarray(normalized_residual, dtype=np.float32).reshape(9), -1.0, 1.0)
    return np.clip(base + residual * scales.vector(), PANDA_LOW, PANDA_HIGH).astype(np.float32)
