from __future__ import annotations

from dataclasses import dataclass, replace
import math
from typing import Any, Mapping, Sequence

from .expert import profile_grasp_yaw
from .randomization import ParcelSample


@dataclass(frozen=True)
class GraspPoseCandidate:
    candidate_id: str
    target_position: tuple[float, float, float]
    target_quaternion: tuple[float, float, float, float]
    longitudinal_offset_m: float
    vertical_offset_m: float
    wrist_variant: str
    approach_variant: str
    approach_direction: tuple[float, float, float]


IK_POSITION_TOLERANCE_M = 0.005
IK_ROTATION_TOLERANCE_RAD = 0.05
FK_POSITION_TOLERANCE_M = 0.005
STATE_RESTORE_TOLERANCE = 1e-7
MIN_VERTICAL_SIDE_OVERLAP_M = 0.020


def box_requires_geometry_aware_grasp_planning(
    sample: ParcelSample,
    *,
    hand_clearance_m: float,
    min_vertical_side_overlap_m: float = MIN_VERTICAL_SIDE_OVERLAP_M,
) -> bool:
    """Scope planning to boxes whose height reaches the palm-risk envelope."""
    if sample.shape != "box" or sample.dimensions_m is None:
        return False
    if hand_clearance_m <= 0 or min_vertical_side_overlap_m <= 0:
        raise ValueError("grasp-planning geometry thresholds must be positive")
    return sample.dimensions_m[2] >= (
        hand_clearance_m + min_vertical_side_overlap_m
    )


def interpolate_joint_segment(
    start_qpos: Sequence[float],
    goal_qpos: Sequence[float],
    *,
    max_joint_delta_rad: float,
    arm_dofs: int = 7,
) -> tuple[tuple[float, ...], ...]:
    """Return endpoint-inclusive linear joint samples for swept collision checks."""
    if len(start_qpos) != len(goal_qpos) or len(start_qpos) < arm_dofs:
        raise ValueError("joint segments require equally sized arm configurations")
    if arm_dofs < 1 or max_joint_delta_rad <= 0:
        raise ValueError("joint interpolation limits must be positive")
    maximum_delta = max(
        abs(float(goal_qpos[index]) - float(start_qpos[index]))
        for index in range(arm_dofs)
    )
    steps = max(1, int(math.ceil(maximum_delta / max_joint_delta_rad)))
    return tuple(
        tuple(
            float(start + (goal - start) * step / steps)
            for start, goal in zip(start_qpos, goal_qpos, strict=True)
        )
        for step in range(1, steps + 1)
    )


