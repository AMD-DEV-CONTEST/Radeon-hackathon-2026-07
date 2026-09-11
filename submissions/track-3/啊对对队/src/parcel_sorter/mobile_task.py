"""Task and learned-action contracts for mobile bimanual parcel sorting."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
from typing import Iterable


MOBILE_BIMANUAL_ACTION_DIM = 19


class MobileTaskStage(str, Enum):
    NAVIGATE_PICKUP = "navigate_pickup"
    PREGRASP = "pregrasp"
    GRASP = "grasp"
    LIFT = "lift"
    TRANSPORT = "transport"
    PLACE = "place"
    RELEASE = "release"
    RETREAT = "retreat"
    COMPLETE = "complete"
    ABORT = "abort"


@dataclass(frozen=True)
class ArmCartesianCommand:
    position_m: tuple[float, float, float]
    quaternion_wxyz: tuple[float, float, float, float]
    gripper: float


@dataclass(frozen=True)
class MobileBimanualAction:
    base_velocity_xy_yaw: tuple[float, float, float]
    left: ArmCartesianCommand
    right: ArmCartesianCommand


@dataclass(frozen=True)
class MobileTaskObservation:
    base_at_pickup: bool = False
    arms_at_pregrasp: bool = False
    left_grasp_contact: bool = False
    right_grasp_contact: bool = False
    parcel_lifted: bool = False
    base_at_destination: bool = False
    parcel_placed: bool = False
    grippers_open: bool = False
    arms_retreated: bool = False
    parcel_dropped: bool = False
    excessive_contact_force: bool = False
    stage_timed_out: bool = False


@dataclass(frozen=True)
class MobileTaskDecision:
    stage: str
    base_command: str
    arm_command: str
    reason: str
    retry_count: int


class MobileBimanualTaskSupervisor:
    """Fail-closed task state machine shared by expert and VLA execution."""

    def __init__(self, *, max_retries: int = 2) -> None:
        if max_retries < 0:
            raise ValueError("max_retries cannot be negative")
        self.max_retries = max_retries
        self.retry_count = 0
        self.stage = MobileTaskStage.NAVIGATE_PICKUP

    def step(self, observation: MobileTaskObservation) -> MobileTaskDecision:
        if self.stage in {MobileTaskStage.COMPLETE, MobileTaskStage.ABORT}:
            return self._decision("hold", "hold", "terminal state")
        if observation.excessive_contact_force:
            self.stage = MobileTaskStage.ABORT
            return self._decision("stop", "open_and_hold", "contact force gate")
        if observation.parcel_dropped or observation.stage_timed_out:
            if self.retry_count >= self.max_retries:
                self.stage = MobileTaskStage.ABORT
                return self._decision("stop", "open_and_hold", "retry budget exhausted")
            self.retry_count += 1
            self.stage = MobileTaskStage.NAVIGATE_PICKUP
            return self._decision("return_to_pickup", "open_and_home", "bounded recovery")

        if self.stage == MobileTaskStage.NAVIGATE_PICKUP:
            if observation.base_at_pickup:
                self.stage = MobileTaskStage.PREGRASP
                return self._decision("hold", "move_pregrasp", "pickup pose reached")
            return self._decision("navigate_pickup", "home", "approaching pickup")
        if self.stage == MobileTaskStage.PREGRASP:
            if observation.arms_at_pregrasp:
                self.stage = MobileTaskStage.GRASP
                return self._decision("hold", "close", "dual pregrasp reached")
            return self._decision("hold", "move_pregrasp", "synchronizing arms")
        if self.stage == MobileTaskStage.GRASP:
            if observation.left_grasp_contact and observation.right_grasp_contact:
                self.stage = MobileTaskStage.LIFT
                return self._decision("hold", "lift", "bilateral contact verified")
            return self._decision("hold", "close", "waiting for bilateral contact")
        if self.stage == MobileTaskStage.LIFT:
            if observation.parcel_lifted:
                self.stage = MobileTaskStage.TRANSPORT
                return self._decision("navigate_destination", "carry", "lift verified")
            return self._decision("hold", "lift", "lifting parcel")
        if self.stage == MobileTaskStage.TRANSPORT:
            if observation.base_at_destination:
                self.stage = MobileTaskStage.PLACE
                return self._decision("hold", "place", "destination reached")
            return self._decision("navigate_destination", "carry", "transporting parcel")
        if self.stage == MobileTaskStage.PLACE:
            if observation.parcel_placed:
                self.stage = MobileTaskStage.RELEASE
                return self._decision("hold", "open", "placement verified")
            return self._decision("hold", "place", "lowering parcel")
        if self.stage == MobileTaskStage.RELEASE:
            if observation.grippers_open:
                self.stage = MobileTaskStage.RETREAT
                return self._decision("hold", "retreat", "parcel released")
            return self._decision("hold", "open", "opening grippers")
        if self.stage == MobileTaskStage.RETREAT:
            if observation.arms_retreated:
                self.stage = MobileTaskStage.COMPLETE
                return self._decision("hold", "hold", "task complete")
            return self._decision("hold", "retreat", "clearing parcel")
        raise RuntimeError(f"unhandled mobile task stage: {self.stage}")

    def _decision(self, base: str, arm: str, reason: str) -> MobileTaskDecision:
        return MobileTaskDecision(self.stage.value, base, arm, reason, self.retry_count)


def decode_mobile_bimanual_action(
    values: Iterable[float],
    *,
    max_base_linear_speed_m_s: float = 0.35,
    max_base_yaw_rate_rad_s: float = 1.0,
) -> MobileBimanualAction:
    """Decode the 19-D VLA action and enforce finite, normalized commands."""

    raw = tuple(float(value) for value in values)
    if len(raw) != MOBILE_BIMANUAL_ACTION_DIM:
        raise ValueError(f"mobile bimanual action must have {MOBILE_BIMANUAL_ACTION_DIM} values")
    if any(not math.isfinite(value) for value in raw):
        raise ValueError("mobile bimanual action contains non-finite values")
    if min(max_base_linear_speed_m_s, max_base_yaw_rate_rad_s) <= 0:
        raise ValueError("base velocity limits must be positive")
    vx, vy, yaw_rate = raw[:3]
    linear_norm = math.hypot(vx, vy)
    if linear_norm > max_base_linear_speed_m_s:
        scale = max_base_linear_speed_m_s / linear_norm
        vx *= scale
        vy *= scale
    base = (vx, vy, max(-max_base_yaw_rate_rad_s, min(max_base_yaw_rate_rad_s, yaw_rate)))
    return MobileBimanualAction(
        base_velocity_xy_yaw=base,
        left=_decode_arm(raw[3:11]),
        right=_decode_arm(raw[11:19]),
    )


def limit_mobile_arm_step(
    command: ArmCartesianCommand,
    current_position_m: tuple[float, float, float],
    *,
    max_step_m: float = 0.04,
) -> ArmCartesianCommand:
    """Apply the same Cartesian safety bound used by the single-arm policy."""

    if max_step_m <= 0 or not math.isfinite(max_step_m):
        raise ValueError("max_step_m must be finite and positive")
    delta = tuple(target - current for target, current in zip(command.position_m, current_position_m))
    distance = math.sqrt(sum(value * value for value in delta))
    if distance <= max_step_m:
        return command
    scale = max_step_m / distance
    bounded = tuple(current + scale * value for current, value in zip(current_position_m, delta))
    return ArmCartesianCommand(bounded, command.quaternion_wxyz, command.gripper)


def clamp_position_residual_to_anchor(
    target_position_m: Iterable[float],
    anchor_position_m: Iterable[float],
    *,
    max_residual_m: float = 0.01,
) -> tuple[float, float, float]:
    """Bound cumulative learned arm drift around a frozen expert anchor."""

    target = tuple(float(value) for value in target_position_m)
    anchor = tuple(float(value) for value in anchor_position_m)
    if len(target) != 3 or len(anchor) != 3:
        raise ValueError("arm target and anchor must be 3-D")
    if any(not math.isfinite(value) for value in (*target, *anchor)):
        raise ValueError("arm target and anchor must be finite")
    if not math.isfinite(max_residual_m) or max_residual_m <= 0.0:
        raise ValueError("max_residual_m must be finite and positive")
    delta = tuple(value - origin for value, origin in zip(target, anchor, strict=True))
    norm = math.sqrt(sum(value * value for value in delta))
    if norm <= max_residual_m:
        return target  # type: ignore[return-value]
    scale = max_residual_m / norm
    return tuple(
        origin + scale * value
        for origin, value in zip(anchor, delta, strict=True)
    )  # type: ignore[return-value]


def placement_within_release_gate(
    parcel_position_m: Iterable[float],
    expected_position_m: Iterable[float],
    *,
    max_xy_error_m: float = 0.040,
    max_z_error_m: float = 0.025,
) -> bool:
    """Return whether a parcel is inside the audited pre-release position gate."""

    parcel = tuple(float(value) for value in parcel_position_m)
    expected = tuple(float(value) for value in expected_position_m)
    if len(parcel) != 3 or len(expected) != 3:
        raise ValueError("parcel and expected positions must be 3-D")
    if any(not math.isfinite(value) for value in (*parcel, *expected)):
        raise ValueError("parcel and expected positions must be finite")
    if min(max_xy_error_m, max_z_error_m) <= 0.0 or not all(
        math.isfinite(value) for value in (max_xy_error_m, max_z_error_m)
    ):
        raise ValueError("placement tolerances must be finite and positive")
    return bool(
        math.hypot(parcel[0] - expected[0], parcel[1] - expected[1])
        <= max_xy_error_m
        and abs(parcel[2] - expected[2]) <= max_z_error_m
    )


def update_release_gate_stability(
    *,
    attached: bool,
    inside_release_gate: bool,
    consecutive_steps: int,
    required_steps: int = 24,
) -> tuple[int, bool]:
    """Require a stable in-gate landing before any grasp mode releases."""

    if consecutive_steps < 0:
        raise ValueError("consecutive_steps cannot be negative")
    if required_steps <= 0:
        raise ValueError("required_steps must be positive")
    updated = consecutive_steps + 1 if attached and inside_release_gate else 0
    return updated, updated >= required_steps


def _decode_arm(values: tuple[float, ...]) -> ArmCartesianCommand:
    quat = values[3:7]
    norm = math.sqrt(sum(value * value for value in quat))
    if norm <= 1e-8:
        raise ValueError("arm quaternion norm is zero")
    normalized = tuple(value / norm for value in quat)
    return ArmCartesianCommand(values[:3], normalized, 1.0 if values[7] >= 0 else -1.0)
