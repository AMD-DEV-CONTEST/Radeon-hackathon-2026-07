"""CleanRL PPO adaptation that learns only Franka residual actions.

This is adapted from CleanRL's ``ppo_continuous_action.py``.  The PPO rollout,
GAE, clipping, value loss, and optimizer update follow CleanRL; the only policy
change is replacing the actor mean with :class:`ResidualPolicy` and fusing that
sampled residual with an IK action before calling ``env.step``.
"""

from __future__ import annotations

import time
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import numpy as np
import torch
from torch import nn, optim
from torch.distributions.normal import Normal
from torch.utils.tensorboard import SummaryWriter

from .residual_policy import ResidualPolicy, fuse_actions


@dataclass
class PPOConfig:
    num_steps: int = 256
    update_epochs: int = 4
    num_minibatches: int = 4
    learning_rate: float = 3e-4
    gamma: float = 0.99
    gae_lambda: float = 0.95
    clip_coef: float = 0.2
    ent_coef: float = 0.0
    vf_coef: float = 0.5
    max_grad_norm: float = 0.5
    residual_l2_coef: float = 0.1


class ResidualActorCritic(nn.Module):
    """CleanRL continuous-action agent API with a residual-only actor."""

    def __init__(self, observation_dim: int, action_dim: int, residual_scale: float) -> None:
        super().__init__()
        self.actor_mean = ResidualPolicy(observation_dim, action_dim, residual_scale=residual_scale)
        # Residual actions are measured in joint-position increments. Starting
        # with unit-variance exploration would immediately saturate the wrapper
        # action bounds and destroy the competent IK baseline.
        initial_std = max(residual_scale * 0.25, 1e-4)
        self.actor_logstd = nn.Parameter(torch.full((1, action_dim), math.log(initial_std)))
        self.critic = nn.Sequential(
            nn.Linear(observation_dim, 256), nn.Tanh(), nn.Linear(256, 256), nn.Tanh(), nn.Linear(256, 1)
        )

    def get_value(self, obs: torch.Tensor) -> torch.Tensor:
        return self.critic(obs)

    def get_action_and_value(
        self, obs: torch.Tensor, action: torch.Tensor | None = None
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
        mean = self.actor_mean(obs)
        distribution = Normal(mean, self.actor_logstd.expand_as(mean).exp())
        if action is None:
            action = distribution.sample()
        return action, distribution.log_prob(action).sum(-1), distribution.entropy().sum(-1), self.critic(obs)


class CleanRLPPOTrainer:
    """Train residual actions with CleanRL's PPO update and report GPU metrics.

    ``env`` must be a Gymnasium vector environment. ``ik_action_fn`` receives a
    tensor batch of flattened observations and returns equally shaped IK actions.
    The environment receives only the fused final action.
    """

    def __init__(
        self,
        observation_dim: int,
        action_dim: int,
        *,
        config: PPOConfig | None = None,
        residual_scale: float = 0.10,
        device: str = "cuda",
        log_dir: str | Path = "logs/residual_ppo",
    ) -> None:
        self.config = config or PPOConfig()
        self.device = torch.device(device)
        self.agent = ResidualActorCritic(observation_dim, action_dim, residual_scale).to(self.device)
        self.optimizer = optim.Adam(self.agent.parameters(), lr=self.config.learning_rate, eps=1e-5)
        self.writer = SummaryWriter(log_dir=str(log_dir))
        self.metrics: list[dict[str, float]] = []

    @torch.no_grad()
    def final_action(self, observation: torch.Tensor, ik_action: torch.Tensor) -> torch.Tensor:
        """Sample a residual policy action and calculate ``a_ik + Δa``."""
        delta_action, _, _, _ = self.agent.get_action_and_value(observation)
        return fuse_actions(ik_action, delta_action)

    def save_checkpoint(self, path: str | Path, *, global_step: int, extra: dict[str, Any] | None = None) -> Path:
        """Persist model, optimizer, PPO config, and caller-provided provenance."""
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        torch.save({
            "global_step": global_step, "agent": self.agent.state_dict(),
            "optimizer": self.optimizer.state_dict(), "config": self.config.__dict__,
            "extra": extra or {},
        }, output)
        return output

    def load_checkpoint(self, path: str | Path) -> dict[str, Any]:
        """Restore a compatible PPO checkpoint and return its metadata."""
        payload = torch.load(path, map_location=self.device, weights_only=False)
        self.agent.load_state_dict(payload["agent"])
        self.optimizer.load_state_dict(payload["optimizer"])
        return payload

    def train(
        self,
        env: Any,
        ik_action_fn: Callable[[torch.Tensor], torch.Tensor],
        total_timesteps: int,
    ) -> list[dict[str, float]]:
        """Run CleanRL-style PPO updates on a vectorized residual-action environment."""
        num_envs = int(env.num_envs)
        batch_size = num_envs * self.config.num_steps
        if batch_size % self.config.num_minibatches:
            raise ValueError("num_steps * num_envs must divide evenly into num_minibatches")
        minibatch_size = batch_size // self.config.num_minibatches
        next_obs, _ = env.reset()
        next_obs = self._tensor(next_obs)
        next_done = torch.zeros(num_envs, device=self.device)
        start_time, global_step = time.perf_counter(), 0

        while global_step < total_timesteps:
            storage = self._rollout(env, ik_action_fn, next_obs, next_done, num_envs)
            next_obs, next_done = storage["next_obs"], storage["next_done"]
            global_step += batch_size
            self._update(storage, batch_size, minibatch_size)
            metric = self._metrics(storage, global_step, start_time)
            self.metrics.append(metric)
            for name, value in metric.items():
                self.writer.add_scalar(f"charts/{name}", value, global_step)
        self.writer.flush()
        return self.metrics

    def _rollout(self, env: Any, ik_fn: Callable[[torch.Tensor], torch.Tensor], obs: torch.Tensor, done: torch.Tensor, n: int) -> dict[str, torch.Tensor]:
        shape = (self.config.num_steps, n)
        observations = torch.zeros((self.config.num_steps, n, obs.shape[-1]), device=self.device)
        actions = torch.zeros((self.config.num_steps, n, self.agent.actor_logstd.shape[-1]), device=self.device)
        logprobs = torch.zeros(shape, device=self.device)
        rewards, dones, values = (torch.zeros(shape, device=self.device) for _ in range(3))
        successes: list[float] = []
        for step in range(self.config.num_steps):
            observations[step], dones[step] = obs, done
            with torch.no_grad():
                delta, logprob, _, value = self.agent.get_action_and_value(obs)
                final = fuse_actions(ik_fn(obs).to(self.device), delta)
            actions[step], logprobs[step], values[step] = delta, logprob, value.flatten()
            next_obs, reward, terminated, truncated, info = env.step(final.cpu().numpy())
            done = self._tensor(np.logical_or(terminated, truncated), dtype=torch.float32)
            rewards[step], obs = self._tensor(reward), self._tensor(next_obs)
            successes.extend(self._success_values(info))
        with torch.no_grad():
            next_value = self.agent.get_value(obs).flatten()
            advantages = torch.zeros_like(rewards)
            last_gae = torch.zeros(n, device=self.device)
            for step in reversed(range(self.config.num_steps)):
                nonterminal = 1.0 - (done if step == self.config.num_steps - 1 else dones[step + 1])
                next_values = next_value if step == self.config.num_steps - 1 else values[step + 1]
                delta = rewards[step] + self.config.gamma * next_values * nonterminal - values[step]
                advantages[step] = last_gae = delta + self.config.gamma * self.config.gae_lambda * nonterminal * last_gae
        return {"obs": observations, "actions": actions, "logprobs": logprobs, "advantages": advantages,
                "returns": advantages + values, "values": values, "next_obs": obs, "next_done": done,
                "reward_mean": rewards.mean(), "success_rate": float(np.mean(successes)) if successes else 0.0}

    def _update(self, data: dict[str, torch.Tensor], batch_size: int, minibatch_size: int) -> None:
        indices = np.arange(batch_size)
        b_obs, b_actions = data["obs"].reshape(batch_size, -1), data["actions"].reshape(batch_size, -1)
        b_logprobs, b_advantages = data["logprobs"].reshape(-1), data["advantages"].reshape(-1)
        b_returns, b_values = data["returns"].reshape(-1), data["values"].reshape(-1)
        for _ in range(self.config.update_epochs):
            np.random.shuffle(indices)
            for start in range(0, batch_size, minibatch_size):
                mb = indices[start : start + minibatch_size]
                _, new_logprob, entropy, new_value = self.agent.get_action_and_value(b_obs[mb], b_actions[mb])
                ratio = (new_logprob - b_logprobs[mb]).exp()
                advantage = (b_advantages[mb] - b_advantages[mb].mean()) / (b_advantages[mb].std() + 1e-8)
                policy_loss = torch.maximum(-advantage * ratio, -advantage * ratio.clamp(1 - self.config.clip_coef, 1 + self.config.clip_coef)).mean()
                value_loss = 0.5 * (new_value.flatten() - b_returns[mb]).pow(2).mean()
                # In an IK-residual controller, zero is a competent and safe
                # prior.  Penalize the *mean* residual (not sampled exploration)
                # to prevent short PPO runs from replacing the IK solution.
                mean_residual = self.agent.actor_mean(b_obs[mb])
                normalized_residual_l2 = (
                    mean_residual / self.agent.actor_mean.residual_scale
                ).pow(2).mean()
                loss = (
                    policy_loss
                    - self.config.ent_coef * entropy.mean()
                    + self.config.vf_coef * value_loss
                    + self.config.residual_l2_coef * normalized_residual_l2
                )
                self.optimizer.zero_grad()
                loss.backward()
                nn.utils.clip_grad_norm_(self.agent.parameters(), self.config.max_grad_norm)
                self.optimizer.step()

    def _metrics(self, data: dict[str, torch.Tensor], step: int, started: float) -> dict[str, float]:
        elapsed = max(time.perf_counter() - started, 1e-6)
        memory = torch.cuda.max_memory_allocated(self.device) / (1024**2) if self.device.type == "cuda" else 0.0
        return {"reward": float(data["reward_mean"]), "success_rate": float(data["success_rate"]),
                "fps": step / elapsed, "gpu_memory_mb": memory}

    def _tensor(self, value: Any, dtype: torch.dtype = torch.float32) -> torch.Tensor:
        return torch.as_tensor(value, dtype=dtype, device=self.device).reshape(len(value), -1)

    @staticmethod
    def _success_values(info: Any) -> list[float]:
        if isinstance(info, dict) and "is_success" in info:
            values = np.asarray(info["is_success"], dtype=np.float32).reshape(-1)
            # Gymnasium vector environments use a companion mask when an info
            # key is present for only a subset of workers.
            mask = info.get("_is_success")
            if mask is not None:
                values = values[np.asarray(mask, dtype=bool).reshape(-1)]
            return values.tolist()
        return []