def generate_box_grasp_pose_candidates(
    sample: ParcelSample,
    parcel_pose: tuple[float, ...],
    *,
    hand_clearance_m: float,
    max_longitudinal_offset_m: float = 0.050,
    min_longitudinal_edge_margin_m: float = 0.060,
    max_vertical_offset_m: float = 0.055,
    min_vertical_side_overlap_m: float = MIN_VERTICAL_SIDE_OVERLAP_M,
    include_symmetric_wrist: bool = True,
) -> tuple[GraspPoseCandidate, ...]:
    """Generate auditable side-grasp poses for a yaw-oriented rigid box."""
    if sample.shape != "box" or sample.dimensions_m is None:
        raise ValueError("box grasp-pose generation requires box dimensions")
    if min(
        hand_clearance_m,
        min_longitudinal_edge_margin_m,
        min_vertical_side_overlap_m,
    ) <= 0:
        raise ValueError("grasp clearances and overlap must be positive")
    if max_longitudinal_offset_m < 0 or max_vertical_offset_m < 0:
        raise ValueError("grasp-pose offset limits cannot be negative")

    length_m, _, height_m = sample.dimensions_m
    available_longitudinal_offset = max(
        0.0,
        length_m / 2 - min_longitudinal_edge_margin_m,
    )
    longitudinal_extent = min(
        max_longitudinal_offset_m,
        available_longitudinal_offset,
    )
    longitudinal_offsets = _unique_values(
        (-longitudinal_extent, 0.0, longitudinal_extent)
    )

    available_vertical_offset = max(
        0.0,
        height_m / 2 - min_vertical_side_overlap_m,
    )
    vertical_extent = min(max_vertical_offset_m, available_vertical_offset)
    vertical_offsets = _unique_values(
        (
            0.0,
            min(0.020, vertical_extent),
            min(0.040, vertical_extent),
            vertical_extent,
        )
    )

    parcel_yaw = _yaw_from_pose(parcel_pose)
    base_yaw = profile_grasp_yaw(replace(sample, yaw_rad=parcel_yaw))
    variants = [("canonical", base_yaw)]
    if include_symmetric_wrist:
        variants.append(("symmetric_pi", base_yaw + math.pi))
    cos_yaw = math.cos(parcel_yaw)
    sin_yaw = math.sin(parcel_yaw)
    candidates = []
    for wrist_variant, grasp_yaw in variants:
        half_yaw = grasp_yaw / 2
        quaternion = (0.0, math.cos(half_yaw), math.sin(half_yaw), 0.0)
        for longitudinal_offset in longitudinal_offsets:
            x = parcel_pose[0] + longitudinal_offset * cos_yaw
            y = parcel_pose[1] + longitudinal_offset * sin_yaw
            for vertical_offset in vertical_offsets:
                candidate_id = (
                    f"{wrist_variant}-long-{longitudinal_offset:+.3f}"
                    f"-up-{vertical_offset:.3f}"
                )
                candidates.append(
                    GraspPoseCandidate(
                        candidate_id=candidate_id,
                        target_position=(
                            float(x),
                            float(y),
                            float(parcel_pose[2] + hand_clearance_m + vertical_offset),
                        ),
                        target_quaternion=quaternion,
                        longitudinal_offset_m=longitudinal_offset,
                        vertical_offset_m=vertical_offset,
                        wrist_variant=wrist_variant,
                        approach_variant="top_down",
                        approach_direction=(0.0, 0.0, -1.0),
                    )
                )
    return tuple(candidates)


def generate_box_side_grasp_pose_candidates(
    sample: ParcelSample,
    parcel_pose: tuple[float, ...],
    *,
    hand_clearance_m: float,
    palm_edge_margin_m: float = 0.065,
    min_longitudinal_edge_margin_m: float = 0.035,
    max_vertical_offset_m: float = 0.055,
    min_vertical_side_overlap_m: float = MIN_VERTICAL_SIDE_OVERLAP_M,
) -> tuple[GraspPoseCandidate, ...]:
    """Generate long-axis side approaches with the palm outside the box.

    The hand z-axis points from an end face toward the box centre while the
    finger-opening axis remains parallel to the box minor axis. Contact is
    shifted only as far from the centre as needed to keep the palm outside the
    end face, preserving moment-arm margin for long parcels.
    """
    if sample.shape != "box" or sample.dimensions_m is None:
        raise ValueError("box side-grasp generation requires box dimensions")
    if min(
        hand_clearance_m,
        palm_edge_margin_m,
        min_longitudinal_edge_margin_m,
        min_vertical_side_overlap_m,
    ) <= 0:
        raise ValueError("side-grasp clearances and margins must be positive")
    if max_vertical_offset_m < 0:
        raise ValueError("side-grasp vertical offset limit cannot be negative")

    length_m, _, height_m = sample.dimensions_m
    half_length_m = length_m / 2
    if half_length_m + 1e-12 < min_longitudinal_edge_margin_m:
        return ()
    contact_offset_m = max(
        0.0,
        half_length_m - hand_clearance_m + palm_edge_margin_m,
    )
    available_contact_offset_m = max(
        0.0,
        half_length_m - min_longitudinal_edge_margin_m,
    )
    if contact_offset_m > available_contact_offset_m + 1e-12:
        return ()

    available_vertical_offset_m = max(
        0.0,
        height_m / 2 - min_vertical_side_overlap_m,
    )
    vertical_extent_m = min(
        max_vertical_offset_m,
        available_vertical_offset_m,
    )
    vertical_offsets_m = _unique_values(
        (
            0.0,
            min(0.020, vertical_extent_m),
            min(0.040, vertical_extent_m),
            vertical_extent_m,
        )
    )

    parcel_yaw = _yaw_from_pose(parcel_pose)
    longitudinal_axis = (math.cos(parcel_yaw), math.sin(parcel_yaw), 0.0)
    minor_axis = (-math.sin(parcel_yaw), math.cos(parcel_yaw), 0.0)
    candidates = []
    for side_sign, side_name in ((1.0, "positive_long"), (-1.0, "negative_long")):
        approach_direction = tuple(
            -side_sign * value for value in longitudinal_axis
        )
        local_y_axis = tuple(side_sign * value for value in minor_axis)
        quaternion = _quaternion_from_rotation_columns(
            (0.0, 0.0, 1.0),
            local_y_axis,
            approach_direction,
        )
        signed_contact_offset_m = side_sign * contact_offset_m
        contact_x = parcel_pose[0] + signed_contact_offset_m * longitudinal_axis[0]
        contact_y = parcel_pose[1] + signed_contact_offset_m * longitudinal_axis[1]
        for vertical_offset_m in vertical_offsets_m:
            candidate_id = (
                f"side-{side_name}-long-{signed_contact_offset_m:+.3f}"
                f"-up-{vertical_offset_m:.3f}"
            )
            candidates.append(
                GraspPoseCandidate(
                    candidate_id=candidate_id,
                    target_position=(
                        float(
                            contact_x
                            - hand_clearance_m * approach_direction[0]
                        ),
                        float(
                            contact_y
                            - hand_clearance_m * approach_direction[1]
                        ),
                        float(parcel_pose[2] + vertical_offset_m),
                    ),
                    target_quaternion=quaternion,
                    longitudinal_offset_m=signed_contact_offset_m,
                    vertical_offset_m=vertical_offset_m,
                    wrist_variant=side_name,
                    approach_variant="side_long_axis",
                    approach_direction=approach_direction,
                )
            )
    return tuple(candidates)


