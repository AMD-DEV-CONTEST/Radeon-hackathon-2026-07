from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Sequence

from .randomization import ParcelSample


Vector3 = tuple[float, float, float]
Quaternion = tuple[float, float, float, float]


@dataclass(frozen=True)
class CylinderGeometry:
    orientation_mode: str
    axial_length_m: float
    diameter_m: float
    radius_m: float
    centre: Vector3
    axis_world: Vector3


@dataclass(frozen=True)
class CylinderGraspCapability:
    supported: bool
    reason: str
    geometry: CylinderGeometry
    jaw_aperture_m: float
    aperture_margin_m: float
    rolling_friction: float
    rolling_risk_index: float


@dataclass(frozen=True)
class CylinderGraspPoseCandidate:
    candidate_id: str
    target_position: Vector3
    target_quaternion: Quaternion
    longitudinal_offset_m: float
    vertical_offset_m: float
    wrist_variant: str
    approach_variant: str
    approach_direction: Vector3
    radial_approach_angle_rad: float
    aperture_margin_m: float
    centre_of_mass_moment_arm_m: float
    rolling_risk_score: float


@dataclass(frozen=True)
class CylinderGraspPlan:
    capability: CylinderGraspCapability
    candidates: tuple[CylinderGraspPoseCandidate, ...]


def assess_cylinder_grasp_capability(
    sample: ParcelSample,
    parcel_pose: Sequence[float],
    *,
    jaw_aperture_m: float,
    min_aperture_margin_m: float = 0.001,
    min_horizontal_rolling_friction: float = 0.001,
    max_parallel_jaw_length_m: float | None = 0.320,
    max_axis_tilt_deg: float = 20.0,
) -> CylinderGraspCapability:
    """Return an explicit parallel-jaw capability decision for one cylinder.

    The rolling-risk index is a conservative heuristic for ordering and
    reporting, not a calibrated failure probability.
    """
    if jaw_aperture_m <= 0 or min_aperture_margin_m < 0:
        raise ValueError("jaw aperture must be positive and its margin non-negative")
    if min_horizontal_rolling_friction < 0:
        raise ValueError("minimum horizontal rolling friction cannot be negative")
    if max_parallel_jaw_length_m is not None and max_parallel_jaw_length_m <= 0:
        raise ValueError("maximum parallel-jaw length must be positive")
    if not 0 < max_axis_tilt_deg < 90:
        raise ValueError("maximum cylinder-axis tilt must be in (0, 90) degrees")

    geometry = cylinder_geometry(sample, parcel_pose)
    aperture_margin_m = jaw_aperture_m - geometry.diameter_m
    rolling_risk_index = (
        min(
            1.0,
            min_horizontal_rolling_friction
            / max(sample.rolling_friction, 1e-12),
        )
        if sample.orientation_mode == "horizontal"
        and min_horizontal_rolling_friction > 0
        else 0.0
    )
    common = {
        "geometry": geometry,
        "jaw_aperture_m": float(jaw_aperture_m),
        "aperture_margin_m": float(aperture_margin_m),
        "rolling_friction": float(sample.rolling_friction),
        "rolling_risk_index": float(rolling_risk_index),
    }

    if sample.handling_class != "parallel_jaw":
        return CylinderGraspCapability(
            supported=False,
            reason=f"unsupported_handling_class:{sample.handling_class}",
            **common,
        )
    if aperture_margin_m + 1e-12 < min_aperture_margin_m:
        return CylinderGraspCapability(
            supported=False,
            reason="jaw_aperture_margin_below_limit",
            **common,
        )
    if (
        max_parallel_jaw_length_m is not None
        and geometry.axial_length_m > max_parallel_jaw_length_m + 1e-12
    ):
        return CylinderGraspCapability(
            supported=False,
            reason="axial_length_exceeds_parallel_jaw_limit",
            **common,
        )

    vertical_alignment = abs(geometry.axis_world[2])
    maximum_tilt_rad = math.radians(max_axis_tilt_deg)
    if sample.orientation_mode == "upright":
        if vertical_alignment + 1e-12 < math.cos(maximum_tilt_rad):
            return CylinderGraspCapability(
                supported=False,
                reason="upright_axis_tilt_exceeds_limit",
                **common,
            )
    elif vertical_alignment > math.sin(maximum_tilt_rad) + 1e-12:
        return CylinderGraspCapability(
            supported=False,
            reason="horizontal_axis_tilt_exceeds_limit",
            **common,
        )
    if (
        sample.orientation_mode == "horizontal"
        and sample.rolling_friction + 1e-12 < min_horizontal_rolling_friction
    ):
        return CylinderGraspCapability(
            supported=False,
            reason="horizontal_tube_requires_guarded_support",
            **common,
        )
    return CylinderGraspCapability(supported=True, reason="supported", **common)


