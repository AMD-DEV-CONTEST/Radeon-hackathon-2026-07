"""Distill the full teacher stack into a compact deployment policy."""

from __future__ import annotations

import torch
from torch import nn


class StudentPolicy(nn.Module):
    """Small encoder → MLP → action-head policy for low-latency control."""

    def __init__(self, observation_dim: int, action_dim: int, latent_dim: int = 64, hidden_dim: int = 128) -> None:
        super().__init__()
        self.encoder = nn.Sequential(nn.Linear(observation_dim, latent_dim), nn.ReLU())
        self.action_head = nn.Sequential(nn.Linear(latent_dim, hidden_dim), nn.ReLU(), nn.Linear(hidden_dim, action_dim))

    def forward(self, observation: torch.Tensor) -> torch.Tensor:
        return self.action_head(self.encoder(observation))


class PolicyDistiller:
    """Match teacher actions from IK + context residual + flow residual."""

    def __init__(self, student: StudentPolicy, *, device: str = "cuda", learning_rate: float = 3e-4) -> None:
        self.student = student.to(device)
        self.device = torch.device(device)
        self.optimizer = torch.optim.Adam(self.student.parameters(), lr=learning_rate)

    def step(self, observations: torch.Tensor, teacher_actions: torch.Tensor) -> float:
        self.student.train()
        predicted = self.student(observations.to(self.device))
        loss = nn.functional.mse_loss(predicted, teacher_actions.to(self.device))
        self.optimizer.zero_grad(set_to_none=True)
        loss.backward()
        self.optimizer.step()
        return float(loss.detach())
