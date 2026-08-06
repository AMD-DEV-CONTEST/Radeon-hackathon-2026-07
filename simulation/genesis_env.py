"""Gymnasium-style Genesis environment for a Franka pick-and-place task."""

from __future__ import annotations

from typing import Any, Callable

import gymnasium as gym
import numpy as np
from gymnasium import spaces

from .camera import Camera
from .objects import PickPlaceObjects
from .robot import FrankaRobot


class GenesisPickPlaceEnv(gym.Env[dict[str, np.ndarray], np.ndarray]):
    """Gymnasium-compatible Genesis pick-and-place environment.

    ``scene`` must be a built Genesis scene and is advanced through its public
    ``step`` method. The default state-only observation is compatible with
    :class:`gymnasium.wrappers.FlattenObservation`, which is required by the
    vectorized PPO trainer.
    """

    metadata = {"render_modes": ["rgb_array"], "render_fps": 60}

    def __init__(
        self,
        scene: Any,
        robot: FrankaRobot,
        objects: PickPlaceObjects,
        camera: Camera | None = None,
        presentation_camera: Camera | None = None,
        *,
        control_decimation: int = 4,
        max_episode_steps: int = 400,
        success_threshold: float = 0.03,
        require_release_for_success: bool = True,
        require_lift_for_success: bool = True,
        lift_success_height: float = 0.03,
        domain_randomizer: Callable[[], dict[str, Any]] | None = None,
        assist_grasp: bool = True,
        require_dual_finger_contact_for_assist: bool = False,
        assist_contact_steps: int = 3,
        grasp_distance: float = 0.15,
        gripper_closed_threshold: float = 0.01,
        gripper_open_threshold: float = 0.03,
        grasp_offset: tuple[float, float, float] = (0.0, 0.0, -0.07),
    ) -> None:
        super().__init__()
        if control_decimation < 1:
            raise ValueError("control_decimation must be at least 1")

        self.scene = scene
        self.robot = robot
        self.objects = objects
        self.camera = camera
        self.presentation_camera = presentation_camera
        self.control_decimation = control_decimation
        self.max_episode_steps = max_episode_steps
        self.success_threshold = success_threshold
        self.require_release_for_success = require_release_for_success
        self.require_lift_for_success = require_lift_for_success
        self.lift_success_height = lift_success_height
        self.domain_randomizer = domain_randomizer
        self.assist_grasp = assist_grasp
        self.require_dual_finger_contact_for_assist = require_dual_finger_contact_for_assist
        self.assist_contact_steps = assist_contact_steps
        self.grasp_distance = grasp_distance
        self.gripper_closed_threshold = gripper_closed_threshold
        self.gripper_open_threshold = gripper_open_threshold
        self.grasp_offset = np.asarray(grasp_offset, dtype=np.float32)
        self.is_grasped = False
        self._weld_active = False
        self.last_domain_randomization: dict[str, Any] | None = None
        self.episode_step = 0
        self.object_was_lifted = False
        self.consecutive_dual_finger_contact_steps = 0
        self.max_consecutive_dual_finger_contact_steps = 0
        self.is_grasped = False
        joint_dim = int(self.robot.initial_joint_positions.size)
        self.action_space = spaces.Box(
            low=-np.inf, high=np.inf, shape=(joint_dim,), dtype=np.float32
        )
        observation_spaces: dict[str, spaces.Box] = {
            "joint_position": spaces.Box(-np.inf, np.inf, shape=(joint_dim,), dtype=np.float32),
            "joint_velocity": spaces.Box(-np.inf, np.inf, shape=(joint_dim,), dtype=np.float32),
            "end_effector_pose": spaces.Box(-np.inf, np.inf, shape=(7,), dtype=np.float32),
            "object_pose": spaces.Box(-np.inf, np.inf, shape=(7,), dtype=np.float32),
            "target_pose": spaces.Box(-np.inf, np.inf, shape=(7,), dtype=np.float32),
        }
        if self.camera is not None:
            frame = self.camera.observation()
            observation_spaces["camera"] = spaces.Box(
                low=0, high=255, shape=frame.shape, dtype=frame.dtype
            )
        self.observation_space = spaces.Dict(observation_spaces)

    def reset(
        self, *, seed: int | None = None, options: dict[str, Any] | None = None
    ) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
        """Reset Genesis and return the first task observation and metadata."""
        super().reset(seed=seed)
        del options  # Reserved for Gymnasium compatibility; task has no reset-time overrides.

        self._release_grasp()
        self.scene.reset()
        self.robot.reset()
        self.objects.reset()
        if self.domain_randomizer is not None:
            self.last_domain_randomization = self.domain_randomizer()
            self.objects.apply_randomization(self.last_domain_randomization)
        else:
            self.last_domain_randomization = None
        self.episode_step = 0
        self.object_was_lifted = False
        self.consecutive_dual_finger_contact_steps = 0
        self.max_consecutive_dual_finger_contact_steps = 0

        observation = self._observation()
        info = {
            "is_success": False,
            "episode_step": self.episode_step,
            "domain_randomization": self._serializable_randomization(),
        }
        return observation, info

    def step(
        self, action: np.ndarray
    ) -> tuple[dict[str, np.ndarray], float, bool, bool, dict[str, Any]]:
        """Apply one action using Gymnasium's terminated/truncated convention."""
        if not self.action_space.contains(np.asarray(action, dtype=np.float32)):
            raise ValueError(f"action must have shape {self.action_space.shape}")
        self.robot.apply_action(action)
        contact_stats: dict[str, float | int | bool] = {
            "robot_object_contact_count": 0,
            "robot_object_contact_force": 0.0,
            "left_finger_contact_count": 0,
            "right_finger_contact_count": 0,
            "dual_finger_contact": False,
        }
        for _ in range(self.control_decimation):
            self.scene.step()
            contact_stats = self._robot_object_contact_stats()
            self._update_dual_finger_contact_state(contact_stats)
            self._update_grasp_constraint(action)

        self.episode_step += 1
        initial_height = float(self.objects.initial_position[2])
        self.object_was_lifted |= bool(
            self.objects.object_position()[2] >= initial_height + self.lift_success_height
        )
        distance = self.objects.distance_to_goal()
        is_success = distance <= self.success_threshold and (
            not self.require_release_for_success or not self.is_grasped
        ) and (not self.require_lift_for_success or self.object_was_lifted)
        timed_out = self.episode_step >= self.max_episode_steps
        reward = self._reward(distance=distance, is_success=is_success)
        info = {
            "is_success": is_success,
            "distance_to_goal": distance,
            "episode_step": self.episode_step,
            "time_limit_reached": timed_out,
            "is_grasped": self.is_grasped,
            "object_was_lifted": self.object_was_lifted,
            "consecutive_dual_finger_contact_steps": self.consecutive_dual_finger_contact_steps,
            "max_consecutive_dual_finger_contact_steps": self.max_consecutive_dual_finger_contact_steps,
            **contact_stats,
        }
        return self._observation(), reward, is_success, timed_out, info

    def _update_grasp_constraint(self, action: np.ndarray) -> None:
        """Apply an optional weld-grasp curriculum for stable early training.

        Contact-only pinch grasps are brittle when the initial policy is still
        inaccurate. Once a closed gripper reaches the object, this curriculum
        creates Genesis' runtime weld constraint; opening deletes it.
        Disable ``assist_grasp`` for final contact-realism evaluation.
        """
        if not self.assist_grasp or action.size < 2:
            return
        gripper_opening = float(np.mean(np.asarray(action[-2:], dtype=np.float32)))
        if self.is_grasped:
            if gripper_opening >= self.gripper_open_threshold:
                self._release_grasp()
            return
        if gripper_opening <= self.gripper_closed_threshold:
            if self.require_dual_finger_contact_for_assist:
                can_latch = (
                    self.consecutive_dual_finger_contact_steps >= self.assist_contact_steps
                )
            else:
                distance = np.linalg.norm(
                    self.robot.end_effector_pose()[:3] - self.objects.object_position()
                )
                can_latch = distance <= self.grasp_distance
            if can_latch:
                # The latch is conditional on a physically observed pinch in
                # contact-confirmed mode, then acts as a stable grasp model
                # during transport. Opening the fingers always releases it.
                self.objects.set_position(self.robot.end_effector_pose()[:3] + self.grasp_offset)
                rigid = self.scene.sim.rigid_solver
                cube_link = np.asarray([self.objects.object_entity.base_link.idx], dtype=np.int32)
                hand_link = np.asarray([self.robot.end_effector.idx], dtype=np.int32)
                rigid.add_weld_constraint(cube_link, hand_link)
                self._weld_active = self.is_grasped = True

    def _update_dual_finger_contact_state(self, contact_stats: dict[str, float | int | bool]) -> None:
        """Track current and episode-maximum durations of two-finger contact."""
        if bool(contact_stats["dual_finger_contact"]):
            self.consecutive_dual_finger_contact_steps += 1
        else:
            self.consecutive_dual_finger_contact_steps = 0
        self.max_consecutive_dual_finger_contact_steps = max(
            self.max_consecutive_dual_finger_contact_steps,
            self.consecutive_dual_finger_contact_steps,
        )

    def _release_grasp(self) -> None:
        if not self._weld_active:
            self.is_grasped = False
            return
        rigid = self.scene.sim.rigid_solver
        cube_link = np.asarray([self.objects.object_entity.base_link.idx], dtype=np.int32)
        hand_link = np.asarray([self.robot.end_effector.idx], dtype=np.int32)
        rigid.delete_weld_constraint(cube_link, hand_link)
        self._weld_active = self.is_grasped = False

    def render(self) -> np.ndarray | None:
        """Render the configured task camera, if one was supplied."""
        return None if self.camera is None else self.camera.observation()

    def render_presentation(self) -> np.ndarray | None:
        """Render the optional high-resolution camera used only for demos."""
        camera = self.presentation_camera or self.camera
        return None if camera is None else camera.observation()

    def _observation(self) -> dict[str, np.ndarray]:
        """Return qpos, qvel, end-effector, object, and target task state."""
        observation = {**self.robot.observation(), **self.objects.observation()}
        if self.camera is not None:
            observation["camera"] = self.camera.observation()
        return observation

    def _serializable_randomization(self) -> dict[str, Any] | None:
        """Return reset parameters in a JSON-friendly form for dataset audit."""
        if self.last_domain_randomization is None:
            return None
        return {
            name: value.tolist() if isinstance(value, np.ndarray) else value
            for name, value in self.last_domain_randomization.items()
        }

    def _robot_object_contact_stats(self) -> dict[str, float | int]:
        """Summarize physical robot--object contact from the latest sim step.

        This is deliberately independent of ``assist_grasp``.  It lets the
        contact-only curriculum distinguish no contact, a pushing contact, and
        a candidate pinch before interpreting a failed demonstration.
        """
        contacts = self.objects.object_entity.get_contacts(with_entity=self.robot.entity)
        force = contacts.get("force_a")
        if force is None:
            return {
                "robot_object_contact_count": 0,
                "robot_object_contact_force": 0.0,
                "left_finger_contact_count": 0,
                "right_finger_contact_count": 0,
                "dual_finger_contact": False,
            }
        if hasattr(force, "detach") and hasattr(force, "cpu"):
            force = force.detach().cpu().numpy()
        link_a, link_b = contacts["link_a"], contacts["link_b"]
        if hasattr(link_a, "detach") and hasattr(link_a, "cpu"):
            link_a = link_a.detach().cpu().numpy()
        if hasattr(link_b, "detach") and hasattr(link_b, "cpu"):
            link_b = link_b.detach().cpu().numpy()
        force_array = np.asarray(force, dtype=np.float32).reshape(-1, 3)
        contact_links = np.concatenate((np.asarray(link_a).reshape(-1), np.asarray(link_b).reshape(-1)))
        left_idx, right_idx = self.robot.finger_link_indices
        left_count = int(np.count_nonzero(contact_links == left_idx))
        right_count = int(np.count_nonzero(contact_links == right_idx))
        return {
            "robot_object_contact_count": int(force_array.shape[0]),
            "robot_object_contact_force": float(np.linalg.norm(force_array, axis=-1).sum()),
            "left_finger_contact_count": left_count,
            "right_finger_contact_count": right_count,
            "dual_finger_contact": bool(left_count and right_count),
        }

    @staticmethod
    def _reward(*, distance: float, is_success: bool) -> float:
        """Dense shaping reward with a terminal success bonus."""
        return -float(distance) + (1.0 if is_success else 0.0)