def plan_cylinder_grasp_candidates(
    sample: ParcelSample,
    parcel_pose: Sequence[float],
    *,
    hand_clearance_m: float,
    jaw_aperture_m: float,
    min_aperture_margin_m: float = 0.001,
    min_horizontal_rolling_friction: float = 0.001,
    max_parallel_jaw_length_m: float | None = 0.320,
    max_axis_tilt_deg: float = 20.0,
    include_symmetric_wrist: bool = True,
    upright_radial_yaw_count: int = 4,
    max_upright_vertical_offset_m: float = 0.020,
    min_upright_side_overlap_m: float = 0.020,
    max_horizontal_axial_offset_m: float = 0.050,
    min_horizontal_end_margin_m: float = 0.060,
    horizontal_radial_angles_deg: tuple[float, ...] = (0.0, -20.0, 20.0),
) -> CylinderGraspPlan:
    """Generate deterministic candidates or return an explicit empty capability plan."""
    if hand_clearance_m <= 0:
        raise ValueError("hand clearance must be positive")
    capability = assess_cylinder_grasp_capability(
        sample,
        parcel_pose,
        jaw_aperture_m=jaw_aperture_m,
        min_aperture_margin_m=min_aperture_margin_m,
        min_horizontal_rolling_friction=min_horizontal_rolling_friction,
        max_parallel_jaw_length_m=max_parallel_jaw_length_m,
        max_axis_tilt_deg=max_axis_tilt_deg,
    )
    if not capability.supported:
        return CylinderGraspPlan(capability=capability, candidates=())

    if sample.orientation_mode == "upright":
        candidates = _upright_candidates(
            capability,
            hand_clearance_m=hand_clearance_m,
            include_symmetric_wrist=include_symmetric_wrist,
            radial_yaw_count=upright_radial_yaw_count,
            max_vertical_offset_m=max_upright_vertical_offset_m,
            min_side_overlap_m=min_upright_side_overlap_m,
        )
    else:
        candidates = _horizontal_candidates(
            capability,
            hand_clearance_m=hand_clearance_m,
            include_symmetric_wrist=include_symmetric_wrist,
            max_axial_offset_m=max_horizontal_axial_offset_m,
            min_end_margin_m=min_horizontal_end_margin_m,
            radial_angles_deg=horizontal_radial_angles_deg,
        )
    return CylinderGraspPlan(capability=capability, candidates=candidates)


def cylinder_candidate_prior_key(
    candidate: CylinderGraspPoseCandidate,
) -> tuple[float, float, bool, float, str]:
    """Prefer low-roll, centred, canonical candidates before IK-based ranking."""
    return (
        candidate.rolling_risk_score,
        candidate.centre_of_mass_moment_arm_m,
        candidate.wrist_variant != "canonical",
        abs(candidate.vertical_offset_m),
        candidate.candidate_id,
    )


def point_to_capsule_signed_distance(
    point: Sequence[float],
    *,
    centre: Sequence[float],
    axis: Sequence[float],
    half_segment_length_m: float,
    radius_m: float,
) -> float:
    """Signed distance to a conservative capsule envelope around a cylinder."""
    if len(point) != 3 or len(centre) != 3 or len(axis) != 3:
        raise ValueError("capsule point, centre, and axis must be three-dimensional")
    if half_segment_length_m < 0 or radius_m <= 0:
        raise ValueError("capsule half length must be non-negative and radius positive")
    unit_axis = _normalize(tuple(float(value) for value in axis))
    relative = tuple(float(p) - float(c) for p, c in zip(point, centre, strict=True))
    axial = max(
        -half_segment_length_m,
        min(half_segment_length_m, _dot(relative, unit_axis)),
    )
    closest = tuple(
        float(c) + axial * direction
        for c, direction in zip(centre, unit_axis, strict=True)
    )
    return math.dist(tuple(float(value) for value in point), closest) - radius_m