def generate_box_oblique_grasp_pose_candidates(
    sample: ParcelSample,
    parcel_pose: tuple[float, ...],
    *,
    hand_clearance_m: float,
    tilt_angles_deg: tuple[float, ...] = (30.0, 45.0),
    max_vertical_offset_m: float = 0.020,
    min_vertical_side_overlap_m: float = MIN_VERTICAL_SIDE_OVERLAP_M,
) -> tuple[GraspPoseCandidate, ...]:
    """Generate centred grasps whose palm tilts toward either long-axis end."""
    if sample.shape != "box" or sample.dimensions_m is None:
        raise ValueError("box oblique-grasp generation requires box dimensions")
    if hand_clearance_m <= 0 or min_vertical_side_overlap_m <= 0:
        raise ValueError("oblique-grasp clearances must be positive")
    if max_vertical_offset_m < 0:
        raise ValueError("oblique-grasp vertical offset limit cannot be negative")
    if not tilt_angles_deg or any(
        not math.isfinite(angle) or not 0 < angle < 90
        for angle in tilt_angles_deg
    ):
        raise ValueError("oblique-grasp tilt angles must be finite and in (0, 90)")

    height_m = sample.dimensions_m[2]
    available_vertical_offset_m = max(
        0.0,
        height_m / 2 - min_vertical_side_overlap_m,
    )
    vertical_extent_m = min(
        max_vertical_offset_m,
        available_vertical_offset_m,
    )
    vertical_offsets_m = _unique_values((0.0, vertical_extent_m))

    parcel_yaw = _yaw_from_pose(parcel_pose)
    longitudinal_axis = (math.cos(parcel_yaw), math.sin(parcel_yaw), 0.0)
    minor_axis = (-math.sin(parcel_yaw), math.cos(parcel_yaw), 0.0)
    local_y_axis = tuple(-value for value in minor_axis)
    candidates = []
    for tilt_angle_deg in tilt_angles_deg:
        angle_rad = math.radians(tilt_angle_deg)
        vertical_component = math.cos(angle_rad)
        horizontal_component = math.sin(angle_rad)
        for side_sign, side_name in ((1.0, "positive_long"), (-1.0, "negative_long")):
            approach_direction = (
                -side_sign * horizontal_component * longitudinal_axis[0],
                -side_sign * horizontal_component * longitudinal_axis[1],
                -vertical_component,
            )
            local_x_axis = _cross(local_y_axis, approach_direction)
            quaternion = _quaternion_from_rotation_columns(
                local_x_axis,
                local_y_axis,
                approach_direction,
            )
            for vertical_offset_m in vertical_offsets_m:
                target_position = (
                    float(
                        parcel_pose[0]
                        - hand_clearance_m * approach_direction[0]
                    ),
                    float(
                        parcel_pose[1]
                        - hand_clearance_m * approach_direction[1]
                    ),
                    float(
                        parcel_pose[2]
                        + vertical_offset_m
                        - hand_clearance_m * approach_direction[2]
                    ),
                )
                candidate_id = (
                    f"oblique-{side_name}-tilt-{tilt_angle_deg:.0f}"
                    f"-up-{vertical_offset_m:.3f}"
                )
                candidates.append(
                    GraspPoseCandidate(
                        candidate_id=candidate_id,
                        target_position=target_position,
                        target_quaternion=quaternion,
                        longitudinal_offset_m=0.0,
                        vertical_offset_m=vertical_offset_m,
                        wrist_variant=(
                            f"oblique_{side_name}_{tilt_angle_deg:.0f}deg"
                        ),
                        approach_variant="oblique_top_down",
                        approach_direction=approach_direction,
                    )
                )
    return tuple(candidates)


