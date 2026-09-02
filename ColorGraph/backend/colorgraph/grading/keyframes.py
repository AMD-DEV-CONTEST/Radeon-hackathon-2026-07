from __future__ import annotations

from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache

import torch

from colorgraph.domain.grade_graph import Interpolation, ParameterTrack


@dataclass(frozen=True, slots=True)
class _CubicInterval:
    start_time: float
    end_time: float
    constant: float
    linear: float
    quadratic: float
    cubic: float

    def evaluate(self, time_seconds: float) -> float:
        elapsed = time_seconds - self.start_time
        return (
            (self.cubic * elapsed + self.quadratic) * elapsed + self.linear
        ) * elapsed + self.constant


@dataclass(frozen=True, slots=True)
class _PchipCurve:
    times: tuple[float, ...]
    intervals: tuple[_CubicInterval, ...]

    def evaluate(self, time_seconds: float) -> float:
        interval_index = min(
            bisect_right(self.times, time_seconds) - 1,
            len(self.intervals) - 1,
        )
        return self.intervals[max(0, interval_index)].evaluate(time_seconds)


def _endpoint_slope(
    first_span: float,
    second_span: float,
    first_secant: float,
    second_secant: float,
) -> float:
    slope = ((2.0 * first_span + second_span) * first_secant - first_span * second_secant) / (
        first_span + second_span
    )
    if slope * first_secant <= 0.0:
        return 0.0
    if first_secant * second_secant < 0.0 and abs(slope) > 3.0 * abs(first_secant):
        return 3.0 * first_secant
    return slope


@lru_cache(maxsize=4096)
def _compile_pchip(
    points: tuple[tuple[float, float], ...],
) -> _PchipCurve:
    """Precompute Fritsch-Butland PCHIP coefficients for binary-search lookup."""
    if len(points) < 2:
        raise ValueError("PCHIP requires at least two keyframes")

    times = tuple(point[0] for point in points)
    values = tuple(point[1] for point in points)
    spans = tuple(right - left for left, right in zip(times, times[1:], strict=False))
    if any(span <= 0.0 for span in spans):
        raise ValueError("PCHIP keyframe times must be strictly increasing")
    secants = tuple(
        (right - left) / span for left, right, span in zip(values, values[1:], spans, strict=False)
    )

    if len(points) == 2:
        slopes = (secants[0], secants[0])
    else:
        mutable_slopes = [0.0] * len(points)
        mutable_slopes[0] = _endpoint_slope(
            spans[0],
            spans[1],
            secants[0],
            secants[1],
        )
        mutable_slopes[-1] = _endpoint_slope(
            spans[-1],
            spans[-2],
            secants[-1],
            secants[-2],
        )
        for index in range(1, len(points) - 1):
            previous_secant = secants[index - 1]
            following_secant = secants[index]
            if (
                previous_secant == 0.0
                or following_secant == 0.0
                or previous_secant * following_secant <= 0.0
            ):
                mutable_slopes[index] = 0.0
                continue
            previous_span = spans[index - 1]
            following_span = spans[index]
            first_weight = 2.0 * following_span + previous_span
            second_weight = following_span + 2.0 * previous_span
            mutable_slopes[index] = (first_weight + second_weight) / (
                first_weight / previous_secant + second_weight / following_secant
            )
        slopes = tuple(mutable_slopes)

    intervals: list[_CubicInterval] = []
    for index, (start_time, end_time) in enumerate(zip(times, times[1:], strict=False)):
        span = spans[index]
        secant = secants[index]
        left_slope = slopes[index]
        right_slope = slopes[index + 1]
        intervals.append(
            _CubicInterval(
                start_time=start_time,
                end_time=end_time,
                constant=values[index],
                linear=left_slope,
                quadratic=(3.0 * secant - 2.0 * left_slope - right_slope) / span,
                cubic=(left_slope + right_slope - 2.0 * secant) / (span * span),
            )
        )
    return _PchipCurve(times=times, intervals=tuple(intervals))


def _catmull_rom_value(
    track: ParameterTrack,
    left_index: int,
    right_index: int,
    position: float,
) -> float:
    """Evaluate the legacy uniform Catmull-Rom mode for saved projects."""
    keyframes = track.keyframes
    left = keyframes[left_index]
    right = keyframes[right_index]
    previous = keyframes[max(0, left_index - 1)].value
    following = keyframes[min(len(keyframes) - 1, right_index + 1)].value
    position_squared = position * position
    position_cubed = position_squared * position
    return 0.5 * (
        2 * left.value
        + (-previous + right.value) * position
        + (2 * previous - 5 * left.value + 4 * right.value - following) * position_squared
        + (-previous + 3 * left.value - 3 * right.value + following) * position_cubed
    )


