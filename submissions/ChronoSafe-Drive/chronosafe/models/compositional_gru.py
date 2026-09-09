"""Factorized temporal diagnosis for compositional sensor degradation."""

from __future__ import annotations

import numpy as np
import torch
from torch import nn


CAMERA_CLASSES = ("camera_normal", "camera_blur", "camera_freeze")
LIDAR_CLASSES = ("lidar_normal", "lidar_dropout")
DELAY_CLASSES = ("synchronized", "dynamic_delay")


class CompositionalHealthGRU(nn.Module):
    """Share temporal context while diagnosing independent degradation factors."""

    def __init__(self, input_size: int, hidden_size: int) -> None:
        super().__init__()
        self.gru = nn.GRU(input_size, hidden_size, batch_first=True)
        self.norm = nn.LayerNorm(hidden_size)
        self.camera_head = nn.Linear(hidden_size, len(CAMERA_CLASSES))
        self.lidar_head = nn.Linear(hidden_size, len(LIDAR_CLASSES))
        self.delay_head = nn.Linear(hidden_size, len(DELAY_CLASSES))
        self.risk_head = nn.Sequential(nn.Linear(hidden_size, 1), nn.Sigmoid())

    def forward(
        self, sequence: torch.Tensor
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
        output, _ = self.gru(sequence)
        state = self.norm(output[:, -1])
        return (
            self.camera_head(state),
            self.lidar_head(state),
            self.delay_head(state),
            self.risk_head(state).squeeze(-1),
        )


def factor_targets(labels: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Convert the seven evaluation scenarios into independent factor labels."""

    camera = np.asarray([0, 1, 2, 0, 0, 2, 1], dtype=np.int64)[labels]
    lidar = np.asarray([0, 0, 0, 1, 0, 1, 0], dtype=np.int64)[labels]
    delay = np.asarray([0, 0, 0, 0, 1, 0, 1], dtype=np.int64)[labels]
    return camera, lidar, delay


def compose_scenario(camera: int, lidar: int, delay: int) -> str:
    """Compose independent factor predictions into a human-readable scenario."""

    if camera == 2 and lidar == 1:
        return "freeze_plus_dropout"
    if camera == 1 and delay == 1:
        return "blur_plus_delay"
    if camera == 2:
        return "camera_freeze"
    if camera == 1:
        return "progressive_blur"
    if lidar == 1:
        return "lidar_dropout"
    if delay == 1:
        return "dynamic_delay"
    return "clean"
