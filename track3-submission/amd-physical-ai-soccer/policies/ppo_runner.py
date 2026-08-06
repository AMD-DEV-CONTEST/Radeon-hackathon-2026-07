"""Minimal PPO wiring (skrl) for the humanoid soccer env.

Kept framework-light so it's easy to read. If you prefer rsl_rl, the env's
reset/step contract is compatible; only this file changes.
"""
from __future__ import annotations

import torch
import torch.nn as nn


class MLPPolicy(nn.Module):
    """Shared-trunk actor-critic. Gaussian policy for continuous joint targets."""

    def __init__(self, num_obs: int, num_actions: int, hidden=(512, 256, 128)):
        super().__init__()
        layers, last = [], num_obs
        for h in hidden:
            layers += [nn.Linear(last, h), nn.ELU()]
            last = h
        self.trunk = nn.Sequential(*layers)
        self.mu = nn.Linear(last, num_actions)
        self.log_std = nn.Parameter(torch.zeros(num_actions))
        self.value = nn.Linear(last, 1)

    def forward(self, obs):
        z = self.trunk(obs)
        return self.mu(z), self.log_std.exp(), self.value(z)

    def act(self, obs):
        mu, std, value = self.forward(obs)
        dist = torch.distributions.Normal(mu, std)
        action = dist.sample()
        logp = dist.log_prob(action).sum(-1)
        return action, logp, value.squeeze(-1)

    def evaluate(self, obs, action):
        mu, std, value = self.forward(obs)
        dist = torch.distributions.Normal(mu, std)
        logp = dist.log_prob(action).sum(-1)
        entropy = dist.entropy().sum(-1)
        return logp, entropy, value.squeeze(-1)


def build_policy(cfg: dict, num_obs: int, num_actions: int) -> MLPPolicy:
    device = cfg["experiment"]["device"]
    hidden = tuple(cfg["ppo"]["hidden"])
    return MLPPolicy(num_obs, num_actions, hidden).to(device)