def cylinder_geometry(
    sample: ParcelSample,
    parcel_pose: Sequence[float],
) -> CylinderGeometry:
    if sample.shape != "cylinder" or sample.dimensions_m is None:
        raise ValueError("cylinder planning requires explicit cylinder dimensions")
    if sample.orientation_mode not in {"upright", "horizontal"}:
        raise ValueError("cylinder orientation must be upright or horizontal")
    if len(parcel_pose) < 7:
        raise ValueError("parcel pose must contain xyz and a wxyz quaternion")
    if any(not math.isfinite(float(value)) for value in (*sample.dimensions_m, *parcel_pose[:7])):
        raise ValueError("cylinder dimensions and pose must be finite")
    if any(value <= 0 for value in sample.dimensions_m):
        raise ValueError("cylinder dimensions must be positive")

    if sample.orientation_mode == "upright":
        diameter_a, diameter_b, axial_length_m = sample.dimensions_m
    else:
        axial_length_m, diameter_a, diameter_b = sample.dimensions_m
    if not math.isclose(diameter_a, diameter_b, rel_tol=1e-6, abs_tol=1e-9):
        raise ValueError("cylinder radial dimensions must agree")
    diameter_m = (diameter_a + diameter_b) / 2

    quaternion = tuple(float(value) for value in parcel_pose[3:7])
    axis_world = _rotate_local_z(quaternion)
    expected_axis = (
        (0.0, 0.0, 1.0)
        if sample.orientation_mode == "upright"
        else (math.cos(sample.yaw_rad), math.sin(sample.yaw_rad), 0.0)
    )
    if _dot(axis_world, expected_axis) < 0:
        axis_world = tuple(-value for value in axis_world)
    return CylinderGeometry(
        orientation_mode=sample.orientation_mode,
        axial_length_m=float(axial_length_m),
        diameter_m=float(diameter_m),
        radius_m=float(diameter_m / 2),
        centre=tuple(float(value) for value in parcel_pose[:3]),
        axis_world=axis_world,
    )


def _upright_candidates(
    capability: CylinderGraspCapability,
    *,
    hand_clearance_m: float,
    include_symmetric_wrist: bool,
    radial_yaw_count: int,
    max_vertical_offset_m: float,
    min_side_overlap_m: float,
) -> tuple[CylinderGraspPoseCandidate, ...]:
    if radial_yaw_count < 1:
        raise ValueError("upright radial yaw count must be positive")
    if max_vertical_offset_m < 0 or min_side_overlap_m <= 0:
        raise ValueError("upright offset must be non-negative and overlap positive")

    geometry = capability.geometry
    available_offset_m = max(
        0.0,
        geometry.axial_length_m / 2 - min_side_overlap_m,
    )
    vertical_extent_m = min(max_vertical_offset_m, available_offset_m)
    vertical_offsets_m = _unique_values((0.0, vertical_extent_m))
    approach_direction = (0.0, 0.0, -1.0)
    candidates = []
    for radial_index in range(radial_yaw_count):
        radial_yaw = radial_index * math.pi / radial_yaw_count
        for wrist_variant, wrist_yaw in _wrist_variants(
            radial_yaw,
            include_symmetric_wrist,
        ):
            local_x = (math.cos(wrist_yaw), math.sin(wrist_yaw), 0.0)
            local_y = _cross(approach_direction, local_x)
            quaternion = _quaternion_from_basis(local_x, local_y, approach_direction)
            for vertical_offset_m in vertical_offsets_m:
                target_position = _add(
                    geometry.centre,
                    _scale(geometry.axis_world, vertical_offset_m),
                    _scale(approach_direction, -hand_clearance_m),
                )
                candidate_id = (
                    f"upright-yaw-{math.degrees(radial_yaw):05.1f}"
                    f"-{wrist_variant}-up-{vertical_offset_m:.3f}"
                )
                candidates.append(
                    CylinderGraspPoseCandidate(
                        candidate_id=candidate_id,
                        target_position=target_position,
                        target_quaternion=quaternion,
                        longitudinal_offset_m=0.0,
                        vertical_offset_m=vertical_offset_m,
                        wrist_variant=wrist_variant,
                        approach_variant="upright_top_down_radial",
                        approach_direction=approach_direction,
                        radial_approach_angle_rad=0.0,
                        aperture_margin_m=capability.aperture_margin_m,
                        centre_of_mass_moment_arm_m=0.0,
                        rolling_risk_score=0.0,
                    )
                )
    return tuple(candidates)


