"""Gym adapter for PPO residual learning on top of visual-servo IK."""

from __future__ import annotations

import gymnasium as gym
import numpy as np
from gymnasium import spaces

from .visual_servo import VisualServoController


_PHASES = ("approach", "grasp", "close", "lift", "transfer", "place", "release", "retreat")


class VisualServoResidualWrapper(gym.Wrapper):
    """Expose compact visual/contact features and execute base-action residuals."""

    def __init__(
        self, env: gym.Env, controller: VisualServoController, *, residual_scale: float = 0.01,
        action_noise_std: float = 0.0, noise_seed: int = 0,
    ) -> None:
        super().__init__(env)
        self.controller = controller
        self.residual_scale = float(residual_scale)
        self.action_noise_std = float(action_noise_std)
        if self.residual_scale <= 0.0:
            raise ValueError("residual_scale must be positive")
        self.action_space = spaces.Box(
            -self.residual_scale, self.residual_scale, shape=env.action_space.shape, dtype=np.float32,
        )
        # proprio 25, two XY points + valid flags 6, contact 4, phase 8, base action 9
        self.observation_space = spaces.Box(-np.inf, np.inf, shape=(52,), dtype=np.float32)
        self._observation: dict[str, np.ndarray] | None = None
        self._last_info: dict[str, object] = {}
        self._last_base_action = np.zeros(env.action_space.shape, dtype=np.float32)
        self._noise_generator = np.random.default_rng(noise_seed)

    def _features(self, observation: dict[str, np.ndarray]) -> np.ndarray:
        object_xy, target_xy = self.controller.perception.estimate(observation["camera"])
        visual = np.zeros(6, dtype=np.float32)
        if object_xy is not None:
            visual[:2], visual[4] = object_xy, 1.0
        if target_xy is not None:
            visual[2:4], visual[5] = target_xy, 1.0
        proprio = np.concatenate((
            observation["joint_position"], observation["joint_velocity"], observation["end_effector_pose"],
        )).astype(np.float32)
        contact = np.asarray([
            float(self.controller.contact_verifier.grasp_verified),
            float(self.controller.env.is_grasped),
            min(float(self._last_info.get("robot_object_contact_force", 0.0)) / 300.0, 1.0),
            min(float(self._last_info.get("consecutive_dual_finger_contact_steps", 0)) / 10.0, 1.0),
        ], dtype=np.float32)
        phase = np.zeros(len(_PHASES), dtype=np.float32)
        phase[_PHASES.index(self.controller.expert.phase)] = 1.0
        return np.concatenate((proprio, visual, contact, phase, self._last_base_action)).astype(np.float32)

    def reset(self, **kwargs):
        observation, info = self.env.reset(**kwargs)
        self.controller.reset()
        self._observation = observation
        self._last_info = {}
        self._last_base_action.fill(0.0)
        return self._features(observation), info

    def step(self, residual_action: np.ndarray):
        if self._observation is None:
            raise RuntimeError("reset must be called before step")
        residual = np.clip(np.asarray(residual_action, dtype=np.float32), -self.residual_scale, self.residual_scale)
        try:
            self._last_base_action = self.controller.action(self._observation)
        except RuntimeError as error:
            # A missing marker is an evaluation failure mode, not a reason to
            # emit an undefined action into the rigid simulator.
            self._last_base_action = np.asarray(self._observation["joint_position"], dtype=np.float32).copy()
            self._last_base_action[-2:] = 0.04
            info = {"visual_servo_error": str(error), "is_success": False}
            return self._features(self._observation), -1.0, False, True, info
        action = self._last_base_action + residual
        if self.action_noise_std:
            action = action + self._noise_generator.normal(0.0, self.action_noise_std, size=action.shape).astype(np.float32)
        observation, reward, terminated, truncated, info = self.env.step(action)
        self.controller.update_feedback(info, observation)
        self._observation, self._last_info = observation, info
        return self._features(observation), reward, terminated, truncated, {
            **info, "base_action": self._last_base_action, "residual_action": residual,
        }
