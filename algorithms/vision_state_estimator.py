"""Visual task-state estimator for image-conditioned IK control."""

from __future__ import annotations

import torch
from torch import nn

from .vision_actor_critic import VisualEncoder


class VisualTaskStateEstimator(nn.Module):
    """Estimate object and target Cartesian positions from RGB and proprioception."""

    def __init__(
        self, *, image_height: int, image_width: int, proprio_dim: int,
        hidden_dim: int = 256, visual_embedding_dim: int = 128,
    ) -> None:
        super().__init__()
        self.visual_encoder = VisualEncoder(image_height, image_width, visual_embedding_dim)
        self.head = nn.Sequential(
            nn.Linear(visual_embedding_dim + proprio_dim, hidden_dim), nn.ReLU(),
            nn.Linear(hidden_dim, hidden_dim), nn.ReLU(),
            nn.Linear(hidden_dim, 6),
        )
        nn.init.normal_(self.head[-1].weight, mean=0.0, std=0.01)
        nn.init.zeros_(self.head[-1].bias)

    def forward(self, rgb: torch.Tensor, proprio: torch.Tensor) -> torch.Tensor:
        if proprio.ndim != 2:
            raise ValueError("proprio must have shape [batch, proprio_dim]")
        features = torch.cat((self.visual_encoder(rgb), proprio.float()), dim=-1)
        return self.head(features)