def _horizontal_candidates(
    capability: CylinderGraspCapability,
    *,
    hand_clearance_m: float,
    include_symmetric_wrist: bool,
    max_axial_offset_m: float,
    min_end_margin_m: float,
    radial_angles_deg: tuple[float, ...],
) -> tuple[CylinderGraspPoseCandidate, ...]:
    if max_axial_offset_m < 0 or min_end_margin_m <= 0:
        raise ValueError("horizontal offset must be non-negative and end margin positive")
    if not radial_angles_deg or any(
        not math.isfinite(angle) or abs(angle) >= 90
        for angle in radial_angles_deg
    ):
        raise ValueError("horizontal radial angles must be finite and in (-90, 90)")

    geometry = capability.geometry
    available_offset_m = max(
        0.0,
        geometry.axial_length_m / 2 - min_end_margin_m,
    )
    axial_extent_m = min(max_axial_offset_m, available_offset_m)
    axial_offsets_m = _unique_values((-axial_extent_m, 0.0, axial_extent_m))
    downward = (0.0, 0.0, -1.0)
    base_approach = _normalize(
        _subtract(downward, _scale(geometry.axis_world, _dot(downward, geometry.axis_world)))
    )
    side_normal = _normalize(_cross(geometry.axis_world, base_approach))
    candidates = []
    for radial_angle_deg in _unique_values(radial_angles_deg):
        radial_angle_rad = math.radians(radial_angle_deg)
        approach_direction = _normalize(
            _add(
                _scale(base_approach, math.cos(radial_angle_rad)),
                _scale(side_normal, math.sin(radial_angle_rad)),
            )
        )
        rolling_risk_score = min(
            1.0,
            0.5 * capability.rolling_risk_index
            + 0.5 * abs(math.sin(radial_angle_rad)),
        )
        for wrist_variant, wrist_sign in (
            (("canonical", 1.0), ("symmetric_pi", -1.0))
            if include_symmetric_wrist
            else (("canonical", 1.0),)
        ):
            local_x = _scale(geometry.axis_world, wrist_sign)
            local_y = _normalize(_cross(approach_direction, local_x))
            quaternion = _quaternion_from_basis(
                local_x,
                local_y,
                approach_direction,
            )
            for axial_offset_m in axial_offsets_m:
                target_position = _add(
                    geometry.centre,
                    _scale(geometry.axis_world, axial_offset_m),
                    _scale(approach_direction, -hand_clearance_m),
                )
                candidate_id = (
                    f"horizontal-radial-{radial_angle_deg:+05.1f}"
                    f"-{wrist_variant}-axis-{axial_offset_m:+.3f}"
                )
                candidates.append(
                    CylinderGraspPoseCandidate(
                        candidate_id=candidate_id,
                        target_position=target_position,
                        target_quaternion=quaternion,
                        longitudinal_offset_m=axial_offset_m,
                        vertical_offset_m=0.0,
                        wrist_variant=wrist_variant,
                        approach_variant="horizontal_cross_diameter",
                        approach_direction=approach_direction,
                        radial_approach_angle_rad=radial_angle_rad,
                        aperture_margin_m=capability.aperture_margin_m,
                        centre_of_mass_moment_arm_m=abs(axial_offset_m),
                        rolling_risk_score=rolling_risk_score,
                    )
                )
    return tuple(candidates)


def _wrist_variants(
    base_yaw: float,
    include_symmetric_wrist: bool,
) -> tuple[tuple[str, float], ...]:
    variants = [("canonical", base_yaw)]
    if include_symmetric_wrist:
        variants.append(("symmetric_pi", base_yaw + math.pi))
    return tuple(variants)


