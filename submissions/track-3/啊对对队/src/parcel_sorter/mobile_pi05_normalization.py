"""Numerical guards for PI0.5 quantile-normalized vector features."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
import math
from typing import Any


PI05_NORMALIZATION_EPS = 1e-8


def unsafe_quantile_dimensions(
    stats: Mapping[str, Sequence[float]],
    names: Sequence[str],
    *,
    eps: float = PI05_NORMALIZATION_EPS,
) -> tuple[str, ...]:
    """Return variable dimensions whose q01-q99 scale collapses to epsilon."""

    vectors = _validated_vectors(stats, names)
    return tuple(
        str(names[index])
        for index in range(len(names))
        if vectors["max"][index] - vectors["min"][index] > eps
        and vectors["q99"][index] - vectors["q01"][index] <= eps
    )


def stabilize_quantile_stats(
    stats: Mapping[str, Any],
    names: Sequence[str],
    *,
    eps: float = PI05_NORMALIZATION_EPS,
) -> tuple[dict[str, Any], tuple[str, ...]]:
    """Use observed min/max only when variable data has collapsed quantiles.

    Constant dimensions remain unchanged. LeRobot maps their sole observed value
    deterministically, while a variable dimension with q01 == q99 would amplify
    valid labels by roughly 1 / eps.
    """

    vectors = _validated_vectors(stats, names)
    result = deepcopy(dict(stats))
    result["q01"] = list(vectors["q01"])
    result["q99"] = list(vectors["q99"])
    repaired = []
    for index, name in enumerate(names):
        observed_span = vectors["max"][index] - vectors["min"][index]
        quantile_span = vectors["q99"][index] - vectors["q01"][index]
        if observed_span > eps and quantile_span <= eps:
            result["q01"][index] = vectors["min"][index]
            result["q99"][index] = vectors["max"][index]
            repaired.append(str(name))
    return result, tuple(repaired)


def constant_dimensions(
    stats: Mapping[str, Sequence[float]],
    names: Sequence[str],
    *,
    eps: float = PI05_NORMALIZATION_EPS,
) -> tuple[str, ...]:
    """Return dimensions that are constant over all observed frames."""

    vectors = _validated_vectors(stats, names)
    return tuple(
        str(names[index])
        for index in range(len(names))
        if vectors["max"][index] - vectors["min"][index] <= eps
    )


def _validated_vectors(
    stats: Mapping[str, Sequence[float]],
    names: Sequence[str],
) -> dict[str, tuple[float, ...]]:
    if not names:
        raise ValueError("normalization feature names cannot be empty")
    vectors = {}
    for key in ("min", "max", "q01", "q99"):
        raw = stats.get(key)
        if raw is None or len(raw) != len(names):
            raise ValueError(f"normalization stats {key!r} length mismatch")
        values = tuple(float(value) for value in raw)
        if any(not math.isfinite(value) for value in values):
            raise ValueError(f"normalization stats {key!r} contain non-finite values")
        vectors[key] = values
    for index, name in enumerate(names):
        if vectors["max"][index] < vectors["min"][index]:
            raise ValueError(f"normalization min exceeds max for {name}")
        if vectors["q99"][index] < vectors["q01"][index]:
            raise ValueError(f"normalization q01 exceeds q99 for {name}")
    return vectors
