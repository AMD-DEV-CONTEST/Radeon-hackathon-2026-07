"""Evaluation-only observation and action perturbations for robustness tests."""

from __future__ import annotations

from typing import Mapping

import gymnasium as gym
import numpy as np


class ObservationNoiseWrapper(gym.Wrapper):
    """Add deterministic Gaussian noise to selected vector observations."""

    def __init__(self, env: gym.Env, noise_std: Mapping[str, float], *, seed: int) -> None:
        super().__init__(env)
        self.noise_std = {key: float(value) for key, value in noise_std.items() if float(value) > 0.0}
        self.generator = np.random.default_rng(seed)

    def _perturb(self, observation):
        if not self.noise_std:
            return observation
        noisy = dict(observation)
        for key, std in self.noise_std.items():
            if key not in noisy:
                continue
            value = np.asarray(noisy[key])
            if not np.issubdtype(value.dtype, np.floating):
                continue
            noisy[key] = (value + self.generator.normal(0.0, std, size=value.shape)).astype(value.dtype)
        return noisy

    def reset(self, **kwargs):
        observation, info = self.env.reset(**kwargs)
        return self._perturb(observation), info

    def step(self, action):
        observation, reward, terminated, truncated, info = self.env.step(action)
        return self._perturb(observation), reward, terminated, truncated, info


class ActionNoiseWrapper(gym.Wrapper):
    """Inject deterministic joint-position command noise before stepping Genesis."""

    def __init__(self, env: gym.Env, joint_position_std: float, *, seed: int) -> None:
        super().__init__(env)
        self.joint_position_std = float(joint_position_std)
        if self.joint_position_std < 0.0:
            raise ValueError("joint_position_std must be non-negative")
        self.generator = np.random.default_rng(seed)

    def step(self, action):
        action = np.asarray(action, dtype=np.float32)
        if self.joint_position_std:
            action = action + self.generator.normal(0.0, self.joint_position_std, size=action.shape).astype(np.float32)
        # Preserve finite action-space bounds such as gripper opening limits.
        return self.env.step(np.clip(action, self.action_space.low, self.action_space.high))