def _rotate_local_z(quaternion: Quaternion) -> Vector3:
    norm = math.sqrt(sum(value * value for value in quaternion))
    if norm <= 1e-12:
        raise ValueError("parcel quaternion must have non-zero norm")
    w, x, y, z = (value / norm for value in quaternion)
    return _normalize(
        (
            2 * (x * z + w * y),
            2 * (y * z - w * x),
            1 - 2 * (x * x + y * y),
        )
    )


def _quaternion_from_basis(
    local_x_world: Vector3,
    local_y_world: Vector3,
    local_z_world: Vector3,
) -> Quaternion:
    matrix = (
        (local_x_world[0], local_y_world[0], local_z_world[0]),
        (local_x_world[1], local_y_world[1], local_z_world[1]),
        (local_x_world[2], local_y_world[2], local_z_world[2]),
    )
    trace = matrix[0][0] + matrix[1][1] + matrix[2][2]
    if trace > 0:
        scale = math.sqrt(trace + 1.0) * 2
        quaternion = (
            0.25 * scale,
            (matrix[2][1] - matrix[1][2]) / scale,
            (matrix[0][2] - matrix[2][0]) / scale,
            (matrix[1][0] - matrix[0][1]) / scale,
        )
    elif matrix[0][0] > matrix[1][1] and matrix[0][0] > matrix[2][2]:
        scale = math.sqrt(1.0 + matrix[0][0] - matrix[1][1] - matrix[2][2]) * 2
        quaternion = (
            (matrix[2][1] - matrix[1][2]) / scale,
            0.25 * scale,
            (matrix[0][1] + matrix[1][0]) / scale,
            (matrix[0][2] + matrix[2][0]) / scale,
        )
    elif matrix[1][1] > matrix[2][2]:
        scale = math.sqrt(1.0 + matrix[1][1] - matrix[0][0] - matrix[2][2]) * 2
        quaternion = (
            (matrix[0][2] - matrix[2][0]) / scale,
            (matrix[0][1] + matrix[1][0]) / scale,
            0.25 * scale,
            (matrix[1][2] + matrix[2][1]) / scale,
        )
    else:
        scale = math.sqrt(1.0 + matrix[2][2] - matrix[0][0] - matrix[1][1]) * 2
        quaternion = (
            (matrix[1][0] - matrix[0][1]) / scale,
            (matrix[0][2] + matrix[2][0]) / scale,
            (matrix[1][2] + matrix[2][1]) / scale,
            0.25 * scale,
        )
    norm = math.sqrt(sum(value * value for value in quaternion))
    normalized = tuple(float(value / norm) for value in quaternion)
    if normalized[0] < 0:
        normalized = tuple(-value for value in normalized)
    return normalized


def _normalize(vector: Vector3) -> Vector3:
    norm = math.sqrt(_dot(vector, vector))
    if norm <= 1e-12:
        raise ValueError("cannot normalize a zero-length vector")
    return tuple(float(value / norm) for value in vector)


def _dot(left: Sequence[float], right: Sequence[float]) -> float:
    return float(sum(a * b for a, b in zip(left, right, strict=True)))


def _cross(left: Vector3, right: Vector3) -> Vector3:
    return (
        left[1] * right[2] - left[2] * right[1],
        left[2] * right[0] - left[0] * right[2],
        left[0] * right[1] - left[1] * right[0],
    )


def _scale(vector: Sequence[float], scalar: float) -> Vector3:
    return tuple(float(scalar * value) for value in vector)


def _add(*vectors: Sequence[float]) -> Vector3:
    return tuple(float(sum(values)) for values in zip(*vectors, strict=True))


def _subtract(left: Sequence[float], right: Sequence[float]) -> Vector3:
    return tuple(float(a - b) for a, b in zip(left, right, strict=True))


def _unique_values(values: Sequence[float]) -> tuple[float, ...]:
    unique = []
    for value in values:
        if not any(math.isclose(value, other, abs_tol=1e-12) for other in unique):
            unique.append(float(value))
    return tuple(unique)
