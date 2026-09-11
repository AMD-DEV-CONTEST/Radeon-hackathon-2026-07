"""Geometry-first grasp routing for mobile tri-suction parcel handling."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Literal, Sequence


GraspMode = Literal["top_suction", "side_suction", "cooperative_cradle"]


@dataclass(frozen=True)
class MobileGraspRoute:
    mode: GraspMode
    minimum_sealed_cups: int
    cooperative_cradle: bool
    reason: str


def top_down_grasp_quaternion(yaw_rad: float) -> tuple[float, float, float, float]:
    """Return a top-down tool quaternion whose cup footprint follows parcel yaw."""

    if not math.isfinite(yaw_rad):
        raise ValueError("yaw_rad must be finite")
    half_yaw = 0.5 * float(yaw_rad)
    return (0.0, math.cos(half_yaw), math.sin(half_yaw), 0.0)


def radial_side_grasp_quaternion() -> tuple[float, float, float, float]:
    """Point the tool normal along world +Y with its footprint plane vertical."""

    half_turn = math.sqrt(0.5)
    return (half_turn, -half_turn, 0.0, 0.0)


def top_suction_active_cup_indices(minimum_sealed_cups: int) -> tuple[int, ...]:
    """Select a balanced subset from the fixed triangular cup footprint."""

    if minimum_sealed_cups == 1:
        return (0,)
    if minimum_sealed_cups == 2:
        return (1, 2)
    if minimum_sealed_cups == 3:
        return (0, 1, 2)
    raise ValueError("minimum_sealed_cups must be in [1, 3]")


def route_mobile_grasp(
    *,
    shape: str,
    orientation_mode: str,
    size_m: Sequence[float],
    mass_kg: float,
    handling_class: str,
) -> MobileGraspRoute:
    """Select a physically compatible grasp mode without using trial outcomes."""

    if shape not in {"box", "cylinder"}:
        raise ValueError(f"unsupported parcel shape: {shape}")
    if orientation_mode not in {"yaw", "upright", "horizontal"}:
        raise ValueError(f"unsupported parcel orientation: {orientation_mode}")
    if len(size_m) != 3 or any(not math.isfinite(float(value)) for value in size_m):
        raise ValueError("size_m must contain three finite values")
    dimensions = tuple(float(value) for value in size_m)
    if min(dimensions) <= 0.0 or not math.isfinite(mass_kg) or mass_kg <= 0.0:
        raise ValueError("parcel dimensions and mass must be positive")

    if (
        handling_class == "cradle_required"
        or (shape == "cylinder" and orientation_mode == "horizontal")
        or mass_kg > 3.0
        or max(dimensions) > 0.60
        or (max(dimensions) >= 0.28 and mass_kg >= 1.0)
    ):
        return MobileGraspRoute(
            mode="cooperative_cradle",
            minimum_sealed_cups=_top_surface_cup_capacity(dimensions[:2]),
            cooperative_cradle=True,
            reason="horizontal, heavy, or oversized payload requires right-arm support",
        )

    if shape == "cylinder" and orientation_mode == "upright":
        diameter = min(dimensions[0], dimensions[1])
        return MobileGraspRoute(
            mode="side_suction",
            minimum_sealed_cups=1 if diameter < 0.055 else 2,
            cooperative_cradle=False,
            reason="upright cylinder exposes a stable lateral surface",
        )

    available_top_cups = _top_surface_cup_capacity(dimensions[:2])
    required_top_cups = _load_required_cups(mass_kg)
    if required_top_cups > available_top_cups:
        return MobileGraspRoute(
            mode="cooperative_cradle",
            minimum_sealed_cups=available_top_cups,
            cooperative_cradle=True,
            reason="top surface cannot fit the suction cups required by payload load",
        )
    return MobileGraspRoute(
        mode="top_suction",
        minimum_sealed_cups=required_top_cups,
        cooperative_cradle=False,
        reason="box-like parcel supports the load-required top suction cup count",
    )


def _top_surface_cup_capacity(surface_dimensions_m: Sequence[float]) -> int:
    """Return how many physical 12 mm/35 mm cups fit the top surface."""

    long_side, short_side = sorted(
        (float(surface_dimensions_m[0]), float(surface_dimensions_m[1])), reverse=True
    )
    cup_diameter_m = 0.024
    footprint_radius_m = 0.035
    two_cup_long_span_m = math.sqrt(3.0) * footprint_radius_m + cup_diameter_m
    three_cup_short_span_m = 1.5 * footprint_radius_m + cup_diameter_m
    if (
        short_side >= three_cup_short_span_m
        and long_side >= two_cup_long_span_m
    ):
        return 3
    if short_side >= cup_diameter_m and long_side >= two_cup_long_span_m:
        return 2
    return 1


def _load_required_cups(mass_kg: float) -> int:
    """Require enough 10 N cups for gravity with a 1.5x load safety factor."""

    required = int(math.ceil(float(mass_kg) * 9.81 * 1.5 / 10.0))
    return min(3, max(1, required))
