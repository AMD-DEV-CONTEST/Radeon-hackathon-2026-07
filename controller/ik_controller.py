"""Damped-least-squares IK expert policy for the Franka Panda."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import torch


class IKController:
    """Generate stable joint-delta expert actions from Genesis Jacobians.

    ``current_pose`` and ``target_pose`` are `[x, y, z, qw, qx, qy, qz]`.
    The returned action is a joint-position delta using
    ``J.T @ inv(J @ J.T + damping * I) @ pose_error``.
    """

    def __init__(
        self,
        robot: Any | None = None,
        end_effector: Any | None = None,
        *,
        damping: float = 0.05,
        position_gain: float = 1.0,
        rotation_gain: float = 0.5,
        max_joint_delta: float = 0.10,
        device: str = "cuda",
    ) -> None:
        if damping <= 0.0:
            raise ValueError("damping must be positive")
        self.robot = robot
        self.end_effector = end_effector
        self.damping = damping
        self.position_gain = position_gain
        self.rotation_gain = rotation_gain
        self.max_joint_delta = max_joint_delta
        self.device = torch.device(device)

    def compute_action(
        self,
        current_pose: torch.Tensor | np.ndarray,
        target_pose: torch.Tensor | np.ndarray,
    ) -> torch.Tensor:
        """Return a DLS joint delta using the current Genesis Jacobian."""
        if self.robot is None or self.end_effector is None:
            raise RuntimeError("robot and end_effector are required to query the Genesis Jacobian")
        jacobian = self.robot.get_jacobian(link=self.end_effector)
        return self.compute_action_from_jacobian(current_pose, target_pose, jacobian)

    def compute_action_from_jacobian(
        self,
        current_pose: torch.Tensor | np.ndarray,
        target_pose: torch.Tensor | np.ndarray,
        jacobian: torch.Tensor | np.ndarray,
    ) -> torch.Tensor:
        """Compute DLS action from an explicit Jacobian; useful for tests/batches."""
        current = torch.as_tensor(current_pose, dtype=torch.float32, device=self.device)
        target = torch.as_tensor(target_pose, dtype=torch.float32, device=self.device)
        jacobian = torch.as_tensor(jacobian, dtype=torch.float32, device=self.device)
        if current.shape[-1] != 7 or target.shape[-1] != 7:
            raise ValueError("poses must end in 7 values: xyz + wxyz quaternion")
        if jacobian.shape[-2] != 6:
            raise ValueError("Jacobian must have shape (..., 6, n_dofs)")

        error = self._pose_error(current, target)
        identity = torch.eye(6, dtype=jacobian.dtype, device=self.device)
        system = jacobian @ jacobian.transpose(-1, -2) + self.damping * identity
        action = jacobian.transpose(-1, -2) @ torch.linalg.solve(system, error.unsqueeze(-1))
        return action.squeeze(-1).clamp(-self.max_joint_delta, self.max_joint_delta)

    def gripper_action(self, opening: float) -> torch.Tensor:
        """Return Panda's two symmetric gripper position targets in metres."""
        return torch.full((2,), float(opening), dtype=torch.float32, device=self.device)

    def _pose_error(self, current: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
        position_error = self.position_gain * (target[..., :3] - current[..., :3])
        current_quat = torch.nn.functional.normalize(current[..., 3:], dim=-1)
        target_quat = torch.nn.functional.normalize(target[..., 3:], dim=-1)
        quaternion_error = self._quat_multiply(target_quat, self._quat_conjugate(current_quat))
        sign = torch.where(quaternion_error[..., :1] < 0.0, -1.0, 1.0)
        rotation_error = self.rotation_gain * 2.0 * sign * quaternion_error[..., 1:]
        return torch.cat((position_error, rotation_error), dim=-1)

    @staticmethod
    def _quat_conjugate(quaternion: torch.Tensor) -> torch.Tensor:
        return torch.cat((quaternion[..., :1], -quaternion[..., 1:]), dim=-1)

    @staticmethod
    def _quat_multiply(lhs: torch.Tensor, rhs: torch.Tensor) -> torch.Tensor:
        lw, lx, ly, lz = lhs.unbind(dim=-1)
        rw, rx, ry, rz = rhs.unbind(dim=-1)
        return torch.stack(
            (lw * rw - lx * rx - ly * ry - lz * rz,
             lw * rx + lx * rw + ly * rz - lz * ry,
             lw * ry - lx * rz + ly * rw + lz * rx,
             lw * rz + lx * ry - ly * rx + lz * rw),
            dim=-1,
        )


class ExpertDatasetWriter:
    """Accumulate and persist expert demonstrations as NumPy arrays."""

    def __init__(self) -> None:
        self._states: list[np.ndarray] = []
        self._actions: list[np.ndarray] = []

    def append(self, state: torch.Tensor | np.ndarray, action: torch.Tensor | np.ndarray) -> None:
        self._states.append(self._to_numpy(state))
        self._actions.append(self._to_numpy(action))

    def save(self, directory: str | Path = "datasets/expert") -> tuple[Path, Path]:
        if not self._states:
            raise RuntimeError("cannot save an empty expert dataset")
        output = Path(directory)
        output.mkdir(parents=True, exist_ok=True)
        state_path, action_path = output / "state.npy", output / "action.npy"
        np.save(state_path, np.stack(self._states))
        np.save(action_path, np.stack(self._actions))
        return state_path, action_path

    @staticmethod
    def _to_numpy(value: torch.Tensor | np.ndarray) -> np.ndarray:
        if isinstance(value, torch.Tensor):
            value = value.detach().cpu().numpy()
        return np.asarray(value, dtype=np.float32)