def evaluate_track(track: ParameterTrack, time_seconds: float) -> float:
    keyframes = track.keyframes
    if time_seconds <= keyframes[0].time_seconds:
        return keyframes[0].value
    if time_seconds >= keyframes[-1].time_seconds:
        return keyframes[-1].value

    times = tuple(keyframe.time_seconds for keyframe in keyframes)
    left_index = bisect_right(times, time_seconds) - 1
    right_index = left_index + 1
    left = keyframes[left_index]
    right = keyframes[right_index]
    span = right.time_seconds - left.time_seconds
    position = (time_seconds - left.time_seconds) / span

    if track.interpolation == Interpolation.HOLD:
        value = left.value
    elif track.interpolation == Interpolation.LINEAR:
        value = left.value + (right.value - left.value) * position
    elif track.interpolation == Interpolation.PCHIP:
        value = _compile_pchip(
            tuple((keyframe.time_seconds, keyframe.value) for keyframe in keyframes)
        ).evaluate(time_seconds)
    elif track.interpolation == Interpolation.CUBIC and len(keyframes) >= 3:
        value = _catmull_rom_value(
            track,
            left_index,
            right_index,
            position,
        )
    else:
        value = left.value + (right.value - left.value) * position

    elapsed = time_seconds - left.time_seconds
    remaining = right.time_seconds - time_seconds
    if track.max_velocity is not None:
        lower = max(
            left.value - track.max_velocity * elapsed,
            right.value - track.max_velocity * remaining,
        )
        upper = min(
            left.value + track.max_velocity * elapsed,
            right.value + track.max_velocity * remaining,
        )
        if lower <= upper:
            value = max(lower, min(upper, value))
        else:
            value = left.value + (right.value - left.value) * position

    if track.max_acceleration is not None:
        linear = left.value + (right.value - left.value) * position
        maximum_curve_deviation = track.max_acceleration * elapsed * remaining / 2
        value = max(
            linear - maximum_curve_deviation,
            min(linear + maximum_curve_deviation, value),
        )
    return value


def evaluate_track_batch(
    track: ParameterTrack,
    time_seconds: Sequence[float] | torch.Tensor,
) -> torch.Tensor:
    """Evaluate one parameter track for many timestamps without a Python frame loop."""

    source = (
        time_seconds.detach().to(device="cpu", dtype=torch.float64)
        if isinstance(time_seconds, torch.Tensor)
        else torch.as_tensor(time_seconds, dtype=torch.float64)
    )
    original_shape = source.shape
    timestamps = source.reshape(-1)
    keyframes = track.keyframes
    if not keyframes:
        raise ValueError("parameter track must contain at least one keyframe")
    if timestamps.numel() == 0:
        return timestamps.reshape(original_shape)
    if len(keyframes) == 1:
        return torch.full_like(timestamps, keyframes[0].value).reshape(original_shape)

    times = torch.tensor(
        [keyframe.time_seconds for keyframe in keyframes],
        dtype=torch.float64,
    )
    values = torch.tensor(
        [keyframe.value for keyframe in keyframes],
        dtype=torch.float64,
    )
    left_indices = torch.searchsorted(times, timestamps, right=True).sub(1)
    left_indices = left_indices.clamp(0, len(keyframes) - 2)
    right_indices = left_indices + 1
    left_times = times[left_indices]
    right_times = times[right_indices]
    left_values = values[left_indices]
    right_values = values[right_indices]
    spans = right_times - left_times
    positions = (timestamps - left_times) / spans
    linear_values = left_values + (right_values - left_values) * positions

    if track.interpolation == Interpolation.HOLD:
        evaluated = left_values
    elif track.interpolation == Interpolation.LINEAR:
        evaluated = linear_values
    elif track.interpolation == Interpolation.PCHIP:
        curve = _compile_pchip(
            tuple((keyframe.time_seconds, keyframe.value) for keyframe in keyframes)
        )
        constants = torch.tensor(
            [interval.constant for interval in curve.intervals],
            dtype=torch.float64,
        )[left_indices]
        linears = torch.tensor(
            [interval.linear for interval in curve.intervals],
            dtype=torch.float64,
        )[left_indices]
        quadratics = torch.tensor(
            [interval.quadratic for interval in curve.intervals],
            dtype=torch.float64,
        )[left_indices]
        cubics = torch.tensor(
            [interval.cubic for interval in curve.intervals],
            dtype=torch.float64,
        )[left_indices]
        elapsed = timestamps - left_times
        evaluated = (
            (cubics * elapsed + quadratics) * elapsed + linears
        ) * elapsed + constants
    elif track.interpolation == Interpolation.CUBIC and len(keyframes) >= 3:
        previous_values = values[(left_indices - 1).clamp_min(0)]
        following_values = values[
            (right_indices + 1).clamp_max(len(keyframes) - 1)
        ]
        position_squared = positions.square()
        position_cubed = position_squared * positions
        evaluated = 0.5 * (
            2 * left_values
            + (-previous_values + right_values) * positions
            + (
                2 * previous_values
                - 5 * left_values
                + 4 * right_values
                - following_values
            )
            * position_squared
            + (
                -previous_values
                + 3 * left_values
                - 3 * right_values
                + following_values
            )
            * position_cubed
        )
    else:
        evaluated = linear_values

    elapsed = timestamps - left_times
    remaining = right_times - timestamps
    if track.max_velocity is not None:
        lower = torch.maximum(
            left_values - track.max_velocity * elapsed,
            right_values - track.max_velocity * remaining,
        )
        upper = torch.minimum(
            left_values + track.max_velocity * elapsed,
            right_values + track.max_velocity * remaining,
        )
        evaluated = torch.where(
            lower <= upper,
            torch.maximum(lower, torch.minimum(upper, evaluated)),
            linear_values,
        )

    if track.max_acceleration is not None:
        maximum_curve_deviation = (
            track.max_acceleration * elapsed * remaining / 2
        )
        evaluated = torch.maximum(
            linear_values - maximum_curve_deviation,
            torch.minimum(linear_values + maximum_curve_deviation, evaluated),
        )

    evaluated = torch.where(timestamps <= times[0], values[0], evaluated)
    evaluated = torch.where(timestamps >= times[-1], values[-1], evaluated)
    return evaluated.reshape(original_shape)
