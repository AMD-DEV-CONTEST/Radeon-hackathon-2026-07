"""Deterministic resampling of dense 250 Hz TOPP traces to Mantis 30 Hz commands."""

from __future__ import annotations

import bisect
import math
from collections.abc import Sequence
from typing import Any

from .contracts import ContractError


def _finite_vector(values: Sequence[float], context: str) -> list[float]:
    result = [float(value) for value in values]
    if not result or not all(math.isfinite(value) for value in result):
        raise ContractError(f"{context} must contain finite values")
    return result


def _interpolate(
    timestamps: list[float], positions: list[list[float]], query_time: float
) -> list[float]:
    if query_time <= timestamps[0]:
        return positions[0][:]
    if query_time >= timestamps[-1]:
        return positions[-1][:]
    right = bisect.bisect_right(timestamps, query_time)
    left = right - 1
    interval = timestamps[right] - timestamps[left]
    fraction = (query_time - timestamps[left]) / interval
    return [
        start + fraction * (end - start)
        for start, end in zip(positions[left], positions[right])
    ]


def resample_topp_trace(
    timestamps_s: Sequence[float],
    positions: Sequence[Sequence[float]],
    *,
    target_hz: float,
    velocity_limits_per_s: Sequence[float],
) -> dict[str, Any]:
    """Uniformly retime and linearly sample one combined dense dual-arm trace.

    ``positions`` must already use the target semantic joint order.  Retiming is
    uniform across all joints, so the combined trace's left/right coordination and
    geometric path are preserved.  The last output command is always the exact
    source endpoint and is issued on a fixed target-clock tick.
    """

    timestamps = _finite_vector(timestamps_s, "timestamps_s")
    if len(timestamps) < 2:
        raise ContractError("a dense trace requires at least two timestamps")
    if abs(timestamps[0]) > 1e-9:
        raise ContractError("dense trace timestamps must start at zero")
    if any(right <= left for left, right in zip(timestamps, timestamps[1:])):
        raise ContractError("dense trace timestamps must be strictly increasing")
    if len(positions) != len(timestamps):
        raise ContractError("positions and timestamps must have equal length")

    rows = [_finite_vector(row, f"positions[{index}]") for index, row in enumerate(positions)]
    dimension = len(rows[0])
    if any(len(row) != dimension for row in rows):
        raise ContractError("all position rows must have the same dimension")
    limits = _finite_vector(velocity_limits_per_s, "velocity_limits_per_s")
    if len(limits) != dimension or any(limit <= 0 for limit in limits):
        raise ContractError("velocity limits must be positive and match the position dimension")
    target_rate = float(target_hz)
    if not math.isfinite(target_rate) or target_rate <= 0:
        raise ContractError("target_hz must be finite and positive")

    peak_source_velocity = [0.0] * dimension
    for left_time, right_time, left_row, right_row in zip(
        timestamps, timestamps[1:], rows, rows[1:]
    ):
        interval = right_time - left_time
        for index, (start, end) in enumerate(zip(left_row, right_row)):
            peak_source_velocity[index] = max(
                peak_source_velocity[index], abs(end - start) / interval
            )
    time_scale = max(
        1.0,
        max(
            velocity / limit
            for velocity, limit in zip(peak_source_velocity, limits)
        ),
    )
    source_duration = timestamps[-1]
    retimed_duration = source_duration * time_scale
    final_tick = max(1, int(math.ceil(retimed_duration * target_rate - 1e-12)))
    command_times = [tick / target_rate for tick in range(final_tick + 1)]
    sampled = [
        _interpolate(timestamps, rows, min(command_time / time_scale, source_duration))
        for command_time in command_times
    ]
    sampled[-1] = rows[-1][:]

    output_velocities = [[0.0] * dimension]
    for previous, current in zip(sampled, sampled[1:]):
        output_velocities.append(
            [(end - start) * target_rate for start, end in zip(previous, current)]
        )
    tolerance = 1e-9
    for row in output_velocities[1:]:
        if any(abs(value) > limit + tolerance for value, limit in zip(row, limits)):
            raise ContractError("resampled trajectory exceeds a target velocity limit")

    endpoint_lag = command_times[-1] - retimed_duration
    if endpoint_lag < -tolerance or endpoint_lag >= 1.0 / target_rate + tolerance:
        raise ContractError("endpoint hold lag is outside one target control interval")
    return {
        "schema_version": 1,
        "protocol_version": "topp_dense_to_mantis_30hz_v1",
        "source_duration_s": source_duration,
        "retimed_duration_s": retimed_duration,
        "target_hz": target_rate,
        "time_scale_factor": time_scale,
        "endpoint_hold_lag_s": max(0.0, endpoint_lag),
        "peak_source_velocity_per_s": peak_source_velocity,
        "timestamps_s": command_times,
        "positions": sampled,
        "velocities_per_s": output_velocities,
    }
