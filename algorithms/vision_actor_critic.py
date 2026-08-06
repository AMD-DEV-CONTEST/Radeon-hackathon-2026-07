"""RGB + proprioception Actor-Critic components for visuomotor control."""

from __future__ import annotations

import torch
from torch import nn
from torch.distributions import Normal


class SpatialSoftmax(nn.Module):
    """Convert convolutional feature maps into differentiable 2-D keypoints."""

    def __init__(self, height: int, width: int, channels: int) -> None:
        super().__init__()
        x = torch.linspace(-1.0, 1.0, width)
        y = torch.linspace(-1.0, 1.0, height)
        grid_y, grid_x = torch.meshgrid(y, x, indexing="ij")
        self.register_buffer("grid_x", grid_x.reshape(1, 1, -1))
        self.register_buffer("grid_y", grid_y.reshape(1, 1, -1))
        self.channels = channels

    def forward(self, features: torch.Tensor) -> torch.Tensor:
        if features.ndim != 4:
            raise ValueError("features must have shape [batch, channels, height, width]")
        batch, channels, height, width = features.shape
        if channels != self.channels or self.grid_x.shape[-1] != height * width:
            raise ValueError("feature shape differs from SpatialSoftmax configuration")
        attention = torch.softmax(features.reshape(batch, channels, -1), dim=-1)
        expected_x = (attention * self.grid_x).sum(dim=-1)
        expected_y = (attention * self.grid_y).sum(dim=-1)
        return torch.cat((expected_x, expected_y), dim=-1)


class VisualEncoder(nn.Module):
    """Lightweight ConvNet followed by Spatial Softmax keypoint extraction."""

    def __init__(self, image_height: int, image_width: int, embedding_dim: int = 128) -> None:
        super().__init__()
        self.backbone = nn.Sequential(
            nn.Conv2d(3, 32, kernel_size=5, stride=2), nn.ReLU(),
            nn.Conv2d(32, 64, kernel_size=3, stride=2), nn.ReLU(),
            nn.Conv2d(64, 64, kernel_size=3, stride=2), nn.ReLU(),
        )
        with torch.no_grad():
            shape = self.backbone(torch.zeros(1, 3, image_height, image_width)).shape
        self.spatial_softmax = SpatialSoftmax(shape[-2], shape[-1], shape[1])
        self.projection = nn.Sequential(
            nn.Linear(shape[1] * 2, embedding_dim), nn.ReLU(),
        )

    def forward(self, rgb: torch.Tensor) -> torch.Tensor:
        if rgb.ndim != 4:
            raise ValueError("rgb must have shape [batch, height, width, 3] or [batch, 3, height, width]")
        if rgb.shape[-1] == 3:
            rgb = rgb.permute(0, 3, 1, 2)
        if rgb.shape[1] != 3:
            raise ValueError("rgb must have three channels")
        rgb = rgb.float().div(255.0) if rgb.dtype == torch.uint8 else rgb.float()
        return self.projection(self.spatial_softmax(self.backbone(rgb)))


class VisualActorCritic(nn.Module):
    """Continuous Gaussian policy that fuses RGB features with proprioception."""

    def __init__(
        self, *, image_height: int, image_width: int, proprio_dim: int,
        action_dim: int, hidden_dim: int = 256, visual_embedding_dim: int = 128,
    ) -> None:
        super().__init__()
        self.visual_encoder = VisualEncoder(image_height, image_width, visual_embedding_dim)
        self.fusion = nn.Sequential(
            nn.Linear(visual_embedding_dim + proprio_dim, hidden_dim), nn.ReLU(),
            nn.Linear(hidden_dim, hidden_dim), nn.ReLU(),
        )
        self.actor_mean = nn.Linear(hidden_dim, action_dim)
        self.actor_logstd = nn.Parameter(torch.full((1, action_dim), -2.0))
        self.critic = nn.Linear(hidden_dim, 1)
        # Some ROCm competition images omit CPU LAPACK, making orthogonal_
        # initialization fail during CPU-side test construction.  A small
        # Gaussian initialization provides the same near-zero action prior.
        nn.init.normal_(self.actor_mean.weight, mean=0.0, std=0.01)
        nn.init.zeros_(self.actor_mean.bias)

    def features(self, rgb: torch.Tensor, proprio: torch.Tensor) -> torch.Tensor:
        if proprio.ndim != 2:
            raise ValueError("proprio must have shape [batch, proprio_dim]")
        return self.fusion(torch.cat((self.visual_encoder(rgb), proprio.float()), dim=-1))

    def get_action_and_value(
        self, rgb: torch.Tensor, proprio: torch.Tensor, action: torch.Tensor | None = None
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
        features = self.features(rgb, proprio)
        distribution = Normal(self.actor_mean(features), self.actor_logstd.expand(features.shape[0], -1).exp())
        if action is None:
            action = distribution.sample()
        return action, distribution.log_prob(action).sum(-1), distribution.entropy().sum(-1), self.critic(features)

    def mean_action(self, rgb: torch.Tensor, proprio: torch.Tensor) -> torch.Tensor:
        """Deterministic action used by behavior cloning evaluation."""
        return self.actor_mean(self.features(rgb, proprio))
