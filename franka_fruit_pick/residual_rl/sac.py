"""Minimal PyTorch Soft Actor-Critic implementation for normalized residuals."""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import torch
from torch import nn

from .models import ResidualActor, ResidualCritic


@dataclass
class SACConfig:
    gamma: float = 0.99
    tau: float = 0.005
    actor_lr: float = 3e-4
    critic_lr: float = 3e-4
    alpha_lr: float = 3e-4
    target_entropy: float | None = None


class SACAgent:
    def __init__(self, obs_dim: int, action_dim: int, device: torch.device, cfg: SACConfig | None = None):
        self.cfg = cfg or SACConfig()
        self.device = device
        self.action_dim = action_dim
        self.actor = ResidualActor(obs_dim, action_dim).to(device)
        self.critic = ResidualCritic(obs_dim, action_dim).to(device)
        self.target_critic = ResidualCritic(obs_dim, action_dim).to(device)
        self.target_critic.load_state_dict(self.critic.state_dict())
        self.target_critic.requires_grad_(False)

        self.actor_opt = torch.optim.Adam(self.actor.parameters(), lr=self.cfg.actor_lr)
        self.critic_opt = torch.optim.Adam(self.critic.parameters(), lr=self.cfg.critic_lr)
        self.log_alpha = torch.zeros(1, device=device, requires_grad=True)
        self.alpha_opt = torch.optim.Adam([self.log_alpha], lr=self.cfg.alpha_lr)
        self.target_entropy = self.cfg.target_entropy if self.cfg.target_entropy is not None else -float(action_dim)

    @property
    def alpha(self) -> torch.Tensor:
        return self.log_alpha.exp()

    def act(self, obs: np.ndarray, deterministic: bool = False) -> np.ndarray:
        return self.actor.act(obs, self.device, deterministic)

    def update(self, batch: dict[str, torch.Tensor]) -> dict[str, float]:
        with torch.no_grad():
            next_action, next_log_prob, _ = self.actor.sample(batch["next_obs"])
            tq1, tq2 = self.target_critic(batch["next_obs"], next_action)
            target_q = torch.min(tq1, tq2) - self.alpha.detach() * next_log_prob
            target = batch["rewards"] + self.cfg.gamma * (1.0 - batch["dones"]) * target_q

        q1, q2 = self.critic(batch["obs"], batch["actions"])
        critic_loss = nn.functional.mse_loss(q1, target) + nn.functional.mse_loss(q2, target)
        self.critic_opt.zero_grad(set_to_none=True)
        critic_loss.backward()
        self.critic_opt.step()

        action, log_prob, _ = self.actor.sample(batch["obs"])
        q1_pi, q2_pi = self.critic(batch["obs"], action)
        actor_loss = (self.alpha.detach() * log_prob - torch.min(q1_pi, q2_pi)).mean()
        self.actor_opt.zero_grad(set_to_none=True)
        actor_loss.backward()
        self.actor_opt.step()

        alpha_loss = -(self.log_alpha * (log_prob.detach() + self.target_entropy)).mean()
        self.alpha_opt.zero_grad(set_to_none=True)
        alpha_loss.backward()
        self.alpha_opt.step()

        with torch.no_grad():
            for target_param, param in zip(self.target_critic.parameters(), self.critic.parameters(), strict=True):
                target_param.lerp_(param, self.cfg.tau)

        return {
            "critic_loss": float(critic_loss.detach()),
            "actor_loss": float(actor_loss.detach()),
            "alpha_loss": float(alpha_loss.detach()),
            "alpha": float(self.alpha.detach()),
            "q": float(torch.min(q1, q2).mean().detach()),
        }

    def checkpoint(self, *, step: int, obs_dim: int, extra: dict | None = None) -> dict:
        return {
            "step": step,
            "obs_dim": obs_dim,
            "action_dim": self.action_dim,
            "sac_config": asdict(self.cfg),
            "actor": self.actor.state_dict(),
            "critic": self.critic.state_dict(),
            "target_critic": self.target_critic.state_dict(),
            "log_alpha": self.log_alpha.detach().cpu(),
            "extra": extra or {},
        }

    @classmethod
    def from_checkpoint(cls, path: str, device: torch.device) -> "SACAgent":
        data = torch.load(path, map_location=device, weights_only=False)
        agent = cls(data["obs_dim"], data["action_dim"], device, SACConfig(**data["sac_config"]))
        agent.actor.load_state_dict(data["actor"])
        agent.critic.load_state_dict(data["critic"])
        agent.target_critic.load_state_dict(data["target_critic"])
        agent.log_alpha.data.copy_(data["log_alpha"].to(device))
        return agent