def grasp_evaluation_is_feasible(
    evaluation: Mapping[str, Any],
    *,
    collision_filter_enabled: bool = True,
) -> bool:
    """Apply the preregistered IK, state-restoration, and collision gates."""
    kinematically_feasible = (
        bool(evaluation["finite"])
        and float(evaluation["ik_position_error_m"]) <= IK_POSITION_TOLERANCE_M
        and float(evaluation["ik_rotation_error_rad"]) <= IK_ROTATION_TOLERANCE_RAD
        and float(evaluation["fk_position_error_m"]) <= FK_POSITION_TOLERANCE_M
        and float(evaluation["restore_max_abs_error"]) <= STATE_RESTORE_TOLERANCE
    )
    return kinematically_feasible and (
        not collision_filter_enabled
        or int(evaluation["disallowed_collision_count"]) == 0
    )


def grasp_evaluation_rank_key(
    evaluation: Mapping[str, Any],
    *,
    collision_filter_enabled: bool = True,
    manipulability_ranking_enabled: bool = True,
) -> tuple[Any, ...]:
    """Rank feasible poses without letting sub-threshold IK noise dominate.

    Errors are converted to pass/fail buckets. Once a solution is inside every
    kinematic tolerance, a centered low side-contact prior, joint travel,
    manipulability, and clearance determine the order rather than meaningless
    1e-6-scale solver differences.
    """
    feasible = grasp_evaluation_is_feasible(
        evaluation,
        collision_filter_enabled=collision_filter_enabled,
    )
    position_bucket = _error_bucket(
        float(evaluation["ik_position_error_m"]),
        IK_POSITION_TOLERANCE_M,
    )
    rotation_bucket = _error_bucket(
        float(evaluation["ik_rotation_error_rad"]),
        IK_ROTATION_TOLERANCE_RAD,
    )
    fk_bucket = _error_bucket(
        float(evaluation["fk_position_error_m"]),
        FK_POSITION_TOLERANCE_M,
    )
    collision_count = (
        int(evaluation["disallowed_collision_count"])
        if collision_filter_enabled
        else 0
    )
    clearance_m = (
        float(evaluation.get("nonfinger_clearance_m", 0.0))
        if collision_filter_enabled
        else 0.0
    )
    minimum_singular_value = (
        float(evaluation["minimum_singular_value"])
        if manipulability_ranking_enabled
        else 0.0
    )
    symmetric_wrist_fallback = (
        str(evaluation.get("wrist_variant", "canonical")) != "canonical"
    )
    longitudinal_offset_m = abs(
        float(evaluation.get("longitudinal_offset_m", 0.0))
    )
    vertical_offset_m = float(evaluation.get("vertical_offset_m", 0.0))
    return (
        not feasible,
        collision_count,
        position_bucket,
        rotation_bucket,
        fk_bucket,
        symmetric_wrist_fallback,
        longitudinal_offset_m,
        vertical_offset_m,
        float(evaluation["joint_distance_rad"]),
        -minimum_singular_value,
        -clearance_m,
        str(evaluation["candidate_id"]),
        str(evaluation["seed_name"]),
    )


