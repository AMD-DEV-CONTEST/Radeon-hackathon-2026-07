"""Pure evaluators for the RoboTwin ``stack_bowls_three`` port.

The legacy evaluator intentionally preserves the source task's one-sided
height comparison.  It is useful only for source compatibility.  The strict
evaluator is the competition protocol and adds absolute height, motion, and
consecutive-frame requirements.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence


Vector3 = Sequence[float]


def _vectors3(values: Sequence[Vector3], name: str) -> list[tuple[float, float, float]]:
    if len(values) != 3:
        raise ValueError(f"{name} must contain exactly three vectors")
    result: list[tuple[float, float, float]] = []
    for index, value in enumerate(values):
        if len(value) != 3:
            raise ValueError(f"{name}[{index}] must have length 3")
        vector = tuple(float(component) for component in value)
        if not all(math.isfinite(component) for component in vector):
            raise ValueError(f"{name}[{index}] contains a non-finite value")
        result.append(vector)
    return result


def _sorted_by_height(positions: Sequence[Vector3]) -> list[tuple[float, float, float]]:
    return sorted(_vectors3(positions, "positions"), key=lambda position: position[2])


def _axiswise_xy_aligned(
    lower: tuple[float, float, float],
    upper: tuple[float, float, float],
    tolerance_m: float,
) -> bool:
    return abs(lower[0] - upper[0]) < tolerance_m and abs(lower[1] - upper[1]) < tolerance_m


def evaluate_legacy_source(
    positions: Sequence[Vector3],
    *,
    left_gripper_open: bool,
    right_gripper_open: bool,
    table_z_bias: float = 0.0,
) -> dict[str, object]:
    """Reproduce RoboTwin's legacy success and graded-score semantics exactly.

    The source uses ``actual_z - target_z < 0.02`` rather than an absolute
    error.  Consequently, an implausibly low but XY-aligned stack can pass.
    That behavior is deliberate here and covered by a regression test.
    """

    ordered = _sorted_by_height(positions)
    xy_tolerance_m = 0.04
    height_tolerance_m = 0.02
    target_heights = (0.74 + table_z_bias, 0.77 + table_z_bias, 0.81 + table_z_bias)

    lower_middle_xy = _axiswise_xy_aligned(ordered[0], ordered[1], xy_tolerance_m)
    middle_upper_xy = _axiswise_xy_aligned(ordered[1], ordered[2], xy_tolerance_m)
    one_sided_heights = all(
        position[2] - target_height < height_tolerance_m
        for position, target_height in zip(ordered, target_heights)
    )
    success = (
        lower_middle_xy
        and middle_upper_xy
        and one_sided_heights
        and bool(left_gripper_open)
        and bool(right_gripper_open)
    )

    base_height = 0.74 + table_z_bias
    stack_count = 0
    if lower_middle_xy and ordered[1][2] > base_height + 0.015:
        stack_count = 1
        if middle_upper_xy and ordered[2][2] > base_height + 0.045:
            stack_count = 2

    return {
        "protocol_version": "legacy_source_v1",
        "success": success,
        "graded_score": stack_count / 2.0,
        "stack_count": stack_count,
        "ordered_positions": ordered,
        "checks": {
            "lower_middle_xy": lower_middle_xy,
            "middle_upper_xy": middle_upper_xy,
            "one_sided_heights": one_sided_heights,
            "left_gripper_open": bool(left_gripper_open),
            "right_gripper_open": bool(right_gripper_open),
        },
    }


def evaluate_strict_target_frame(
    positions: Sequence[Vector3],
    linear_velocities: Sequence[Vector3],
    angular_velocities: Sequence[Vector3],
    *,
    left_gripper_open_fraction: float,
    right_gripper_open_fraction: float,
    table_z_bias: float = 0.0,
    xy_axis_tolerance_m: float = 0.04,
    height_absolute_tolerance_m: float = 0.02,
    maximum_linear_speed_m_s: float = 0.02,
    maximum_angular_speed_rad_s: float = 0.15,
    minimum_gripper_open_fraction: float = 0.9,
    no_safety_failure: bool = True,
    no_physics_divergence: bool = True,
) -> dict[str, object]:
    """Evaluate one frame of the stricter Mantis competition protocol."""

    numeric_limits = (
        xy_axis_tolerance_m,
        height_absolute_tolerance_m,
        maximum_linear_speed_m_s,
        maximum_angular_speed_rad_s,
        minimum_gripper_open_fraction,
    )
    if not all(math.isfinite(value) and value >= 0 for value in numeric_limits):
        raise ValueError("strict evaluator tolerances must be finite and non-negative")
    gripper_fractions = (float(left_gripper_open_fraction), float(right_gripper_open_fraction))
    if not all(math.isfinite(value) for value in gripper_fractions):
        raise ValueError("gripper open fractions must be finite")

    indexed_positions = list(enumerate(_vectors3(positions, "positions")))
    linear = _vectors3(linear_velocities, "linear_velocities")
    angular = _vectors3(angular_velocities, "angular_velocities")
    ordered = sorted(indexed_positions, key=lambda item: item[1][2])
    ordered_positions = [position for _, position in ordered]
    ordered_linear = [linear[index] for index, _ in ordered]
    ordered_angular = [angular[index] for index, _ in ordered]

    target_heights = (0.74 + table_z_bias, 0.77 + table_z_bias, 0.81 + table_z_bias)
    lower_middle_xy = _axiswise_xy_aligned(
        ordered_positions[0], ordered_positions[1], xy_axis_tolerance_m
    )
    middle_upper_xy = _axiswise_xy_aligned(
        ordered_positions[1], ordered_positions[2], xy_axis_tolerance_m
    )
    absolute_heights = all(
        abs(position[2] - target_height) < height_absolute_tolerance_m
        for position, target_height in zip(ordered_positions, target_heights)
    )
    motion_stable = all(
        math.sqrt(sum(component * component for component in velocity))
        < maximum_linear_speed_m_s
        for velocity in ordered_linear
    ) and all(
        math.sqrt(sum(component * component for component in velocity))
        < maximum_angular_speed_rad_s
        for velocity in ordered_angular
    )
    grippers_open = all(value >= minimum_gripper_open_fraction for value in gripper_fractions)
    frame_success = (
        lower_middle_xy
        and middle_upper_xy
        and absolute_heights
        and motion_stable
        and grippers_open
        and bool(no_safety_failure)
        and bool(no_physics_divergence)
    )
    return {
        "protocol_version": "competition_strict_v1",
        "frame_success": frame_success,
        "ordered_positions": ordered_positions,
        "checks": {
            "lower_middle_xy": lower_middle_xy,
            "middle_upper_xy": middle_upper_xy,
            "absolute_heights": absolute_heights,
            "motion_stable": motion_stable,
            "grippers_open": grippers_open,
            "no_safety_failure": bool(no_safety_failure),
            "no_physics_divergence": bool(no_physics_divergence),
        },
    }


@dataclass
class StackStabilityTracker:
    """Require a strict frame predicate for consecutive policy frames."""

    required_frames: int
    consecutive_frames: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.required_frames, int) or self.required_frames <= 0:
            raise ValueError("required_frames must be a positive integer")

    def update(self, frame_success: bool) -> bool:
        self.consecutive_frames = self.consecutive_frames + 1 if frame_success else 0
        return self.consecutive_frames >= self.required_frames

    def reset(self) -> None:
        self.consecutive_frames = 0
