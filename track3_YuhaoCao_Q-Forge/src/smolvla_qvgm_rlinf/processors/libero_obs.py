"""Convert raw LIBERO observations to the canonical RLinf/SmolVLA fields."""

from __future__ import annotations

from typing import Any

import numpy as np


def quaternion_xyzw_to_axis_angle(quaternion: np.ndarray) -> np.ndarray:
    """Convert one XYZW quaternion to a three-dimensional rotation vector."""
    quat = np.asarray(quaternion, dtype=np.float64).copy()
    if quat.shape != (4,):
        raise ValueError(f"quaternion must have shape (4,), got {quat.shape}")
    norm = np.linalg.norm(quat)
    if not np.isfinite(norm) or norm == 0:
        raise ValueError("quaternion must be finite and nonzero")
    quat /= norm
    # q and -q encode the same rotation. Select the shortest rotation.
    if quat[3] < 0:
        quat = -quat
    xyz_norm = np.linalg.norm(quat[:3])
    if xyz_norm < 1e-12:
        return np.zeros(3, dtype=np.float32)
    angle = 2.0 * np.arctan2(xyz_norm, np.clip(quat[3], -1.0, 1.0))
    return (quat[:3] / xyz_norm * angle).astype(np.float32)


def build_libero_state(raw_observation: dict[str, Any]) -> np.ndarray:
    """Build SmolVLA's 8D LIBERO state: xyz, rotation vector, gripper qpos."""
    position = np.asarray(raw_observation["robot0_eef_pos"], dtype=np.float32)
    gripper = np.asarray(raw_observation["robot0_gripper_qpos"], dtype=np.float32)
    if position.shape != (3,) or gripper.shape != (2,):
        raise ValueError(
            f"expected eef_pos=(3,) and gripper_qpos=(2,), got {position.shape} and {gripper.shape}"
        )
    rotation = quaternion_xyzw_to_axis_angle(raw_observation["robot0_eef_quat"])
    return np.concatenate((position, rotation, gripper)).astype(np.float32)


def orient_libero_image(image: np.ndarray) -> np.ndarray:
    """Rotate a raw simulator image 180 degrees to match LIBERO datasets."""
    array = np.asarray(image)
    if array.ndim != 3 or array.shape[-1] != 3:
        raise ValueError(f"expected HWC RGB image, got {array.shape}")
    return np.ascontiguousarray(array[::-1, ::-1])


def prepare_raw_libero_observation(
    raw_observation: dict[str, Any], task_description: str
) -> dict[str, Any]:
    """Return one unbatched observation in RLinf's canonical field convention."""
    return {
        "main_images": orient_libero_image(raw_observation["agentview_image"]),
        "wrist_images": orient_libero_image(raw_observation["robot0_eye_in_hand_image"]),
        "states": build_libero_state(raw_observation),
        "task_descriptions": task_description,
    }
