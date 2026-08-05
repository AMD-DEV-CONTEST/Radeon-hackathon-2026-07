"""Lightweight recurrent sensor-health model."""

from __future__ import annotations

import torch
from torch import nn


class HealthGRU(nn.Module):
    def __init__(self, input_size: int, hidden_size: int, num_classes: int) -> None:
        super().__init__()
        self.gru = nn.GRU(input_size, hidden_size, batch_first=True)
        self.norm = nn.LayerNorm(hidden_size)
        self.classifier = nn.Linear(hidden_size, num_classes)
        self.risk_head = nn.Sequential(nn.Linear(hidden_size, 1), nn.Sigmoid())

    def forward(self, sequence: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        output, _ = self.gru(sequence)
        state = self.norm(output[:, -1])
        logits = self.classifier(state)
        risk = self.risk_head(state).squeeze(-1)
        return logits, risk
