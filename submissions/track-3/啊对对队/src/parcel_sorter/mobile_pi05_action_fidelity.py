"""Offline action-fidelity metrics for the 23-D absolute PI0.5 contract."""

from __future__ import annotations

import math
import statistics
from collections.abc import Iterable, Sequence


PI05_ABSOLUTE_ACTION_DIM = 23


def quaternion_geodesic_error_rad(
    predicted: Sequence[float], target: Sequence[float]
) -> float:
    """Return the sign-invariant angular distance between two quaternions."""

    if len(predicted) != 4 or len(target) != 4:
        raise ValueError("quaternions must contain four values")
    predicted_norm = math.sqrt(sum(float(value) ** 2 for value in predicted))
    target_norm = math.sqrt(sum(float(value) ** 2 for value in target))
    if predicted_norm <= 1e-12 or target_norm <= 1e-12:
        return math.pi
    dot = sum(
        float(left) * float(right)
        for left, right in zip(predicted, target, strict=True)
    ) / (predicted_norm * target_norm)
    return 2.0 * math.acos(min(1.0, max(-1.0, abs(dot))))


def absolute_action_fidelity(
    predicted: Sequence[float], target: Sequence[float]
) -> dict[str, float | bool]:
    """Compare one unnormalized PI0.5 action against its supervised label."""

    if len(predicted) != PI05_ABSOLUTE_ACTION_DIM:
        raise ValueError("predicted absolute action must have 23 values")
    if len(target) != PI05_ABSOLUTE_ACTION_DIM:
        raise ValueError("target absolute action must have 23 values")
    predicted_values = tuple(float(value) for value in predicted)
    target_values = tuple(float(value) for value in target)
    finite = all(math.isfinite(value) for value in predicted_values + target_values)
    if not finite:
        return {
            "finite": False,
            "base_velocity_l2": math.inf,
            "left_position_l2_m": math.inf,
            "right_position_l2_m": math.inf,
            "maximum_arm_position_l2_m": math.inf,
            "left_orientation_error_rad": math.pi,
            "right_orientation_error_rad": math.pi,
            "maximum_arm_orientation_error_rad": math.pi,
            "left_tool_correct": False,
            "right_tool_correct": False,
            "progress_absolute_error": math.inf,
        }

    base_error = _l2(predicted_values[0:3], target_values[0:3])
    left_position_error = _l2(predicted_values[3:6], target_values[3:6])
    right_position_error = _l2(predicted_values[11:14], target_values[11:14])
    left_orientation_error = quaternion_geodesic_error_rad(
        predicted_values[6:10], target_values[6:10]
    )
    right_orientation_error = quaternion_geodesic_error_rad(
        predicted_values[14:18], target_values[14:18]
    )
    return {
        "finite": True,
        "base_velocity_l2": base_error,
        "left_position_l2_m": left_position_error,
        "right_position_l2_m": right_position_error,
        "maximum_arm_position_l2_m": max(
            left_position_error, right_position_error
        ),
        "left_orientation_error_rad": left_orientation_error,
        "right_orientation_error_rad": right_orientation_error,
        "maximum_arm_orientation_error_rad": max(
            left_orientation_error, right_orientation_error
        ),
        "left_tool_correct": (predicted_values[10] >= 0.0)
        == (target_values[10] >= 0.0),
        "right_tool_correct": (predicted_values[18] >= 0.0)
        == (target_values[18] >= 0.0),
        "progress_absolute_error": abs(predicted_values[22] - target_values[22]),
    }


def aggregate_absolute_action_fidelity(
    samples: Iterable[dict[str, float | bool]],
) -> dict[str, float | bool | int]:
    """Aggregate repeated diffusion samples without treating them as replicates."""

    rows = list(samples)
    if not rows:
        raise ValueError("at least one action-fidelity sample is required")
    numeric_keys = (
        "base_velocity_l2",
        "left_position_l2_m",
        "right_position_l2_m",
        "maximum_arm_position_l2_m",
        "left_orientation_error_rad",
        "right_orientation_error_rad",
        "maximum_arm_orientation_error_rad",
        "progress_absolute_error",
    )
    result: dict[str, float | bool | int] = {
        "sample_count": len(rows),
        "finite": all(bool(row.get("finite")) for row in rows),
        "left_tool_accuracy": statistics.fmean(
            float(bool(row.get("left_tool_correct"))) for row in rows
        ),
        "right_tool_accuracy": statistics.fmean(
            float(bool(row.get("right_tool_correct"))) for row in rows
        ),
    }
    for key in numeric_keys:
        values = [float(row[key]) for row in rows]
        result[f"median_{key}"] = statistics.median(values)
        result[f"maximum_{key}"] = max(values)
    return result


def action_fidelity_gate(
    metrics: dict[str, object],
    *,
    median_position_m: float = 0.06,
    maximum_position_m: float = 0.12,
    median_orientation_rad: float = 0.60,
    maximum_orientation_rad: float = 1.00,
    median_base_velocity: float = 0.08,
    maximum_base_velocity: float = 0.12,
    median_progress_error: float = 0.35,
    minimum_tool_accuracy: float = 2.0 / 3.0,
) -> dict[str, bool]:
    """Evaluate the preregistered development action-fidelity thresholds."""

    return {
        "finite": metrics.get("finite") is True,
        "median_arm_position": float(
            metrics.get("median_maximum_arm_position_l2_m", math.inf)
        )
        <= median_position_m,
        "maximum_arm_position": float(
            metrics.get("maximum_maximum_arm_position_l2_m", math.inf)
        )
        <= maximum_position_m,
        "median_arm_orientation": float(
            metrics.get("median_maximum_arm_orientation_error_rad", math.inf)
        )
        <= median_orientation_rad,
        "maximum_arm_orientation": float(
            metrics.get("maximum_maximum_arm_orientation_error_rad", math.inf)
        )
        <= maximum_orientation_rad,
        "median_base_velocity": float(
            metrics.get("median_base_velocity_l2", math.inf)
        )
        <= median_base_velocity,
        "maximum_base_velocity": float(
            metrics.get("maximum_base_velocity_l2", math.inf)
        )
        <= maximum_base_velocity,
        "median_progress": float(
            metrics.get("median_progress_absolute_error", math.inf)
        )
        <= median_progress_error,
        "left_tool": float(metrics.get("left_tool_accuracy", 0.0))
        >= minimum_tool_accuracy,
        "right_tool": float(metrics.get("right_tool_accuracy", 0.0))
        >= minimum_tool_accuracy,
    }


def _l2(left: Sequence[float], right: Sequence[float]) -> float:
    return math.sqrt(
        sum(
            (float(first) - float(second)) ** 2
            for first, second in zip(left, right, strict=True)
        )
    )
