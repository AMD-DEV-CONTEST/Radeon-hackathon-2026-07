"""Frozen observation / action protocol for RadeonVLA-Reflex.

This module is the single source of truth for joint ordering, control rate,
camera keys, and LeRobot feature schema. Training and evaluation must agree on
these constants; do not invent alternate layouts in downstream modules.
"""

from __future__ import annotations

from typing import Any

# Sim runs at dt=0.01 s (100 Hz). Policy / dataset capture is decimated to 20 Hz
# to match configs/base.yaml control_hz.
CONTROL_HZ = 100
CONTROL_DT = 0.01
DATASET_FPS = 20
POLICY_HZ = DATASET_FPS

JOINT_NAMES: tuple[str, ...] = (
    "panda_joint1",
    "panda_joint2",
    "panda_joint3",
    "panda_joint4",
    "panda_joint5",
    "panda_joint6",
    "panda_joint7",
    "panda_finger_joint1",
    "panda_finger_joint2",
)

ACTION_DIM = len(JOINT_NAMES)
STATE_DIM = ACTION_DIM
ARM_DOF_INDICES = tuple(range(7))
FINGER_DOF_INDICES = (7, 8)

# Absolute joint-position targets (radians for arm, meters for fingers).
ACTION_TYPE = "absolute_joint_position"
GRIPPER_OPEN = 0.04
GRIPPER_CLOSED = 0.0

# Soft joint limits used by the safety monitor (slightly inside manufacturer ranges).
ARM_POSITION_BOUNDS: tuple[tuple[float, float], ...] = (
    (-2.80, 2.80),
    (-1.70, 1.70),
    (-2.80, 2.80),
    (-3.00, 0.05),
    (-2.80, 2.80),
    (0.05, 3.70),
    (-2.80, 2.80),
)
FINGER_POSITION_BOUNDS: tuple[float, float] = (0.0, 0.04)

IMAGE_KEYS: tuple[str, ...] = (
    "observation.images.world",
    "observation.images.wrist",
)

# SmolVLA base was trained with canonical camera1/2 keys; map at train time.
SMOLVLA_RENAME_MAP: dict[str, str] = {
    "observation.images.world": "observation.images.camera1",
    "observation.images.wrist": "observation.images.camera2",
}

# The published SmolVLA base checkpoint describes a 6-D robot state.  This
# project uses the seven Panda arm joints plus both finger joints, so the
# checkpoint config must be overridden to 9-D when it is loaded for training.
# Keep the base model's canonical visual interface: the dataset rename map
# supplies camera1/camera2 and SmolVLA handles the absent camera3 as an empty
# view, matching the upstream pretraining layout.
SMOLVLA_INPUT_FEATURES: dict[str, dict[str, object]] = {
    "observation.state": {"type": "STATE", "shape": [STATE_DIM]},
    "observation.images.camera1": {"type": "VISUAL", "shape": [3, 256, 256]},
    "observation.images.camera2": {"type": "VISUAL", "shape": [3, 256, 256]},
    "observation.images.camera3": {"type": "VISUAL", "shape": [3, 256, 256]},
}

# YCB mesh directory names used by the scene builder.
FRUIT_YCB: dict[str, str] = {
    "banana": "011_banana",
    "lemon": "014_lemon",
    "plum": "018_plum",
    "apple": "013_apple",
    "orange": "017_orange",
}
BOWL_YCB = "024_bowl"
# Four placeable bowls: white+blue pair on the left, white+blue pair on the right.
# Entity names match "{side}_bowl" with side in CONTAINER_SIDES.
CONTAINER_TO_ENTITY: dict[str, str] = {
    "white_left_bowl": "white_left_bowl",
    "blue_left_bowl": "blue_left_bowl",
    "white_right_bowl": "white_right_bowl",
    "blue_right_bowl": "blue_right_bowl",
}
CONTAINER_SIDES: tuple[str, ...] = ("white_left", "blue_left", "white_right", "blue_right")
# Backward-compatible aliases used in older task strings / scripts.
CONTAINER_ALIASES: dict[str, str] = {
    "left_bowl": "white_left_bowl",
    "right_bowl": "white_right_bowl",
}


def vector_feature(names: tuple[str, ...] = JOINT_NAMES) -> dict[str, Any]:
    return {
        "dtype": "float32",
        "shape": (len(names),),
        "names": list(names),
    }


def image_feature(height: int, width: int) -> dict[str, Any]:
    return {
        "dtype": "video",
        "shape": (height, width, 3),
        "names": ["height", "width", "channel"],
    }


def dataset_features(height: int = 240, width: int = 320) -> dict[str, Any]:
    vec = vector_feature()
    img = image_feature(height, width)
    return {
        "observation.state": dict(vec),
        "action": dict(vec),
        "observation.images.world": dict(img),
        "observation.images.wrist": dict(img),
    }


def clamp_action(action) -> list[float]:
    """Clamp a 9-D absolute joint action into safe bounds."""
    import numpy as np

    a = np.asarray(action, dtype=np.float64).reshape(-1)
    if a.shape[0] != ACTION_DIM:
        raise ValueError(f"Expected action dim {ACTION_DIM}, got {a.shape[0]}")
    out = a.copy()
    for i, (lo, hi) in enumerate(ARM_POSITION_BOUNDS):
        out[i] = float(np.clip(out[i], lo, hi))
    flo, fhi = FINGER_POSITION_BOUNDS
    out[7] = float(np.clip(out[7], flo, fhi))
    out[8] = float(np.clip(out[8], flo, fhi))
    return out.tolist()
