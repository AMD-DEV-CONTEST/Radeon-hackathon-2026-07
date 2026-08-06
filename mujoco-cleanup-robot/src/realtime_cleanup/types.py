"""Typed messages crossing the sensor/model/actuator trust boundaries."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


ARM_ACTION_NAMES = (
    "lift",
    "arm",
    "wrist_yaw",
    "wrist_pitch",
    "wrist_roll",
    "gripper",
)
TIDYBOT_ARM_ACTION_NAMES = (
    "joint_1",
    "joint_2",
    "joint_3",
    "joint_4",
    "joint_5",
    "joint_6",
    "joint_7",
    "gripper",
)
TIDYBOT_BASE_ACTION_NAMES = ("x", "y", "theta")
TIDYBOT_BASE_TWIST_NAMES = ("vx_body", "vy_body", "wz")
TIDYBOT_TASK_PHASES = ("pick", "carry", "deposit")


@dataclass(frozen=True)
class SensorPacket:
    """Only observations that an eventual physical Stretch can provide."""

    frame_id: int
    monotonic_ns: int
    simulation_time: float
    nav_rgb: np.ndarray
    head_rgb: np.ndarray
    head_depth_m: np.ndarray
    wrist_rgb: np.ndarray
    wrist_depth_m: np.ndarray
    arm_position: np.ndarray
    arm_velocity: np.ndarray
    wheel_velocity: np.ndarray
    imu: np.ndarray
    head_fovy_degrees: float

    def __post_init__(self) -> None:
        if self.nav_rgb.ndim != 3 or self.nav_rgb.shape[2] != 3:
            raise ValueError("nav_rgb must be HxWx3")
        if self.head_rgb.ndim != 3 or self.head_rgb.shape[2] != 3:
            raise ValueError("head_rgb must be HxWx3")
        if self.wrist_rgb.ndim != 3 or self.wrist_rgb.shape[2] != 3:
            raise ValueError("wrist_rgb must be HxWx3")
        if self.head_depth_m.shape != self.head_rgb.shape[:2]:
            raise ValueError("head depth and RGB shapes must match")
        if self.wrist_depth_m.shape != self.wrist_rgb.shape[:2]:
            raise ValueError("wrist depth and RGB shapes must match")
        if self.arm_position.shape != (len(ARM_ACTION_NAMES),):
            raise ValueError("arm_position must contain six actuator positions")
        if self.arm_velocity.shape != (len(ARM_ACTION_NAMES),):
            raise ValueError("arm_velocity must contain six actuator velocities")
        if self.wheel_velocity.shape != (2,):
            raise ValueError("wheel_velocity must be two-dimensional")
        if self.imu.shape != (6,):
            raise ValueError("imu must contain 3-axis acceleration and gyro")


@dataclass(frozen=True)
class Detection:
    label: str
    source_label: str
    confidence: float
    bbox_xyxy: tuple[int, int, int, int]
    mask: np.ndarray
    center_camera_m: np.ndarray
    physical_size_m: tuple[float, float]
    unknown: bool
    trace_id: str


@dataclass(frozen=True)
class NavigationPlan:
    waypoints: np.ndarray
    temporal_distance: float
    goal_masked: bool
    trace_id: str

    def __post_init__(self) -> None:
        if self.waypoints.ndim != 2 or self.waypoints.shape[1] != 2:
            raise ValueError("waypoints must be Nx2")


@dataclass(frozen=True)
class ArmPolicyOutput:
    action_chunk: np.ndarray
    trace_id: str

    def __post_init__(self) -> None:
        if self.action_chunk.ndim != 2 or self.action_chunk.shape[1] != len(ARM_ACTION_NAMES):
            raise ValueError("action_chunk must be Nx6")


@dataclass(frozen=True)
class TidyBotSensorPacket:
    """Sensor-only boundary for the TidyBot plus rigid collection trailer.

    ``base_position`` is relative odometry ``[x, y, yaw]``. ``base_velocity``
    is always body-frame ``[vx, vy, wz]`` in both simulation and hardware.
    """

    frame_id: int
    monotonic_ns: int
    simulation_time: float
    nav_rgb: np.ndarray
    workspace_rgb: np.ndarray
    workspace_depth_m: np.ndarray
    wrist_rgb: np.ndarray
    wrist_depth_m: np.ndarray
    basket_rgb: np.ndarray
    arm_position: np.ndarray
    arm_velocity: np.ndarray
    base_position: np.ndarray
    base_velocity: np.ndarray
    workspace_fovy_degrees: float
    task_phase: str
    overview_rgb: np.ndarray | None = None
    workspace_camera_to_base: np.ndarray | None = None

    def __post_init__(self) -> None:
        for name in ("nav_rgb", "workspace_rgb", "wrist_rgb", "basket_rgb"):
            image = getattr(self, name)
            if image.ndim != 3 or image.shape[2] != 3:
                raise ValueError(f"{name} must be HxWx3")
        if self.overview_rgb is not None:
            if self.overview_rgb.ndim != 3 or self.overview_rgb.shape[2] != 3:
                raise ValueError("overview_rgb must be HxWx3 when provided")
        if self.workspace_depth_m.shape != self.workspace_rgb.shape[:2]:
            raise ValueError("workspace depth and RGB shapes must match")
        if self.wrist_depth_m.shape != self.wrist_rgb.shape[:2]:
            raise ValueError("wrist depth and RGB shapes must match")
        if self.arm_position.shape != (len(TIDYBOT_ARM_ACTION_NAMES),):
            raise ValueError("TidyBot arm position must be eight-dimensional")
        if self.arm_velocity.shape != (len(TIDYBOT_ARM_ACTION_NAMES),):
            raise ValueError("TidyBot arm velocity must be eight-dimensional")
        if self.base_position.shape != (len(TIDYBOT_BASE_ACTION_NAMES),):
            raise ValueError("TidyBot base position must be x/y/theta")
        if self.base_velocity.shape != (len(TIDYBOT_BASE_ACTION_NAMES),):
            raise ValueError("TidyBot base velocity must be x/y/theta")
        if self.task_phase not in TIDYBOT_TASK_PHASES:
            raise ValueError(f"invalid TidyBot task phase: {self.task_phase}")
        if self.workspace_camera_to_base is not None:
            if self.workspace_camera_to_base.shape != (4, 4):
                raise ValueError("workspace_camera_to_base must be a 4x4 transform")
            if not np.isfinite(self.workspace_camera_to_base).all():
                raise ValueError("workspace_camera_to_base must be finite")
            if not np.allclose(
                self.workspace_camera_to_base[3],
                (0.0, 0.0, 0.0, 1.0),
                atol=1e-6,
            ):
                raise ValueError("workspace_camera_to_base must be homogeneous")


@dataclass(frozen=True)
class TidyBotArmPolicyOutput:
    action_chunk: np.ndarray
    phase: str
    trace_id: str

    def __post_init__(self) -> None:
        if self.action_chunk.ndim != 2 or self.action_chunk.shape[1] != len(
            TIDYBOT_ARM_ACTION_NAMES
        ):
            raise ValueError("TidyBot action_chunk must be Nx8")
        if self.phase not in TIDYBOT_TASK_PHASES:
            raise ValueError(f"invalid TidyBot action phase: {self.phase}")


@dataclass(frozen=True)
class TidyBotBaseCommand:
    target_pose: np.ndarray
    trace_id: str

    def __post_init__(self) -> None:
        if self.target_pose.shape != (len(TIDYBOT_BASE_ACTION_NAMES),):
            raise ValueError("TidyBot target pose must be x/y/theta")
        if not np.isfinite(self.target_pose).all():
            raise ValueError("TidyBot target pose must be finite")


@dataclass(frozen=True)
class TidyBotBaseVelocityCommand:
    """Real-transferable holonomic command expressed in the base frame."""

    body_twist: np.ndarray
    trace_id: str

    def __post_init__(self) -> None:
        if self.body_twist.shape != (len(TIDYBOT_BASE_TWIST_NAMES),):
            raise ValueError("TidyBot body twist must be vx/vy/wz")
        if not np.isfinite(self.body_twist).all():
            raise ValueError("TidyBot body twist must be finite")
