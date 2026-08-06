"""Mapping between lerobot normalized joint values and SO101 URDF radians.

Why this exists:
  lerobot's FeetechMotorsBus with `normalize=True` returns a device-
  independent value in [-100, +100] (or [0, 100] for one-sided motors
  like the gripper). Calibration handles the per-motor tick↔normalized
  map, so normalized values are directly comparable between leader and
  follower arms — this is the whole point of using lerobot calibration
  instead of our old custom JSON format.

  But the rest of BotverseX (JointUpdate schema, UrdfViewer, dataset
  recording) speaks **radians**, tied to the SO101 URDF joint limits.
  So we do one affine conversion at the leader (normalized → rad on
  send) and the inverse at the follower (rad → normalized on write).
  Both arms use the same limits, so the "coordinate system" they speak
  on the wire is unambiguous: 0 rad means the joint is at its URDF
  center, independent of each physical motor's homing offset.

Limits are lifted from `apps/realtime/dora-bambot/URDF/so101.urdf`.
If the URDF changes, keep this table in sync or the viewer will drift.
"""
from __future__ import annotations

from typing import Dict

# Motor name → (lower_rad, upper_rad) from URDF <limit> tags.
# Sign convention matches URDF; for M100..M100 motors we linearly map
# [-100, 0, +100] → [lower, center=(lower+upper)/2, upper].
# For the gripper (RANGE_0_100) we map [0, 100] → [lower, upper].
JOINT_LIMITS_RAD: Dict[str, tuple[float, float]] = {
    "shoulder_pan":  (-1.91986,  1.91986),
    "shoulder_lift": (-1.74533,  1.74533),
    "elbow_flex":    (-1.74533,  1.57080),
    "wrist_flex":    (-1.65806,  1.65806),
    "wrist_roll":    (-2.74385,  2.84121),
    "gripper":       (-0.17453,  1.74533),
}


# Motor name → motor id (1..6), matches SO101 wiring everywhere.
MOTOR_NAME_TO_ID: Dict[str, int] = {
    "shoulder_pan":  1,
    "shoulder_lift": 2,
    "elbow_flex":    3,
    "wrist_flex":    4,
    "wrist_roll":    5,
    "gripper":       6,
}
MOTOR_ID_TO_NAME: Dict[int, str] = {v: k for k, v in MOTOR_NAME_TO_ID.items()}


# Motors that use RANGE_0_100 norm mode (only gripper on SO101).
ONE_SIDED_MOTORS: set[str] = {"gripper"}


def normalized_to_rad(motor_name: str, normalized: float) -> float:
    """Convert a lerobot-normalized value to radians via URDF limits.

    RANGE_M100_100 motors: linear map [-100, +100] → [lower, upper].
    RANGE_0_100 motors:    linear map [0, +100]   → [lower, upper].
    """
    lo, hi = JOINT_LIMITS_RAD[motor_name]
    if motor_name in ONE_SIDED_MOTORS:
        ratio = float(normalized) / 100.0
    else:
        ratio = (float(normalized) + 100.0) / 200.0
    return lo + ratio * (hi - lo)


def rad_to_normalized(motor_name: str, rad: float) -> float:
    """Inverse of `normalized_to_rad`."""
    lo, hi = JOINT_LIMITS_RAD[motor_name]
    span = hi - lo
    if span == 0:
        return 0.0
    ratio = (float(rad) - lo) / span
    if motor_name in ONE_SIDED_MOTORS:
        return ratio * 100.0
    return ratio * 200.0 - 100.0


__all__ = [
    "JOINT_LIMITS_RAD",
    "MOTOR_NAME_TO_ID",
    "MOTOR_ID_TO_NAME",
    "ONE_SIDED_MOTORS",
    "normalized_to_rad",
    "rad_to_normalized",
]
