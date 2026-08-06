"""Gym wrapper that turns an IK expert into the base policy for residual RL."""

from __future__ import annotations

import gymnasium as gym
import numpy as np
from gymnasium import spaces

from .pick_place_expert import PickPlaceIKExpert


class IKResidualWrapper(gym.Wrapper):
    """Expose bounded residual actions while the wrapped task executes IK + Δa."""

    def __init__(self, env: gym.Env, expert: PickPlaceIKExpert, residual_scale: float = 0.10) -> None:
        super().__init__(env)
        if residual_scale <= 0:
            raise ValueError("residual_scale must be positive")
        self.expert = expert
        self.residual_scale = residual_scale
        self.action_space = spaces.Box(
            -residual_scale, residual_scale, shape=env.action_space.shape, dtype=np.float32
        )
        self._observation: dict[str, np.ndarray] | None = None

    def reset(self, **kwargs):
        observation, info = self.env.reset(**kwargs)
        self.expert.reset()
        self._observation = observation
        return observation, info

    def step(self, residual_action: np.ndarray):
        if self._observation is None:
            raise RuntimeError("reset must be called before step")
        residual = np.clip(np.asarray(residual_action, dtype=np.float32), -self.residual_scale, self.residual_scale)
        base_action = self.expert.action(self._observation)
        action = base_action + residual
        observation, reward, terminated, truncated, info = self.env.step(action)
        info = {**info, "ik_action": base_action, "residual_action": residual}
        self._observation = observation
        return observation, reward, terminated, truncated, info
