"""Pickable-object and placement-goal state for Genesis tasks."""

from __future__ import annotations

from typing import Any

import numpy as np

from .robot import _to_numpy


class PickPlaceObjects:
    """Manages the object pose and a fixed or randomized placement target."""

    def __init__(
        self,
        object_entity: Any,
        initial_position: np.ndarray,
        goal_position: np.ndarray,
        goal_quaternion: np.ndarray | None = None,
        target_marker_entity: Any | None = None,
    ) -> None:
        self.object_entity = object_entity
        self.initial_position = np.asarray(initial_position, dtype=np.float32)
        self.goal_position = np.asarray(goal_position, dtype=np.float32)
        self.initial_goal_position = self.goal_position.copy()
        self.goal_quaternion = np.asarray(
            (1.0, 0.0, 0.0, 0.0) if goal_quaternion is None else goal_quaternion,
            dtype=np.float32,
        )
        self.target_marker_entity = target_marker_entity

    def reset(self) -> None:
        self.set_position(self.initial_position)
        self.goal_position = self.initial_goal_position.copy()
        self._set_target_marker_position()

    def set_position(self, position: np.ndarray) -> None:
        """Set a user-frame pose and clear velocity after a discontinuity.

        ``get_pos()`` and ``set_pos()`` use Genesis' user frame by default;
        keeping ``relative=True`` makes task coordinates consistent with the
        observations returned to the policy. It is not a displacement flag.
        """
        self.object_entity.set_pos(
            np.asarray(position, dtype=np.float32), relative=True, zero_velocity=True
        )

    def apply_randomization(self, parameters: dict[str, Any]) -> None:
        """Apply mass, friction, and initial-position domain randomization."""
        mass = parameters["mass"]
        friction = parameters["friction"]
        position = parameters["object_position"]
        self.object_entity.set_mass(float(mass.item() if hasattr(mass, "item") else mass))
        self.object_entity.set_friction(float(friction.item() if hasattr(friction, "item") else friction))
        self.set_position(position)
        if "goal_position" in parameters:
            self.goal_position = np.asarray(parameters["goal_position"], dtype=np.float32)
            self._set_target_marker_position()

    def _set_target_marker_position(self) -> None:
        """Move the visual-only target marker without affecting contact physics."""
        if self.target_marker_entity is None:
            return
        marker_position = self.goal_position.copy()
        # The placement target denotes the cube center; keep the thin marker
        # on the table so it remains visible below the released cube.
        marker_position[2] = 0.003
        self.target_marker_entity.set_pos(marker_position, relative=True, zero_velocity=True)

    def object_position(self) -> np.ndarray:
        return _to_numpy(self.object_entity.get_pos())

    def object_pose(self) -> np.ndarray:
        return np.concatenate(
            (self.object_position(), _to_numpy(self.object_entity.get_quat()))
        )

    def target_pose(self) -> np.ndarray:
        return np.concatenate((self.goal_position, self.goal_quaternion))

    def distance_to_goal(self) -> float:
        return float(np.linalg.norm(self.object_position() - self.goal_position))

    def observation(self) -> dict[str, np.ndarray]:
        return {
            "object_pose": self.object_pose(),
            "target_pose": self.target_pose(),
        }
