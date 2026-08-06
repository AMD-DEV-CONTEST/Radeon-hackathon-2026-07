"""Franka Panda loading and control through Genesis asset morphs."""

from __future__ import annotations

from typing import Any

import numpy as np


FRANKA_MJCF_ASSET = "xml/franka_emika_panda/panda.xml"
FRANKA_URDF_ASSET = "urdf/panda_bullet/panda.urdf"
DEFAULT_FRANKA_QPOS = np.array(
    [0.0, -0.785, 0.0, -2.356, 0.0, 1.571, 0.785, 0.04, 0.04],
    dtype=np.float32,
)


def _to_numpy(value: Any) -> np.ndarray:
    """Copy Genesis' device tensors to host before exposing Gym observations.

    ROCm PyTorch intentionally uses the ``cuda`` device API for compatibility;
    therefore a value reported as ``cuda:0`` can be an AMD HIP tensor.
    """
    if hasattr(value, "detach") and hasattr(value, "cpu"):
        value = value.detach().cpu()
    return np.asarray(value, dtype=np.float32)


def load_franka_panda(
    scene: Any,
    *,
    asset_format: str = "mjcf",
    position: tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> Any:
    """Load Genesis' bundled Franka Panda asset into ``scene``.

    The robot model is supplied entirely by Genesis.  Use ``asset_format='mjcf'``
    (the default) or ``'urdf'``; URDF requires ``fixed=True`` because it does
    not define a base joint to the world.
    """
    try:
        import genesis as gs
    except ImportError as error:
        raise ImportError("Genesis must be installed before loading Franka Panda.") from error

    if asset_format == "mjcf":
        morph = gs.morphs.MJCF(file=FRANKA_MJCF_ASSET, pos=position)
    elif asset_format == "urdf":
        morph = gs.morphs.URDF(file=FRANKA_URDF_ASSET, pos=position, fixed=True)
    else:
        raise ValueError("asset_format must be either 'mjcf' or 'urdf'")
    return scene.add_entity(morph)


class FrankaRobot:
    """Keeps Genesis-specific robot calls behind a small controller interface."""

    def __init__(
        self,
        entity: Any,
        initial_joint_positions: np.ndarray = DEFAULT_FRANKA_QPOS,
        end_effector_link: str = "hand",
    ) -> None:
        self.entity = entity
        self.initial_joint_positions = np.asarray(initial_joint_positions, dtype=np.float32)
        self.end_effector = entity.get_link(end_effector_link)
        self.left_finger = entity.get_link("left_finger")
        self.right_finger = entity.get_link("right_finger")

    @property
    def finger_link_indices(self) -> tuple[int, int]:
        """Global rigid-link indices used to classify object contacts."""
        return int(self.left_finger.idx), int(self.right_finger.idx)

    def reset(self) -> None:
        self.entity.set_qpos(self.initial_joint_positions)

    def configure_contact_gripper(
        self, *, friction: float, kp: float, kv: float, force_limit: float
    ) -> None:
        """Configure the two finger PD drives for contact-only grasping."""
        finger_dofs = np.asarray([7, 8], dtype=np.int32)
        self.entity.set_friction(float(friction))
        self.entity.set_dofs_kp(
            np.full(2, kp, dtype=np.float32), dofs_idx_local=finger_dofs
        )
        self.entity.set_dofs_kv(
            np.full(2, kv, dtype=np.float32), dofs_idx_local=finger_dofs
        )
        limits = np.full(2, force_limit, dtype=np.float32)
        self.entity.set_dofs_force_range(
            -limits, limits, dofs_idx_local=finger_dofs
        )

    def apply_action(self, action: np.ndarray) -> None:
        """Send joint-position targets (including gripper joints) to Genesis."""
        action = np.asarray(action, dtype=np.float32)
        self.entity.control_dofs_position(action)

    def observation(self) -> np.ndarray:
        """Return the required robot state: qpos, qvel, and hand pose."""
        qpos = self.entity.get_dofs_position()
        qvel = self.entity.get_dofs_velocity()
        return {
            "joint_position": _to_numpy(qpos),
            "joint_velocity": _to_numpy(qvel),
            "end_effector_pose": self.end_effector_pose(),
        }

    def end_effector_pose(self) -> np.ndarray:
        position = _to_numpy(self.end_effector.get_pos())
        quaternion = _to_numpy(self.end_effector.get_quat())
        return np.concatenate((position, quaternion))
