from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Observation:
    """Minimal signals used by the closed-loop task supervisor."""

    parcel_visible: bool = False
    at_pregrasp: bool = False
    grasp_contact: bool = False
    parcel_lifted: bool = False
    at_drop_pose: bool = False
    parcel_in_bin: bool = False
    parcel_released: bool = False
    transport_slip: bool = False
    at_recovery_setdown: bool = False
    excessive_contact_force: bool = False
    fault: bool = False


@dataclass(frozen=True)
class ControlDecision:
    stage: str
    command: str
    reason: str
    retry_count: int


@dataclass(frozen=True)
class RobotState:
    """Numeric state used by the scripted expert and dataset writer."""

    joint_positions: tuple[float, ...]
    end_effector_pose: tuple[float, ...]
    parcel_pose: tuple[float, ...]
    target_position: tuple[float, float, float]
    gripper_contact_force_n: float

    def policy_vector(self) -> tuple[float, ...]:
        return (
            *self.joint_positions,
            *self.end_effector_pose,
            *self.target_position,
            self.gripper_contact_force_n,
        )

    def privileged_vector(self) -> tuple[float, ...]:
        return self.parcel_pose

    def vector(self) -> tuple[float, ...]:
        return (*self.policy_vector(), *self.privileged_vector())


@dataclass(frozen=True)
class CartesianAction:
    """Safe high-level action consumed by IK and the gripper controller."""

    target_position: tuple[float, float, float]
    target_quaternion: tuple[float, float, float, float]
    gripper: float
    command: str

    def vector(self) -> tuple[float, ...]:
        return (*self.target_position, *self.target_quaternion, self.gripper)


@dataclass(frozen=True)
class TrajectoryFrame:
    frame_index: int
    timestamp_seconds: float
    stage: str
    state: RobotState
    action: CartesianAction
    task: str
    rgb: Any | None = None
    depth: Any | None = None


@dataclass(frozen=True)
class PolicyContext:
    decision: ControlDecision
    state: RobotState
    task: str
    rgb: Any | None = None
    depth: Any | None = None