def rank_grasp_pose_evaluations(
    evaluations: Sequence[Mapping[str, Any]],
    *,
    collision_filter_enabled: bool = True,
    manipulability_ranking_enabled: bool = True,
) -> list[Mapping[str, Any]]:
    return sorted(
        evaluations,
        key=lambda evaluation: grasp_evaluation_rank_key(
            evaluation,
            collision_filter_enabled=collision_filter_enabled,
            manipulability_ranking_enabled=manipulability_ranking_enabled,
        ),
    )


def select_grasp_pose_evaluation(
    evaluations: Sequence[Mapping[str, Any]],
    *,
    rejected_candidate_ids: frozenset[str] = frozenset(),
    collision_filter_enabled: bool = True,
    manipulability_ranking_enabled: bool = True,
) -> Mapping[str, Any] | None:
    ranked = rank_grasp_pose_evaluations(
        evaluations,
        collision_filter_enabled=collision_filter_enabled,
        manipulability_ranking_enabled=manipulability_ranking_enabled,
    )
    return next(
        (
            evaluation
            for evaluation in ranked
            if str(evaluation["candidate_id"]) not in rejected_candidate_ids
            and grasp_evaluation_is_feasible(
                evaluation,
                collision_filter_enabled=collision_filter_enabled,
            )
        ),
        None,
    )


def rejected_candidates_after_retry(
    rejected_candidate_ids: set[str],
    selected_evaluation: Mapping[str, Any] | None,
    *,
    retry_changed: bool,
    blacklist_failed_candidate_enabled: bool,
) -> set[str]:
    """Return the next retry blacklist without changing default replanning."""
    if not retry_changed:
        return set(rejected_candidate_ids)
    if not blacklist_failed_candidate_enabled:
        return set()
    updated = set(rejected_candidate_ids)
    if selected_evaluation is not None:
        updated.add(str(selected_evaluation["candidate_id"]))
    return updated


def effective_rejected_candidate_ids(
    generated_candidate_ids: Sequence[str],
    rejected_candidate_ids: set[str] | frozenset[str],
    diagnostic_allowlist: frozenset[str] | None = None,
) -> frozenset[str]:
    """Combine runtime rejection with an optional diagnostic-only allowlist."""
    effective = set(rejected_candidate_ids)
    if diagnostic_allowlist is not None:
        effective.update(
            str(candidate_id)
            for candidate_id in generated_candidate_ids
            if str(candidate_id) not in diagnostic_allowlist
        )
    return frozenset(effective)


def _error_bucket(error: float, tolerance: float) -> int:
    if not math.isfinite(error):
        return 2**31 - 1
    if error <= tolerance:
        return 0
    return int(math.ceil(error / tolerance))


def _unique_values(values: tuple[float, ...]) -> tuple[float, ...]:
    unique = []
    for value in values:
        if not any(math.isclose(value, other, abs_tol=1e-12) for other in unique):
            unique.append(float(value))
    return tuple(unique)


def _quaternion_from_rotation_columns(
    local_x_world: tuple[float, float, float],
    local_y_world: tuple[float, float, float],
    local_z_world: tuple[float, float, float],
) -> tuple[float, float, float, float]:
    """Convert orthonormal world-frame axis columns to a normalized wxyz quaternion."""
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


def _cross(
    left: tuple[float, float, float],
    right: tuple[float, float, float],
) -> tuple[float, float, float]:
    return (
        left[1] * right[2] - left[2] * right[1],
        left[2] * right[0] - left[0] * right[2],
        left[0] * right[1] - left[1] * right[0],
    )


def _yaw_from_pose(pose: tuple[float, ...]) -> float:
    if len(pose) < 7:
        raise ValueError("parcel pose must contain xyz and a wxyz quaternion")
    w, x, y, z = pose[3:7]
    return math.atan2(
        2.0 * (w * z + x * y),
        1.0 - 2.0 * (y * y + z * z),
    )
