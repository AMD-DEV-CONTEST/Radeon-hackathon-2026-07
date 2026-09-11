"""Tri-cup suction geometry and compliant attachment math.

The simulator keeps suction actuation separate from policy inference: a policy
requests the same binary gripper command, while this module validates a seal
and computes a bounded six-dimensional wrench for the free parcel body.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable


Vector3 = tuple[float, float, float]
Quaternion = tuple[float, float, float, float]


@dataclass(frozen=True)
class SuctionAttachment:
    relative_position_m: Vector3
    relative_quaternion_wxyz: Quaternion
    sealed_cup_count: int


@dataclass(frozen=True)
class SuctionWrench:
    force_world_n: Vector3
    torque_world_nm: Vector3
    position_error_m: float
    orientation_error_rad: float
    broken: bool


def inertia_scaled_rotational_gains(
    minimum_principal_inertia_kg_m2: float,
    *,
    natural_frequency_rad_s: float = 20.0,
    maximum_stiffness_nm_rad: float = 5.0,
) -> tuple[float, float]:
    """Return stable, critically damped gains for the lightest rotation axis."""

    values = (
        minimum_principal_inertia_kg_m2,
        natural_frequency_rad_s,
        maximum_stiffness_nm_rad,
    )
    if any(not math.isfinite(value) or value <= 0.0 for value in values):
        raise ValueError("inertia and rotational-gain limits must be finite and positive")
    stiffness = min(
        maximum_stiffness_nm_rad,
        minimum_principal_inertia_kg_m2 * natural_frequency_rad_s**2,
    )
    damping = 2.0 * math.sqrt(stiffness * minimum_principal_inertia_kg_m2)
    return stiffness, damping


def tri_cup_offsets(footprint_radius_m: float) -> tuple[Vector3, Vector3, Vector3]:
    """Return an equilateral three-cup layout in the hand XY plane."""

    if not math.isfinite(footprint_radius_m) or footprint_radius_m <= 0:
        raise ValueError("suction footprint radius must be finite and positive")
    radius = float(footprint_radius_m)
    return (
        (0.0, radius, 0.0),
        (-math.sqrt(3.0) * radius / 2.0, -radius / 2.0, 0.0),
        (math.sqrt(3.0) * radius / 2.0, -radius / 2.0, 0.0),
    )


def quaternion_conjugate(quaternion: Quaternion) -> Quaternion:
    w, x, y, z = _normalized_quaternion(quaternion)
    return (w, -x, -y, -z)


def quaternion_multiply(left: Quaternion, right: Quaternion) -> Quaternion:
    lw, lx, ly, lz = left
    rw, rx, ry, rz = right
    return _normalized_quaternion(
        (
            lw * rw - lx * rx - ly * ry - lz * rz,
            lw * rx + lx * rw + ly * rz - lz * ry,
            lw * ry - lx * rz + ly * rw + lz * rx,
            lw * rz + lx * ry - ly * rx + lz * rw,
        )
    )


def rotate_vector(quaternion: Quaternion, vector: Vector3) -> Vector3:
    w, x, y, z = _normalized_quaternion(quaternion)
    vx, vy, vz = vector
    # Expanded q * [0, v] * conjugate(q), avoiding normalization of [0, v].
    tx = 2.0 * (y * vz - z * vy)
    ty = 2.0 * (z * vx - x * vz)
    tz = 2.0 * (x * vy - y * vx)
    return (
        vx + w * tx + y * tz - z * ty,
        vy + w * ty + z * tx - x * tz,
        vz + w * tz + x * ty - y * tx,
    )


def create_attachment(
    hand_position_m: Vector3,
    hand_quaternion_wxyz: Quaternion,
    parcel_position_m: Vector3,
    parcel_quaternion_wxyz: Quaternion,
    *,
    sealed_cup_count: int,
) -> SuctionAttachment:
    if sealed_cup_count < 1:
        raise ValueError("a suction attachment requires at least one sealed cup")
    inverse_hand = quaternion_conjugate(hand_quaternion_wxyz)
    relative_world = tuple(
        parcel - hand
        for parcel, hand in zip(parcel_position_m, hand_position_m, strict=True)
    )
    return SuctionAttachment(
        relative_position_m=rotate_vector(inverse_hand, relative_world),
        relative_quaternion_wxyz=quaternion_multiply(
            inverse_hand,
            parcel_quaternion_wxyz,
        ),
        sealed_cup_count=sealed_cup_count,
    )


def compliant_suction_wrench(
    attachment: SuctionAttachment,
    hand_position_m: Vector3,
    hand_quaternion_wxyz: Quaternion,
    parcel_position_m: Vector3,
    parcel_quaternion_wxyz: Quaternion,
    parcel_linear_velocity_m_s: Vector3,
    parcel_angular_velocity_rad_s: Vector3,
    *,
    translational_stiffness_n_m: float,
    translational_damping_n_s_m: float,
    rotational_stiffness_nm_rad: float,
    rotational_damping_nm_s_rad: float,
    max_force_n: float,
    max_torque_nm: float,
    break_distance_m: float,
    break_angle_rad: float,
    free_twist_axis_world: Vector3 | None = None,
) -> SuctionWrench:
    """Compute a bounded spring-damper wrench for a latched parcel."""

    positive = (
        translational_stiffness_n_m,
        translational_damping_n_s_m,
        rotational_stiffness_nm_rad,
        rotational_damping_nm_s_rad,
        max_force_n,
        max_torque_nm,
        break_distance_m,
        break_angle_rad,
    )
    if any(not math.isfinite(value) or value <= 0 for value in positive):
        raise ValueError("suction wrench limits and gains must be finite and positive")

    desired_position = tuple(
        hand + relative
        for hand, relative in zip(
            hand_position_m,
            rotate_vector(hand_quaternion_wxyz, attachment.relative_position_m),
            strict=True,
        )
    )
    position_error = tuple(
        desired - current
        for desired, current in zip(desired_position, parcel_position_m, strict=True)
    )
    position_error_m = _norm(position_error)

    desired_quaternion = quaternion_multiply(
        hand_quaternion_wxyz,
        attachment.relative_quaternion_wxyz,
    )
    error_quaternion = quaternion_multiply(
        desired_quaternion,
        quaternion_conjugate(parcel_quaternion_wxyz),
    )
    if error_quaternion[0] < 0:
        error_quaternion = tuple(-value for value in error_quaternion)  # type: ignore[assignment]
    vector_norm = _norm(error_quaternion[1:])
    orientation_error_rad = 2.0 * math.atan2(vector_norm, max(0.0, error_quaternion[0]))
    if vector_norm <= 1e-12:
        rotation_vector = (0.0, 0.0, 0.0)
    else:
        rotation_vector = tuple(
            value / vector_norm * orientation_error_rad
            for value in error_quaternion[1:]
        )
    if free_twist_axis_world is not None:
        axis_norm = _norm(free_twist_axis_world)
        if axis_norm <= 1e-12:
            raise ValueError("free twist axis must have non-zero length")
        axis = tuple(value / axis_norm for value in free_twist_axis_world)
        twist = sum(
            value * component
            for value, component in zip(rotation_vector, axis, strict=True)
        )
        rotation_vector = tuple(
            value - twist * component
            for value, component in zip(rotation_vector, axis, strict=True)
        )
        orientation_error_rad = _norm(rotation_vector)

    broken = (
        position_error_m > break_distance_m
        or orientation_error_rad > break_angle_rad
    )
    if broken:
        return SuctionWrench(
            force_world_n=(0.0, 0.0, 0.0),
            torque_world_nm=(0.0, 0.0, 0.0),
            position_error_m=position_error_m,
            orientation_error_rad=orientation_error_rad,
            broken=True,
        )

    force = tuple(
        translational_stiffness_n_m * error
        - translational_damping_n_s_m * velocity
        for error, velocity in zip(
            position_error,
            parcel_linear_velocity_m_s,
            strict=True,
        )
    )
    torque = tuple(
        rotational_stiffness_nm_rad * error
        - rotational_damping_nm_s_rad * velocity
        for error, velocity in zip(
            rotation_vector,
            parcel_angular_velocity_rad_s,
            strict=True,
        )
    )
    return SuctionWrench(
        force_world_n=_limit_norm(force, max_force_n),
        torque_world_nm=_limit_norm(torque, max_torque_nm),
        position_error_m=position_error_m,
        orientation_error_rad=orientation_error_rad,
        broken=False,
    )


def _normalized_quaternion(quaternion: Iterable[float]) -> Quaternion:
    values = tuple(float(value) for value in quaternion)
    if len(values) != 4 or any(not math.isfinite(value) for value in values):
        raise ValueError("quaternion must contain four finite values")
    norm = _norm(values)
    if norm <= 1e-12:
        raise ValueError("quaternion norm must be positive")
    return tuple(value / norm for value in values)  # type: ignore[return-value]


def _norm(values: Iterable[float]) -> float:
    return math.sqrt(sum(float(value) ** 2 for value in values))


def _limit_norm(values: Vector3, maximum: float) -> Vector3:
    norm = _norm(values)
    if norm <= maximum or norm <= 1e-12:
        return values
    scale = maximum / norm
    return tuple(value * scale for value in values)  # type: ignore[return-value]
