from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass
import math
from pathlib import Path
import time
from typing import Any, Mapping
import xml.etree.ElementTree as ET

from .config import ExperimentConfig
from .contact_branch import summarize_contact_branch_events
from .contact_wrench import (
    ContactPoint,
    ContactWrenchConfig,
    evaluate_contact_wrench,
    evaluate_contact_wrench_torch,
    summarize_contact_wrench_events,
)
from .contracts import CartesianAction, ControlDecision, Observation, RobotState
from .capabilities import require_supported_handling, runtime_supported_handling_classes
from .expert import ScriptedPickPlaceExpert
from .grasp_planning import (
    box_requires_geometry_aware_grasp_planning,
    effective_rejected_candidate_ids,
    grasp_evaluation_is_feasible,
    interpolate_joint_segment,
    rejected_candidates_after_retry,
)
from .randomization import ParcelSample
from .shape_grasp_planning import (
    ShapeGraspPlannerConfig,
    build_shape_grasp_plan,
    rank_shape_grasp_pose_evaluations,
    select_shape_grasp_pose_evaluation,
)
from .suction import (
    SuctionAttachment,
    compliant_suction_wrench,
    create_attachment,
    quaternion_conjugate,
    rotate_vector,
    tri_cup_offsets,
)


_INITIALIZED_BACKEND: str | None = None


def wrist_camera_pose(
    hand_position: tuple[float, float, float],
    hand_quaternion: tuple[float, float, float, float],
    np: Any,
) -> tuple[
    tuple[float, float, float],
    tuple[float, float, float],
    tuple[float, float, float],
]:
    """Return a close wrist-camera pose aligned with the Panda hand frame."""
    position = np.asarray(hand_position, dtype=np.float64)
    forward = np.asarray(
        rotate_vector(hand_quaternion, (0.0, 0.0, 1.0)), dtype=np.float64
    )
    up = np.asarray(
        rotate_vector(hand_quaternion, (0.0, 1.0, 0.0)), dtype=np.float64
    )
    forward /= np.linalg.norm(forward)
    up /= np.linalg.norm(up)
    camera_position = position - forward * 0.045 + up * 0.020
    lookat = position + forward * 0.180
    return (
        tuple(camera_position.tolist()),
        tuple(lookat.tolist()),
        tuple(up.tolist()),
    )


def combine_rigid_body_with_box_inertia(
    base_mass_kg: float,
    base_center_m: tuple[float, float, float],
    base_full_inertia_kg_m2: tuple[float, float, float, float, float, float],
    box_density_kg_m3: float,
    box_half_size_m: tuple[float, float, float],
    box_center_m: tuple[float, float, float],
) -> tuple[
    float,
    tuple[float, float, float],
    tuple[float, float, float, float, float, float],
]:
    """Combine a rigid body with a uniform box using the parallel-axis theorem."""
    values = (
        base_mass_kg,
        *base_center_m,
        *base_full_inertia_kg_m2,
        box_density_kg_m3,
        *box_half_size_m,
        *box_center_m,
    )
    if any(not math.isfinite(value) for value in values):
        raise ValueError("rigid-body inertia inputs must be finite")
    if base_mass_kg <= 0 or box_density_kg_m3 <= 0:
        raise ValueError("rigid-body masses and density must be positive")
    if any(value <= 0 for value in box_half_size_m):
        raise ValueError("box half-sizes must be positive")

    box_size_m = tuple(2.0 * value for value in box_half_size_m)
    box_mass_kg = box_density_kg_m3 * math.prod(box_size_m)
    total_mass_kg = base_mass_kg + box_mass_kg
    center_m = tuple(
        (
            base_mass_kg * base_center_m[axis]
            + box_mass_kg * box_center_m[axis]
        )
        / total_mass_kg
        for axis in range(3)
    )

    base_matrix = _full_inertia_matrix(base_full_inertia_kg_m2)
    dx, dy, dz = box_size_m
    box_matrix = [
        [box_mass_kg * (dy * dy + dz * dz) / 12.0, 0.0, 0.0],
        [0.0, box_mass_kg * (dx * dx + dz * dz) / 12.0, 0.0],
        [0.0, 0.0, box_mass_kg * (dx * dx + dy * dy) / 12.0],
    ]
    combined = _shift_inertia_matrix(
        base_matrix,
        base_mass_kg,
        tuple(value - center_m[axis] for axis, value in enumerate(base_center_m)),
    )
    shifted_box = _shift_inertia_matrix(
        box_matrix,
        box_mass_kg,
        tuple(value - center_m[axis] for axis, value in enumerate(box_center_m)),
    )
    for row in range(3):
        for column in range(3):
            combined[row][column] += shifted_box[row][column]
    full_inertia = (
        combined[0][0],
        combined[1][1],
        combined[2][2],
        combined[0][1],
        combined[0][2],
        combined[1][2],
    )
    return total_mass_kg, center_m, full_inertia


def combine_rigid_body_with_cylinders_inertia(
    base_mass_kg: float,
    base_center_m: tuple[float, float, float],
    base_full_inertia_kg_m2: tuple[float, float, float, float, float, float],
    cylinder_density_kg_m3: float,
    cylinder_radius_m: float,
    cylinder_length_m: float,
    cylinder_centers_m: tuple[tuple[float, float, float], ...],
) -> tuple[
    float,
    tuple[float, float, float],
    tuple[float, float, float, float, float, float],
]:
    """Combine a rigid body with parallel solid cylinders along local Z."""

    values = (
        base_mass_kg,
        *base_center_m,
        *base_full_inertia_kg_m2,
        cylinder_density_kg_m3,
        cylinder_radius_m,
        cylinder_length_m,
        *(value for center in cylinder_centers_m for value in center),
    )
    if any(not math.isfinite(value) for value in values):
        raise ValueError("cylinder inertia inputs must be finite")
    if (
        base_mass_kg <= 0
        or cylinder_density_kg_m3 <= 0
        or cylinder_radius_m <= 0
        or cylinder_length_m <= 0
        or not cylinder_centers_m
    ):
        raise ValueError("cylinder inertia masses, dimensions, and centers are required")

    cylinder_mass_kg = (
        cylinder_density_kg_m3
        * math.pi
        * cylinder_radius_m**2
        * cylinder_length_m
    )
    total_mass_kg = base_mass_kg + cylinder_mass_kg * len(cylinder_centers_m)
    center_m = tuple(
        (
            base_mass_kg * base_center_m[axis]
            + cylinder_mass_kg * sum(center[axis] for center in cylinder_centers_m)
        )
        / total_mass_kg
        for axis in range(3)
    )
    combined = _shift_inertia_matrix(
        _full_inertia_matrix(base_full_inertia_kg_m2),
        base_mass_kg,
        tuple(value - center_m[axis] for axis, value in enumerate(base_center_m)),
    )
    radial_inertia = cylinder_mass_kg * (
        3.0 * cylinder_radius_m**2 + cylinder_length_m**2
    ) / 12.0
    axial_inertia = cylinder_mass_kg * cylinder_radius_m**2 / 2.0
    cylinder_matrix = [
        [radial_inertia, 0.0, 0.0],
        [0.0, radial_inertia, 0.0],
        [0.0, 0.0, axial_inertia],
    ]
    for cylinder_center in cylinder_centers_m:
        shifted = _shift_inertia_matrix(
            cylinder_matrix,
            cylinder_mass_kg,
            tuple(
                value - center_m[axis]
                for axis, value in enumerate(cylinder_center)
            ),
        )
        for row in range(3):
            for column in range(3):
                combined[row][column] += shifted[row][column]
    return (
        total_mass_kg,
        center_m,
        (
            combined[0][0],
            combined[1][1],
            combined[2][2],
            combined[0][1],
            combined[0][2],
            combined[1][2],
        ),
    )


def _full_inertia_matrix(
    inertia: tuple[float, float, float, float, float, float],
) -> list[list[float]]:
    ixx, iyy, izz, ixy, ixz, iyz = inertia
    return [
        [ixx, ixy, ixz],
        [ixy, iyy, iyz],
        [ixz, iyz, izz],
    ]


def _shift_inertia_matrix(
    inertia: list[list[float]],
    mass_kg: float,
    offset_m: tuple[float, float, float],
) -> list[list[float]]:
    squared_norm = sum(value * value for value in offset_m)
    return [
        [
            inertia[row][column]
            + mass_kg
            * (
                (squared_norm if row == column else 0.0)
                - offset_m[row] * offset_m[column]
            )
            for column in range(3)
        ]
        for row in range(3)
    ]


def _float_triplet(value: str, name: str) -> tuple[float, float, float]:
    parsed = tuple(float(item) for item in value.split())
    if len(parsed) != 3 or any(not math.isfinite(item) for item in parsed):
        raise ValueError(f"{name} must contain three finite values")
    return parsed


def build_parcel_gripper_mjcf(
    source_path: str | Path,
    output_path: str | Path,
    extension_m: float,
    density_kg_m3: float = 1240.0,
    combine_adapter_inertia: bool = True,
) -> Path:
    """Generate a Panda MJCF with explicit, versioned parcel finger adapters."""
    if not math.isfinite(extension_m) or not 0.005 <= extension_m <= 0.060:
        raise ValueError("parcel gripper extension must be in [0.005, 0.060] m")
    if not math.isfinite(density_kg_m3) or not 100.0 <= density_kg_m3 <= 2500.0:
        raise ValueError("parcel gripper density must be in [100, 2500] kg/m^3")
    source = Path(source_path).resolve()
    output = Path(output_path).resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Panda MJCF source does not exist: {source}")
    mesh_directory = source.parent / "assets"
    if not mesh_directory.is_dir():
        raise FileNotFoundError(f"Panda MJCF mesh directory does not exist: {mesh_directory}")

    tree = ET.parse(source)
    root = tree.getroot()
    compiler = root.find("compiler")
    if compiler is None:
        raise ValueError("Panda MJCF is missing its compiler element")
    compiler.set("meshdir", str(mesh_directory))

    half_extension = extension_m / 2.0
    stock_tip_end_m = 0.053
    center_z_m = stock_tip_end_m + half_extension
    size = f"0.010 0.004 {half_extension:.9f}"
    position = f"0 0.0055 {center_z_m:.9f}"
    for finger_name in ("left_finger", "right_finger"):
        finger = root.find(f".//body[@name='{finger_name}']")
        if finger is None:
            raise ValueError(f"Panda MJCF is missing {finger_name}")
        if combine_adapter_inertia:
            inertial = finger.find("inertial")
            if inertial is None:
                raise ValueError(f"Panda MJCF {finger_name} is missing inertial data")
            if "diaginertia" not in inertial.attrib:
                raise ValueError(
                    f"Panda MJCF {finger_name} must use explicit diaginertia"
                )
            base_mass_kg = float(inertial.attrib["mass"])
            base_center_m = _float_triplet(inertial.attrib["pos"], "inertial pos")
            diagonal = _float_triplet(
                inertial.attrib["diaginertia"],
                "inertial diaginertia",
            )
            combined_mass_kg, combined_center_m, combined_inertia = (
                combine_rigid_body_with_box_inertia(
                    base_mass_kg,
                    base_center_m,
                    (*diagonal, 0.0, 0.0, 0.0),
                    density_kg_m3,
                    (0.010, 0.004, half_extension),
                    (0.0, 0.0055, center_z_m),
                )
            )
            inertial.set("mass", f"{combined_mass_kg:.12g}")
            inertial.set(
                "pos",
                " ".join(f"{value:.12g}" for value in combined_center_m),
            )
            inertial.attrib.pop("diaginertia")
            inertial.set(
                "fullinertia",
                " ".join(f"{value:.12g}" for value in combined_inertia),
            )
        ET.SubElement(
            finger,
            "geom",
            {
                "name": f"{finger_name}_parcel_adapter_collision",
                "type": "box",
                "size": size,
                "pos": position,
                "group": "3",
            },
        )
        ET.SubElement(
            finger,
            "geom",
            {
                "name": f"{finger_name}_parcel_adapter_visual",
                "type": "box",
                "size": size,
                "pos": position,
                "group": "2",
                "contype": "0",
                "conaffinity": "0",
                "rgba": "0.05 0.60 0.72 1",
            },
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    tree.write(output, encoding="utf-8", xml_declaration=True)
    return output


def build_tri_suction_mjcf(
    source_path: str | Path,
    output_path: str | Path,
    *,
    cup_radius_m: float,
    footprint_radius_m: float,
    cup_length_m: float,
    tip_offset_m: float,
    density_kg_m3: float,
) -> Path:
    """Generate a Panda MJCF with three physical suction cups on the hand."""

    source = Path(source_path).resolve()
    output = Path(output_path).resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Panda MJCF source does not exist: {source}")
    offsets = tri_cup_offsets(footprint_radius_m)
    if not 0.004 <= cup_radius_m <= 0.030:
        raise ValueError("suction cup radius must be in [0.004, 0.030] m")
    if not 0.004 <= cup_length_m <= 0.030:
        raise ValueError("suction cup length must be in [0.004, 0.030] m")
    if not 0.060 <= tip_offset_m <= 0.160:
        raise ValueError("suction tip offset must be in [0.060, 0.160] m")
    if not 100.0 <= density_kg_m3 <= 2500.0:
        raise ValueError("suction density must be in [100, 2500] kg/m^3")

    tree = ET.parse(source)
    root = tree.getroot()
    compiler = root.find("compiler")
    if compiler is None:
        raise ValueError("Panda MJCF is missing its compiler element")
    mesh_directory = source.parent / "assets"
    if not mesh_directory.is_dir():
        raise FileNotFoundError(f"Panda MJCF mesh directory does not exist: {mesh_directory}")
    compiler.set("meshdir", str(mesh_directory))
    hand = root.find(".//body[@name='hand']")
    if hand is None:
        raise ValueError("Panda MJCF is missing hand")
    inertial = hand.find("inertial")
    if inertial is None or "diaginertia" not in inertial.attrib:
        raise ValueError("Panda MJCF hand requires explicit diagonal inertia")

    center_z_m = tip_offset_m + cup_length_m / 2.0
    centers = tuple((x, y, center_z_m) for x, y, _ in offsets)
    base_mass_kg = float(inertial.attrib["mass"])
    base_center_m = _float_triplet(inertial.attrib["pos"], "hand inertial pos")
    diagonal = _float_triplet(
        inertial.attrib["diaginertia"],
        "hand inertial diaginertia",
    )
    combined_mass, combined_center, combined_inertia = (
        combine_rigid_body_with_cylinders_inertia(
            base_mass_kg,
            base_center_m,
            (*diagonal, 0.0, 0.0, 0.0),
            density_kg_m3,
            cup_radius_m,
            cup_length_m,
            centers,
        )
    )
    inertial.set("mass", f"{combined_mass:.12g}")
    inertial.set("pos", " ".join(f"{value:.12g}" for value in combined_center))
    inertial.attrib.pop("diaginertia")
    inertial.set(
        "fullinertia",
        " ".join(f"{value:.12g}" for value in combined_inertia),
    )
    size = f"{cup_radius_m:.9f} {cup_length_m / 2.0:.9f}"
    for index, center in enumerate(centers):
        position = " ".join(f"{value:.9f}" for value in center)
        ET.SubElement(
            hand,
            "geom",
            {
                "name": f"suction_cup_{index}_collision",
                "type": "cylinder",
                "size": size,
                "pos": position,
                "group": "3",
            },
        )
        ET.SubElement(
            hand,
            "geom",
            {
                "name": f"suction_cup_{index}_visual",
                "type": "cylinder",
                "size": size,
                "pos": position,
                "group": "2",
                "contype": "0",
                "conaffinity": "0",
                "rgba": "0.08 0.70 0.34 1",
            },
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    tree.write(output, encoding="utf-8", xml_declaration=True)
    return output


def aabb_gap_m(first_aabb: Any, second_aabb: Any) -> float:
    """Return Euclidean separation between two world-space AABBs in metres."""
    first = first_aabb
    second = second_aabb
    if len(first) != 2 or len(second) != 2:
        raise ValueError("AABBs must contain min and max corners")
    if any(len(corner) != 3 for corner in (*first, *second)):
        raise ValueError("AABB corners must contain three coordinates")
    gap = []
    for axis in range(3):
        gap.append(
            max(
                0.0,
                float(first[0][axis]) - float(second[1][axis]),
                float(second[0][axis]) - float(first[1][axis]),
            )
        )
    return math.sqrt(sum(value * value for value in gap))


def cross_entity_collision_pairs(
    collision_pairs: Any,
    first_geom_range: tuple[int, int],
    second_geom_range: tuple[int, int],
) -> tuple[tuple[int, int], ...]:
    """Filter unordered collision pairs to two entity geometry ranges."""
    first_start, first_end = first_geom_range
    second_start, second_end = second_geom_range
    matches = []
    seen = set()
    for pair in collision_pairs:
        geom_a, geom_b = (int(value) for value in pair)
        match = None
        if first_start <= geom_a < first_end and second_start <= geom_b < second_end:
            match = (geom_a, geom_b)
        elif second_start <= geom_a < second_end and first_start <= geom_b < first_end:
            match = (geom_b, geom_a)
        if match is not None and match not in seen:
            seen.add(match)
            matches.append(match)
    return tuple(matches)


def resolve_geometry_grasp_planning_active(
    *,
    planning_enabled: bool,
    geometry_eligible: bool,
    reset_fallback_gate_enabled: bool,
    reset_fallback_used: bool,
) -> bool:
    """Resolve planner activation from static scope and measured reset risk."""
    return (
        planning_enabled
        and geometry_eligible
        and (not reset_fallback_gate_enabled or reset_fallback_used)
    )


def scaled_robot_gains(
    arm_kp: tuple[float, ...],
    arm_kv: tuple[float, ...],
    finger_kp: float,
    finger_kv: float,
    stiffness_scale: float,
) -> tuple[tuple[float, ...], tuple[float, ...]]:
    """Scale arm stiffness while preserving its nominal damping relationship."""
    velocity_scale = math.sqrt(stiffness_scale)
    return (
        (*tuple(value * stiffness_scale for value in arm_kp), finger_kp, finger_kp),
        (*tuple(value * velocity_scale for value in arm_kv), finger_kv, finger_kv),
    )


def _limit_vector(values: tuple[float, ...], maximum_norm: float) -> tuple[float, ...]:
    norm = math.sqrt(sum(value * value for value in values))
    if norm <= maximum_norm or norm == 0.0:
        return values
    scale = maximum_norm / norm
    return tuple(value * scale for value in values)


def cartesian_velocity_twist(
    current_position: tuple[float, float, float],
    current_quaternion: tuple[float, float, float, float],
    target_position: tuple[float, float, float],
    target_quaternion: tuple[float, float, float, float],
    *,
    position_gain_s: float,
    orientation_gain_s: float,
    max_linear_m_s: float,
    max_angular_rad_s: float,
) -> tuple[float, float, float, float, float, float]:
    """Build a bounded world-frame twist from a Cartesian pose error.

    Genesis quaternions are ordered wxyz. The shortest quaternion arc avoids a
    discontinuity when equivalent quaternions have opposite signs.
    """
    linear = _limit_vector(
        tuple(
            (target - current) * position_gain_s
            for current, target in zip(current_position, target_position, strict=True)
        ),
        max_linear_m_s,
    )
    current_norm = math.sqrt(sum(value * value for value in current_quaternion))
    target_norm = math.sqrt(sum(value * value for value in target_quaternion))
    if current_norm == 0.0 or target_norm == 0.0:
        raise ValueError("Cartesian velocity control requires non-zero quaternions")
    cw, cx, cy, cz = (value / current_norm for value in current_quaternion)
    tw, tx, ty, tz = (value / target_norm for value in target_quaternion)
    # target * conjugate(current)
    error = (
        tw * cw + tx * cx + ty * cy + tz * cz,
        -tw * cx + tx * cw - ty * cz + tz * cy,
        -tw * cy + tx * cz + ty * cw - tz * cx,
        -tw * cz - tx * cy + ty * cx + tz * cw,
    )
    if error[0] < 0.0:
        error = tuple(-value for value in error)
    vector_norm = math.sqrt(sum(value * value for value in error[1:]))
    if vector_norm < 1e-12:
        angular = (0.0, 0.0, 0.0)
    else:
        angle = 2.0 * math.atan2(vector_norm, max(0.0, min(1.0, error[0])))
        angular = _limit_vector(
            tuple(value / vector_norm * angle * orientation_gain_s for value in error[1:]),
            max_angular_rad_s,
        )
    return (*linear, *angular)


def damped_least_squares_velocity(
    jacobian: Any,
    twist: Any,
    *,
    damping: float,
    max_joint_velocity: float,
    array_module: Any,
) -> Any:
    """Map a Cartesian twist to bounded joint velocity for NumPy or Torch arrays."""
    if tuple(jacobian.shape)[0] != 6 or tuple(twist.shape) != (6,):
        raise ValueError("expected a 6xN Jacobian and a six-element twist")
    if hasattr(jacobian, "new_zeros"):
        identity = jacobian.new_zeros((6, 6))
        identity.diagonal().fill_(1.0)
    else:
        identity = array_module.eye(6, dtype=jacobian.dtype)
    joint_velocity = jacobian.transpose(-2, -1) @ array_module.linalg.solve(
        jacobian @ jacobian.transpose(-2, -1) + identity * damping * damping,
        twist,
    )
    if hasattr(joint_velocity, "abs"):
        peak = joint_velocity.abs().max()
        scale = (joint_velocity.new_tensor(max_joint_velocity) / (peak + 1e-12)).clamp(max=1.0)
        return joint_velocity * scale
    peak = float(array_module.max(array_module.abs(joint_velocity)))
    if peak > max_joint_velocity:
        joint_velocity = joint_velocity * (max_joint_velocity / peak)
    return joint_velocity


@dataclass(frozen=True)
class ParcelSpawnSpec:
    shape: str
    dimensions_m: tuple[float, float, float]
    initial_z_m: float
    euler_degrees: tuple[float, float, float]
    cylinder_height_m: float | None = None
    cylinder_radius_m: float | None = None


PAYLOAD_TRANSPORT_PHASES = frozenset(
    {"raise", "raise_settle", "transfer", "transfer_settle"}
)


@dataclass(frozen=True)
class TransportSlipSignal:
    relative_delta_m: float
    downward_delta_m: float
    destination_distance_m: float
    contact_force_n: float
    triggered: bool


def detect_transport_slip(
    previous_relative_position_m: tuple[float, float, float] | None,
    state: RobotState,
    *,
    phase: str,
    relative_delta_threshold_m: float,
    downward_delta_threshold_m: float,
    min_contact_force_n: float,
    min_destination_distance_m: float,
) -> TransportSlipSignal | None:
    """Fuse relative motion, contact, and task phase into one slip signal."""
    if previous_relative_position_m is None:
        return None
    current_relative = tuple(
        float(ee - parcel)
        for ee, parcel in zip(
            state.end_effector_pose[:3],
            state.parcel_pose[:3],
            strict=True,
        )
    )
    relative_step = tuple(
        current - previous
        for current, previous in zip(
            current_relative,
            previous_relative_position_m,
            strict=True,
        )
    )
    relative_delta_m = math.sqrt(sum(value * value for value in relative_step))
    downward_delta_m = relative_step[2]
    destination_distance_m = math.hypot(
        state.end_effector_pose[0] - state.target_position[0],
        state.end_effector_pose[1] - state.target_position[1],
    )
    return TransportSlipSignal(
        relative_delta_m=relative_delta_m,
        downward_delta_m=downward_delta_m,
        destination_distance_m=destination_distance_m,
        contact_force_n=state.gripper_contact_force_n,
        triggered=(
            phase in PAYLOAD_TRANSPORT_PHASES
            and relative_delta_m >= relative_delta_threshold_m
            and downward_delta_m >= downward_delta_threshold_m
            and state.gripper_contact_force_n >= min_contact_force_n
            and destination_distance_m >= min_destination_distance_m
        ),
    )


def parcel_spawn_spec(config: ExperimentConfig, sample: ParcelSample) -> ParcelSpawnSpec:
    dimensions = sample.dimensions_m or tuple(
        base * scale
        for base, scale in zip(
            config.task.parcel_base_size_m,
            sample.size_scale_xyz,
            strict=True,
        )
    )
    yaw_degrees = math.degrees(sample.yaw_rad)
    if sample.shape == "box":
        return ParcelSpawnSpec(
            shape="box",
            dimensions_m=dimensions,
            initial_z_m=dimensions[2] / 2,
            euler_degrees=(0.0, 0.0, yaw_degrees),
        )
    if sample.shape != "cylinder":
        raise ValueError(f"unsupported parcel shape: {sample.shape}")
    if sample.orientation_mode == "upright":
        height, radius = dimensions[2], dimensions[0] / 2
        euler = (0.0, 0.0, yaw_degrees)
        initial_z = height / 2
    elif sample.orientation_mode == "horizontal":
        height, radius = dimensions[0], dimensions[1] / 2
        euler = (0.0, 90.0, yaw_degrees)
        initial_z = radius
    else:
        raise ValueError(f"unsupported cylinder orientation: {sample.orientation_mode}")
    return ParcelSpawnSpec(
        shape="cylinder",
        dimensions_m=dimensions,
        initial_z_m=initial_z,
        euler_degrees=euler,
        cylinder_height_m=height,
        cylinder_radius_m=radius,
    )


def genesis_depth_to_meters(depth: Any, np: Any) -> Any:
    """Return Genesis rasterizer depth as float32 metres.

    Genesis camera near/far planes and reconstructed point clouds use metres,
    so applying an additional millimetre conversion corrupts the sensor scale.
    """
    return np.asarray(depth, dtype=np.float32)


def needs_rolling_friction(sample: ParcelSample) -> bool:
    """Enable the more expensive solver path only for rolling-prone parcels."""
    return (
        sample.shape == "cylinder"
        and sample.orientation_mode == "horizontal"
        and sample.rolling_friction > 0
    )


def initialize_genesis(backend: str) -> tuple[Any, Any, Any]:
    """Initialize the pinned Genesis runtime and validate the selected GPU stack."""
    global _INITIALIZED_BACKEND

    if backend not in {"rocm", "cuda", "cpu"}:
        raise ValueError("backend must be one of: rocm, cuda, cpu")
    if _INITIALIZED_BACKEND is not None and _INITIALIZED_BACKEND != backend:
        raise RuntimeError(
            f"Genesis is already initialized for {_INITIALIZED_BACKEND}; use a new process for {backend}"
        )

    import numpy as np
    import torch
    import genesis as gs

    if _INITIALIZED_BACKEND is None:
        if backend == "rocm":
            if getattr(torch.version, "hip", None) is None:
                raise RuntimeError("ROCm backend requires a PyTorch HIP build")
            if not torch.cuda.is_available() or torch.cuda.device_count() != 1:
                raise RuntimeError("ROCm execution requires exactly one visible Radeon GPU")
            gs.init(backend=gs.gpu, precision="32", seed=0)
        elif backend == "cuda":
            if getattr(torch.version, "cuda", None) is None or getattr(torch.version, "hip", None) is not None:
                raise RuntimeError("CUDA backend requires an NVIDIA PyTorch CUDA build")
            if not torch.cuda.is_available():
                raise RuntimeError("PyTorch cannot access the NVIDIA GPU")
            gs.init(backend=gs.gpu, precision="32", seed=0)
        else:
            gs.init(backend=gs.cpu, precision="32", seed=0)
        _INITIALIZED_BACKEND = backend
    return gs, torch, np


class GenesisParcelEnv:
    """Single-environment Franka parcel sorting task with aligned RGB-D output."""

    def __init__(
        self,
        config: ExperimentConfig,
        sample: ParcelSample,
        *,
        backend: str = "rocm",
        show_viewer: bool = False,
        video_path: str | Path | None = None,
        capture_sensors: bool = False,
        capture_contact_wrench_telemetry: bool = False,
        contact_wrench_telemetry_backend: str = "cpu",
        contact_branch_control_window: tuple[int, int] | None = None,
        defer_initialization_settle: bool = False,
    ) -> None:
        self.config = config
        self.sample = sample
        # Check the end-effector contract before importing/building Genesis.
        # Evaluation-only catalog entries must not be mistaken for support.
        require_supported_handling(
            sample.handling_class,
            supported=runtime_supported_handling_classes(
                tri_suction_enabled=config.task.tri_suction_enabled,
            ),
        )
        self.backend = backend
        self.gs, self.torch, self.np = initialize_genesis(backend)
        self.gs.set_random_seed(config.seed + sample.episode_index)
        self._robot_asset_source = "Genesis 1.2.3 Apache-2.0 Panda MJCF"
        self._robot_mjcf_path = "xml/franka_emika_panda/panda.xml"
        self._robot_adapter_mass_per_finger_kg = 0.0
        self._robot_suction_mass_kg = 0.0
        source_mjcf = (
            Path(self.gs.__file__).resolve().parent
            / "assets"
            / "xml"
            / "franka_emika_panda"
            / "panda.xml"
        )
        if config.task.parcel_gripper_adapter_enabled:
            extension_value = (
                f"{config.task.parcel_gripper_adapter_extension_m * 1000.0:.6f}"
                .rstrip("0")
            )
            if extension_value.endswith("."):
                extension_value += "0"
            extension_tag = extension_value.replace(".", "p")
            density_tag = (
                f"{config.task.parcel_gripper_adapter_density_kg_m3:.3f}"
                .rstrip("0")
                .rstrip(".")
                .replace(".", "p")
            )
            inertia_enabled = config.task.parcel_gripper_adapter_inertia_enabled
            physical_tag = (
                f"{density_tag}kgm3" if inertia_enabled else "stockinertia"
            )
            generated_mjcf = (
                Path(config.output.root_dir)
                / "generated_assets"
                / f"panda_parcel_adapter_{extension_tag}mm_{physical_tag}.xml"
            )
            if inertia_enabled:
                self._robot_adapter_mass_per_finger_kg = (
                    config.task.parcel_gripper_adapter_density_kg_m3
                    * 0.020
                    * 0.008
                    * config.task.parcel_gripper_adapter_extension_m
                )
            self._robot_mjcf_path = str(
                build_parcel_gripper_mjcf(
                    source_mjcf,
                    generated_mjcf,
                    config.task.parcel_gripper_adapter_extension_m,
                    config.task.parcel_gripper_adapter_density_kg_m3,
                    combine_adapter_inertia=inertia_enabled,
                )
            )
        elif config.task.tri_suction_enabled:
            task = config.task
            radius_tag = f"{task.tri_suction_cup_radius_m * 1000:.1f}".replace(
                ".", "p"
            )
            footprint_tag = (
                f"{task.tri_suction_footprint_radius_m * 1000:.1f}".replace(
                    ".", "p"
                )
            )
            generated_mjcf = (
                Path(config.output.root_dir)
                / "generated_assets"
                / f"panda_tri_suction_r{radius_tag}_f{footprint_tag}.xml"
            )
            self._robot_suction_mass_kg = (
                3.0
                * task.tri_suction_density_kg_m3
                * math.pi
                * task.tri_suction_cup_radius_m**2
                * task.tri_suction_cup_length_m
            )
            self._robot_mjcf_path = str(
                build_tri_suction_mjcf(
                    source_mjcf,
                    generated_mjcf,
                    cup_radius_m=task.tri_suction_cup_radius_m,
                    footprint_radius_m=task.tri_suction_footprint_radius_m,
                    cup_length_m=task.tri_suction_cup_length_m,
                    tip_offset_m=task.tri_suction_tip_offset_m,
                    density_kg_m3=task.tri_suction_density_kg_m3,
                )
            )
        self.expert = ScriptedPickPlaceExpert(config, sample)
        self._shape_grasp_planner_config = ShapeGraspPlannerConfig(
            cylinder_jaw_aperture_m=2.0 * config.control.open_width_m,
        )
        self._geometry_grasp_planning_eligible = (
            sample.handling_class == "parallel_jaw"
            and box_requires_geometry_aware_grasp_planning(
                sample, hand_clearance_m=self.expert.grasp_hand_clearance_m()
            )
            or (sample.handling_class == "parallel_jaw" and sample.shape == "cylinder")
        )
        self._geometry_grasp_planning_active = resolve_geometry_grasp_planning_active(
            planning_enabled=config.task.geometry_aware_grasp_planning_enabled,
            geometry_eligible=self._geometry_grasp_planning_eligible,
            reset_fallback_gate_enabled=(
                config.task.grasp_planning_reset_fallback_gate_enabled
            ),
            reset_fallback_used=False,
        )
        self.control_step = 0
        self._release_steps = 0
        self._gripper_force_n = 0.0
        self._closed = False
        self._capture_sensors = capture_sensors
        self._capture_contact_wrench_telemetry = capture_contact_wrench_telemetry
        if contact_wrench_telemetry_backend not in {"cpu", "rocm"}:
            raise ValueError("contact_wrench_telemetry_backend must be cpu or rocm")
        self._contact_wrench_telemetry_backend = contact_wrench_telemetry_backend
        if contact_branch_control_window is not None:
            if (
                len(contact_branch_control_window) != 2
                or any(
                    not isinstance(value, int)
                    for value in contact_branch_control_window
                )
                or contact_branch_control_window[0] < 0
                or contact_branch_control_window[1]
                < contact_branch_control_window[0]
            ):
                raise ValueError(
                    "contact_branch_control_window must be two ordered "
                    "non-negative integers"
                )
        self._contact_branch_control_window = contact_branch_control_window
        self._latest_rgb: Any | None = None
        self._latest_depth: Any | None = None
        self._video_path = Path(video_path) if video_path else None
        self._wrist_video_path = (
            self._video_path.with_name(f"{self._video_path.stem}-wrist.mp4")
            if self._video_path is not None
            else None
        )
        self._action_queue: deque[CartesianAction | None] = deque(
            [None] * sample.action_delay_steps
        )
        self._aabb_guard_filter_count = 0
        self._aabb_guard_active_steps = 0
        self._aabb_guard_max_active_steps = 0
        self._aabb_guard_samples = 0
        self._aabb_guard_compute_ms_total = 0.0
        self._aabb_guard_last_gap_m: float | None = None
        self._aabb_guard_last_compute_ms = 0.0
        self._aabb_guard_last_triggered = False
        self._aabb_guard_last_reason: str | None = None
        self._aabb_guard_last_nominal_target_m: tuple[float, float, float] | None = None
        self._aabb_guard_last_filtered_target_m: tuple[float, float, float] | None = None
        self._approach_velocity_samples = 0
        self._approach_velocity_compute_ms_total = 0.0
        self._approach_velocity_max_joint_rad_s = 0.0
        self._approach_velocity_max_pose_error_m = 0.0
        self._approach_velocity_last_twist: tuple[float, ...] | None = None
        self._approach_velocity_last_joint_command: tuple[float, ...] | None = None
        self._approach_velocity_last_predicted_twist: tuple[float, ...] | None = None
        self._approach_velocity_last_actual_joint_velocity: tuple[float, ...] | None = None
        self._collision_checked_reset_used = False
        self._collision_checked_reset_compute_ms = 0.0
        self._initial_robot_parcel_collisions: tuple[dict[str, Any], ...] = ()
        self._fallback_robot_parcel_collisions: tuple[dict[str, Any], ...] = ()
        self._grasp_plan_retry_count: int | None = None
        self._grasp_plan_selected: dict[str, Any] | None = None
        self._grasp_plan_pending_replan = True
        self._grasp_plan_rejected_candidate_ids: set[str] = set()
        self._diagnostic_grasp_candidate_allowlist: frozenset[str] | None = None
        self._grasp_plan_events: list[dict[str, Any]] = []
        self._grasp_plan_compute_ms_total = 0.0
        self._grasp_plan_attempts = 0
        self._grasp_waypoint_checks = 0
        self._grasp_waypoint_rejections = 0
        self._grasp_waypoint_compute_ms_total = 0.0
        self._grasp_waypoint_collision_samples = 0
        self._grasp_waypoint_max_segment_samples = 0
        self._grasp_waypoint_last_collision: tuple[dict[str, Any], ...] = ()
        self._grasp_waypoint_last_restore_error = 0.0
        self._transport_slip_previous_relative_position_m: (
            tuple[float, float, float] | None
        ) = None
        self._transport_slip_samples = 0
        self._transport_slip_trigger_count = 0
        self._transport_slip_active_steps = 0
        self._transport_slip_force_remaining_steps = 0
        self._transport_slip_max_relative_delta_m = 0.0
        self._transport_slip_last_signal: TransportSlipSignal | None = None
        self._transport_slip_last_force_limit_n = (
            sample.close_force_n
            if sample.close_force_n is not None
            else config.control.close_force_n
        )
        self._transport_slip_events: list[dict[str, Any]] = []
        self._transport_slip_setdown_pending = False
        self._last_applied_command: str | None = None
        self._contact_wrench_events: list[dict[str, Any]] = []
        self._contact_wrench_samples = 0
        self._contact_wrench_compute_ms_total = 0.0
        self._contact_wrench_device: str | None = None
        self._contact_wrench_last: dict[str, Any] | None = None
        self._contact_branch_events: list[dict[str, Any]] = []
        self._contact_branch_device: str | None = None
        self._contact_branch_compute_ms_total = 0.0
        self._suction_commanded = False
        self._suction_attachment: SuctionAttachment | None = None
        self._suction_cup_geom_indices: frozenset[int] = frozenset()
        self._suction_geom_discovery = "disabled"
        self._suction_sealed_cup_count = 0
        self._suction_physical_contact_cup_count = 0
        self._suction_geometric_seal_cup_count = 0
        self._suction_latch_count = 0
        self._suction_break_count = 0
        self._suction_last_force_n = 0.0
        self._suction_last_torque_nm = 0.0
        self._suction_max_force_n = 0.0
        self._suction_max_position_error_m = 0.0
        self._suction_max_orientation_error_rad = 0.0

        physics_dt = 1.0 / config.simulation.physics_hz
        rolling_friction = needs_rolling_friction(sample)
        self.scene = self.gs.Scene(
            sim_options=self.gs.options.SimOptions(dt=physics_dt),
            rigid_options=self.gs.options.RigidOptions(
                box_box_detection=True,
                enable_collision=True,
                enable_joint_limit=True,
                enable_torsional_friction=rolling_friction,
                enable_rolling_friction=rolling_friction,
            ),
            viewer_options=self.gs.options.ViewerOptions(
                camera_pos=(1.35, -1.15, 0.95),
                camera_lookat=(0.48, 0.0, 0.08),
                camera_fov=48,
                res=(960, 640),
            ),
            profiling_options=self.gs.options.ProfilingOptions(show_FPS=False),
            show_viewer=show_viewer,
        )
        self.plane = self.scene.add_entity(self.gs.morphs.Plane())
        self._add_sorting_targets()
        self.robot = self.scene.add_entity(
            self.gs.morphs.MJCF(file=self._robot_mjcf_path),
            visualize_contact=show_viewer,
        )

        spawn = parcel_spawn_spec(config, sample)
        self._initial_parcel_z = spawn.initial_z_m
        self._contact_wrench_config = ContactWrenchConfig(
            parcel_mass_kg=sample.mass_kg,
            parcel_dimensions_m=spawn.dimensions_m,
            # Genesis 1.2.3 combines a contact pair with max(mu_a, mu_b).
            friction_coefficient=max(
                sample.friction,
                sample.finger_friction if sample.finger_friction is not None else 1.0,
            ),
            max_contact_force_n=config.task.max_contact_force_n,
        )
        color = (0.10, 0.55, 0.92) if sample.destination == "left" else (0.96, 0.55, 0.12)
        if spawn.shape == "box":
            parcel_morph = self.gs.morphs.Box(
                size=spawn.dimensions_m,
                pos=(sample.position_xy[0], sample.position_xy[1], spawn.initial_z_m),
                euler=spawn.euler_degrees,
            )
        else:
            parcel_morph = self.gs.morphs.Cylinder(
                height=spawn.cylinder_height_m,
                radius=spawn.cylinder_radius_m,
                pos=(sample.position_xy[0], sample.position_xy[1], spawn.initial_z_m),
                euler=spawn.euler_degrees,
            )
        self.parcel = self.scene.add_entity(
            parcel_morph,
            material=self.gs.materials.Rigid(
                friction=sample.friction,
                friction_rolling=sample.rolling_friction,
            ),
            surface=self.gs.surfaces.Rough(
                diffuse_texture=self.gs.textures.ColorTexture(color=color)
            ),
        )

        self.camera = None
        if config.sensors.rgb or config.sensors.depth or self._video_path:
            camera_base = (1.10, -0.78, 0.78)
            camera_position = tuple(
                base + noise
                for base, noise in zip(camera_base, sample.camera_noise_xyz_m, strict=True)
            )
            self.camera = self.scene.add_camera(
                res=(config.sensors.image_width, config.sensors.image_height),
                pos=camera_position,
                lookat=(0.50, 0.0, 0.04),
                fov=52,
                GUI=show_viewer,
            )
        self.wrist_camera = None
        if self._wrist_video_path is not None:
            self.wrist_camera = self.scene.add_camera(
                res=(config.sensors.image_width, config.sensors.image_height),
                pos=(0.45, 0.0, 0.55),
                lookat=(0.55, 0.0, 0.05),
                fov=72,
                GUI=False,
            )

        self.scene.build()
        self._configure_robot()
        self.parcel.set_mass(sample.mass_kg)
        self.end_effector = self.robot.get_link("hand")
        self.left_finger = self.robot.get_link("left_finger")
        self.right_finger = self.robot.get_link("right_finger")
        if config.task.tri_suction_enabled:
            named_cups = frozenset(
                int(geom.idx)
                for geom in self.end_effector.geoms
                if str(getattr(geom, "name", "")).startswith("suction_cup_")
                and str(getattr(geom, "name", "")).endswith("_collision")
            )
            if len(named_cups) == 3:
                self._suction_cup_geom_indices = named_cups
                self._suction_geom_discovery = "mjcf_name"
            else:
                collision_geoms = tuple(self.end_effector.geoms)
                if len(collision_geoms) >= 4:
                    self._suction_cup_geom_indices = frozenset(
                        int(geom.idx) for geom in collision_geoms[-3:]
                    )
                    self._suction_geom_discovery = "hand_collision_append_order"
            if len(self._suction_cup_geom_indices) != 3:
                raise RuntimeError(
                    "tri-suction MJCF must expose exactly three collision cups; "
                    f"hand collision geoms={len(tuple(self.end_effector.geoms))}"
                )
        if sample.finger_friction is not None:
            self.left_finger.set_friction(sample.finger_friction)
            self.right_finger.set_friction(sample.finger_friction)
        self.arm_dofs = self.np.arange(7)
        self.finger_dofs = self.np.arange(7, 9)
        self._configure_collision_checked_reset()
        self._refresh_geometry_grasp_planning_active()

        if self.camera is not None and self._video_path is not None:
            self._video_path.parent.mkdir(parents=True, exist_ok=True)
            self.camera.start_recording()
        if self.wrist_camera is not None and self._wrist_video_path is not None:
            self._wrist_video_path.parent.mkdir(parents=True, exist_ok=True)
            self.wrist_camera.start_recording()

        if not defer_initialization_settle:
            for _ in range(self.initialization_settle_steps):
                self.scene.step()
            if self.camera is not None and (self._capture_sensors or self._video_path):
                self._render_camera()

    @property
    def initialization_settle_steps(self) -> int:
        return max(2, self.config.simulation.physics_hz // 30)

    @property
    def geometry_grasp_planning_active(self) -> bool:
        return self._geometry_grasp_planning_active

    def set_diagnostic_all_box_grasp_planning(self) -> None:
        """Expose candidate enumeration for a preregistered box-only study."""
        if self.sample.shape != "box" or self.sample.dimensions_m is None:
            raise ValueError("all-box grasp planning requires a rigid box sample")
        if self.config.task.grasp_planning_reset_fallback_gate_enabled:
            raise ValueError("all-box diagnostic scope cannot use the reset fallback gate")
        self._geometry_grasp_planning_eligible = True
        self._refresh_geometry_grasp_planning_active()

    def _add_sorting_targets(self) -> None:
        targets = []
        for center, color in (
            (self.config.task.left_bin_center_m, (0.08, 0.55, 0.92)),
            (self.config.task.right_bin_center_m, (0.96, 0.50, 0.08)),
        ):
            targets.append(self.scene.add_entity(
                self.gs.morphs.Box(
                    size=(
                        self.config.task.bin_half_extent_m[0] * 2,
                        self.config.task.bin_half_extent_m[1] * 2,
                        0.01,
                    ),
                    pos=(center[0], center[1], 0.005),
                    fixed=True,
                ),
                surface=self.gs.surfaces.Rough(
                    diffuse_texture=self.gs.textures.ColorTexture(color=color)
                ),
            ))
        self.sorting_targets = tuple(targets)

    def _configure_robot(self) -> None:
        control = self.config.control
        gains_kp, gains_kv = scaled_robot_gains(
            control.arm_kp,
            control.arm_kv,
            control.finger_kp,
            control.finger_kv,
            1.0,
        )
        gains_kp = self.np.asarray(gains_kp)
        gains_kv = self.np.asarray(gains_kv)
        self.robot.set_dofs_kp(gains_kp)
        self.robot.set_dofs_kv(gains_kv)
        self._active_arm_stiffness_scale = 1.0
        self.robot.set_dofs_force_range(
            self.np.asarray((-87, -87, -87, -87, -12, -12, -12, -100, -100)),
            self.np.asarray((87, 87, 87, 87, 12, 12, 12, 100, 100)),
        )
        self.robot.set_qpos(
            self.np.asarray(control.reset_qpos)
        )

    def state(self) -> RobotState:
        joint_positions = self._flat_tuple(self.robot.get_qpos())
        ee_pose = (
            *self._flat_tuple(self.end_effector.get_pos()),
            *self._flat_tuple(self.end_effector.get_quat()),
        )
        parcel_pose = (
            *self._flat_tuple(self.parcel.get_pos()),
            *self._flat_tuple(self.parcel.get_quat()),
        )
        _, max_force = self._grasp_contact()
        return RobotState(
            joint_positions=joint_positions,
            end_effector_pose=ee_pose,
            parcel_pose=parcel_pose,
            target_position=self.expert.destination_position,
            gripper_contact_force_n=max_force,
        )

    def prepare_action(self, decision: ControlDecision, state: RobotState) -> None:
        """Update payload safety and select a grasp before policy prediction."""
        self._update_transport_slip_recovery(decision, state)
        task = self.config.task
        if (
            not self._geometry_grasp_planning_active
            or decision.command != "move_pregrasp"
        ):
            return

        retry_changed = decision.retry_count != self._grasp_plan_retry_count
        self._grasp_plan_rejected_candidate_ids = rejected_candidates_after_retry(
            self._grasp_plan_rejected_candidate_ids,
            self._grasp_plan_selected,
            retry_changed=retry_changed,
            blacklist_failed_candidate_enabled=(
                task.grasp_planning_failed_candidate_blacklist_enabled
            ),
        )
        should_replan = (
            self._grasp_plan_selected is None
            and self._grasp_plan_pending_replan
        ) or (
            retry_changed and task.grasp_planning_retry_replan_enabled
        )
        if not should_replan:
            self._grasp_plan_retry_count = decision.retry_count
            return

        self.expert.clear_planned_grasp_pose()
        self._grasp_plan_selected = None
        self._grasp_plan_pending_replan = False
        self._action_queue = deque([None] * self.sample.action_delay_steps)
        self._plan_grasp_pose(state, decision.retry_count)

    def set_diagnostic_grasp_candidate_allowlist(
        self,
        candidate_ids: frozenset[str],
    ) -> None:
        """Restrict the planner before an isolated counterfactual experiment."""
        if not candidate_ids:
            raise ValueError("diagnostic grasp candidate allowlist cannot be empty")
        if self._grasp_plan_attempts or self.control_step:
            raise RuntimeError("diagnostic allowlist must be set before execution")
        self._diagnostic_grasp_candidate_allowlist = frozenset(
            str(candidate_id) for candidate_id in candidate_ids
        )

    def _update_transport_slip_recovery(
        self,
        decision: ControlDecision,
        state: RobotState,
    ) -> None:
        control = self.config.control
        phase = self.expert.transport_phase
        active = (
            (
                control.transport_slip_recovery_enabled
                or control.transport_slip_setdown_regrasp_enabled
            )
            and self._geometry_grasp_planning_active
            and decision.command in {"move_lift", "move_drop"}
            and phase in PAYLOAD_TRANSPORT_PHASES
        )
        if not active:
            self._transport_slip_previous_relative_position_m = None
            self._transport_slip_force_remaining_steps = 0
            if decision.command == "move_recovery_setdown":
                self._transport_slip_setdown_pending = False
            return

        current_relative = tuple(
            float(ee - parcel)
            for ee, parcel in zip(
                state.end_effector_pose[:3],
                state.parcel_pose[:3],
                strict=True,
            )
        )
        signal = detect_transport_slip(
            self._transport_slip_previous_relative_position_m,
            state,
            phase=phase,
            relative_delta_threshold_m=control.transport_slip_relative_delta_m,
            downward_delta_threshold_m=control.transport_slip_downward_delta_m,
            min_contact_force_n=control.transport_slip_min_contact_force_n,
            min_destination_distance_m=(
                control.transport_slip_min_destination_distance_m
            ),
        )
        self._transport_slip_previous_relative_position_m = current_relative
        if signal is None:
            return

        self._transport_slip_samples += 1
        self._transport_slip_last_signal = signal
        self._transport_slip_max_relative_delta_m = max(
            self._transport_slip_max_relative_delta_m,
            signal.relative_delta_m,
        )
        if not signal.triggered:
            return

        self._transport_slip_trigger_count += 1
        if control.transport_slip_recovery_enabled:
            self._transport_slip_force_remaining_steps = max(
                self._transport_slip_force_remaining_steps,
                control.transport_slip_force_hold_steps,
            )
        if control.transport_slip_setdown_regrasp_enabled:
            self._transport_slip_setdown_pending = True
        self._transport_slip_events.append(
            {
                "frame": self.control_step,
                "phase": phase,
                **asdict(signal),
            }
        )

    def _plan_grasp_pose(self, state: RobotState, retry_count: int) -> None:
        started = time.perf_counter_ns()
        task = self.config.task
        plan = build_shape_grasp_plan(
            self.sample,
            state.parcel_pose,
            hand_clearance_m=self.expert.grasp_hand_clearance_m(),
            include_symmetric_wrist=task.grasp_planning_symmetric_wrist_enabled,
            config=self._shape_grasp_planner_config,
        )
        candidates = plan.candidates if plan.activation_eligible else ()
        seeds = self._grasp_planning_seeds()
        evaluations = [
            self._evaluate_grasp_pose_candidate(candidate, seed_name, seed_qpos)
            for candidate in candidates
            for seed_name, seed_qpos in seeds
        ]
        ranked = rank_shape_grasp_pose_evaluations(
            evaluations,
            shape=plan.shape,
            collision_filter_enabled=task.grasp_planning_collision_filter_enabled,
            manipulability_ranking_enabled=(
                task.grasp_planning_manipulability_ranking_enabled
            ),
        )
        effective_rejected_ids = effective_rejected_candidate_ids(
            tuple(candidate.candidate_id for candidate in candidates),
            self._grasp_plan_rejected_candidate_ids,
            self._diagnostic_grasp_candidate_allowlist,
        )
        selected = select_shape_grasp_pose_evaluation(
            ranked,
            shape=plan.shape,
            rejected_candidate_ids=effective_rejected_ids,
            collision_filter_enabled=task.grasp_planning_collision_filter_enabled,
            manipulability_ranking_enabled=(
                task.grasp_planning_manipulability_ranking_enabled
            ),
        )
        compute_ms = (time.perf_counter_ns() - started) / 1_000_000
        self._grasp_plan_attempts += 1
        self._grasp_plan_compute_ms_total += compute_ms
        self._grasp_plan_retry_count = retry_count

        selected_summary = None
        if selected is not None:
            self._grasp_plan_selected = dict(selected)
            self.expert.set_planned_grasp_pose(
                tuple(float(value) for value in selected["target_position"]),
                tuple(float(value) for value in selected["target_quaternion"]),
            )
            selected_summary = self._grasp_evaluation_summary(selected)
        self._grasp_plan_events.append(
            {
                "retry_count": retry_count,
                "shape": plan.shape,
                "capability_reason": plan.reason,
                "candidate_count": len(candidates),
                "seed_count": len(seeds),
                "evaluation_count": len(evaluations),
                "feasible_count": sum(
                    grasp_evaluation_is_feasible(
                        evaluation,
                        collision_filter_enabled=(
                            task.grasp_planning_collision_filter_enabled
                        ),
                    )
                    for evaluation in evaluations
                ),
                "rejected_candidate_ids": sorted(effective_rejected_ids),
                "diagnostic_candidate_allowlist": (
                    sorted(self._diagnostic_grasp_candidate_allowlist)
                    if self._diagnostic_grasp_candidate_allowlist is not None
                    else None
                ),
                "selected": selected_summary,
                "compute_ms": compute_ms,
            }
        )

    def _grasp_planning_seeds(self) -> tuple[tuple[str, tuple[float, ...]], ...]:
        configured = (
            ("current", self._flat_tuple(self.robot.get_qpos())),
            ("historical_reset", tuple(self.config.control.reset_qpos)),
            (
                "collision_free_reset",
                tuple(self.config.control.collision_free_reset_qpos),
            ),
        )
        unique: list[tuple[str, tuple[float, ...]]] = []
        for name, values in configured:
            if not any(
                len(values) == len(other)
                and all(
                    math.isclose(value, reference, abs_tol=1e-9)
                    for value, reference in zip(values, other, strict=True)
                )
                for _, other in unique
            ):
                unique.append((name, values))
        return tuple(unique)

    def _evaluate_grasp_pose_candidate(
        self,
        candidate: Any,
        seed_name: str,
        seed_qpos: tuple[float, ...],
    ) -> dict[str, Any]:
        started = time.perf_counter_ns()
        qpos, ik_error = self.robot.inverse_kinematics(
            link=self.end_effector,
            pos=self.np.asarray(candidate.target_position),
            quat=self.np.asarray(candidate.target_quaternion),
            init_qpos=self.np.asarray(seed_qpos),
            respect_joint_limit=True,
            max_samples=8,
            max_solver_iters=40,
            return_error=True,
        )
        qpos_values = list(self._flat_tuple(qpos))
        qpos_values[7:] = (
            self.config.control.open_width_m,
            self.config.control.open_width_m,
        )
        qpos_array = self.np.asarray(qpos_values)
        ik_error_values = self._flat_tuple(ik_error)
        finite = all(
            math.isfinite(value) for value in (*qpos_values, *ik_error_values)
        )

        link_local_index = int(self.end_effector.idx - self.robot.link_start)
        qpos_device = self.robot.get_qpos().device
        fk_positions, fk_quaternions = self.robot.forward_kinematics(
            self.torch.as_tensor(qpos_array, device=qpos_device),
            links_idx_local=self.np.asarray((link_local_index,)),
        )
        fk_position = self._flat_tuple(fk_positions)
        fk_quaternion = self._flat_tuple(fk_quaternions)
        original_qpos = self._flat_tuple(self.robot.get_qpos())
        collisions: tuple[dict[str, Any], ...] = ()
        singular_values: tuple[float, ...] = ()
        clearance_m = 0.0
        restore_error = math.inf
        try:
            self.robot.set_qpos(qpos_array)
            collisions = self._describe_robot_collisions()
            clearance_m = self._minimum_nonfinger_parcel_clearance_m()
            jacobian = self.robot.get_jacobian(self.end_effector)[..., :7]
            singular_values = self._flat_tuple(
                self.torch.linalg.svdvals(jacobian)
            )
        finally:
            self.robot.set_qpos(self.np.asarray(original_qpos))
            restored = self._flat_tuple(self.robot.get_qpos())
            restore_error = max(
                abs(value - reference)
                for value, reference in zip(restored, original_qpos, strict=True)
            )

        disallowed = tuple(
            collision
            for collision in collisions
            if not (
                collision["robot_link"] in {"left_finger", "right_finger"}
                and collision["other_is_parcel"]
            )
        )
        joint_distance = math.sqrt(
            sum(
                (value - reference) ** 2
                for value, reference in zip(
                    qpos_values[:7], original_qpos[:7], strict=True
                )
            )
        )
        min_singular_value = min(singular_values) if singular_values else 0.0
        evaluation = {
            **asdict(candidate),
            "seed_name": seed_name,
            "qpos": qpos_values,
            "ik_error_pose": ik_error_values,
            "ik_position_error_m": math.sqrt(
                sum(value * value for value in ik_error_values[:3])
            ),
            "ik_rotation_error_rad": math.sqrt(
                sum(value * value for value in ik_error_values[3:])
            ),
            "fk_position": fk_position,
            "fk_quaternion": fk_quaternion,
            "fk_position_error_m": math.dist(
                fk_position, candidate.target_position
            ),
            "joint_distance_rad": joint_distance,
            "jacobian_singular_values": singular_values,
            "minimum_singular_value": min_singular_value,
            "nonfinger_clearance_m": clearance_m,
            "collisions": collisions,
            "disallowed_collisions": disallowed,
            "collision_count": len(collisions),
            "disallowed_collision_count": len(disallowed),
            "restore_max_abs_error": restore_error,
            "finite": finite,
            "compute_ms": (time.perf_counter_ns() - started) / 1_000_000,
        }
        evaluation["feasible"] = grasp_evaluation_is_feasible(
            evaluation,
            collision_filter_enabled=(
                self.config.task.grasp_planning_collision_filter_enabled
            ),
        )
        return evaluation

    @staticmethod
    def _grasp_evaluation_summary(
        evaluation: Mapping[str, Any],
    ) -> dict[str, Any]:
        keys = (
            "candidate_id",
            "seed_name",
            "target_position",
            "target_quaternion",
            "longitudinal_offset_m",
            "vertical_offset_m",
            "wrist_variant",
            "approach_variant",
            "approach_direction",
            "ik_position_error_m",
            "ik_rotation_error_rad",
            "fk_position_error_m",
            "joint_distance_rad",
            "minimum_singular_value",
            "nonfinger_clearance_m",
            "disallowed_collision_count",
            "compute_ms",
        )
        return {key: evaluation[key] for key in keys}

    def _describe_robot_collisions(self) -> tuple[dict[str, Any], ...]:
        rows = []
        for geom_a_index, geom_b_index in self.robot.detect_collision():
            geom_a = self.scene.rigid_solver.geoms[int(geom_a_index)]
            geom_b = self.scene.rigid_solver.geoms[int(geom_b_index)]
            if geom_a.entity is self.robot:
                robot_geom, other_geom = geom_a, geom_b
            elif geom_b.entity is self.robot:
                robot_geom, other_geom = geom_b, geom_a
            else:
                continue
            rows.append(
                {
                    "robot_geom_index": int(robot_geom.idx),
                    "robot_link": str(robot_geom.link.name),
                    "other_geom_index": int(other_geom.idx),
                    "other_link": str(other_geom.link.name),
                    "other_is_parcel": other_geom.entity is self.parcel,
                }
            )
        return tuple(rows)

    def _minimum_nonfinger_parcel_clearance_m(self) -> float:
        parcel_aabb = self.parcel.get_AABB()
        clearances = []
        for link in self.robot.links:
            if str(link.name) in {"left_finger", "right_finger"} or link.n_geoms == 0:
                continue
            clearances.append(aabb_gap_m(link.get_AABB(), parcel_aabb))
        return min(clearances) if clearances else 0.0

    def observation(self, state: RobotState | None = None) -> Observation:
        state = state or self.state()
        parcel_position = state.parcel_pose[:3]
        ee_position = state.end_effector_pose[:3]
        has_contact, max_force = self._grasp_contact()
        destination = self.expert.destination_position
        in_bin = (
            abs(parcel_position[0] - destination[0]) <= self.config.task.bin_half_extent_m[0]
            and abs(parcel_position[1] - destination[1]) <= self.config.task.bin_half_extent_m[1]
        )
        at_drop = self._distance(ee_position, self.expert.drop_position()) <= self.config.task.position_tolerance_m
        recovery_setdown = self.expert.recovery_setdown_position(ee_position)
        at_recovery_setdown = (
            ee_position[2]
            <= recovery_setdown[2] + self.config.task.position_tolerance_m
        )
        if in_bin and not has_contact:
            self._release_steps += 1
        else:
            self._release_steps = 0

        values = (*state.joint_positions, *state.end_effector_pose, *state.parcel_pose)
        finite = all(math.isfinite(value) for value in values)
        return Observation(
            parcel_visible=finite and parcel_position[2] > -0.02,
            at_pregrasp=self.expert.at_pregrasp(ee_position, state.parcel_pose),
            grasp_contact=has_contact,
            parcel_lifted=parcel_position[2]
            >= self._initial_parcel_z + self.config.task.lift_height_m * 0.65,
            at_drop_pose=at_drop,
            parcel_in_bin=in_bin,
            parcel_released=self._release_steps >= self.config.task.release_settle_steps,
            transport_slip=self._transport_slip_setdown_pending,
            at_recovery_setdown=at_recovery_setdown,
            excessive_contact_force=max_force > self.config.task.max_contact_force_n,
            fault=not finite,
        )

    def step(self, action: CartesianAction) -> None:
        self._action_queue.append(action)
        delayed_action = self._action_queue.popleft()
        if delayed_action is not None:
            self._apply_action(delayed_action)
            self._last_applied_command = delayed_action.command

        physics_steps = self.config.simulation.physics_hz // self.config.simulation.control_hz
        for physics_substep in range(physics_steps):
            self.scene.step()
            self._update_suction_attachment()
            if (
                self._contact_branch_control_window is not None
                and self._contact_branch_control_window[0]
                <= self.control_step
                <= self._contact_branch_control_window[1]
            ):
                self._record_contact_branch(physics_substep)
            if (
                self._capture_contact_wrench_telemetry
                and physics_substep == physics_steps - 1
            ):
                self._record_contact_wrench(physics_substep)
        self.control_step += 1

        camera_stride = self.config.simulation.control_hz // self.config.simulation.camera_hz
        if self.camera is not None and self.control_step % camera_stride == 0:
            if self._capture_sensors or self._video_path:
                self._render_camera()

    def sensor_frame(self) -> tuple[Any | None, Any | None]:
        if not self._capture_sensors:
            return None, None
        if self._latest_rgb is None and self.camera is not None:
            self._render_camera()
        return self._latest_rgb, self._latest_depth

    def parcel_dropped(self) -> bool:
        position = self._flat_tuple(self.parcel.get_pos())
        return position[2] < -0.02 or abs(position[0]) > 1.2 or abs(position[1]) > 1.2

    def safety_snapshot(self) -> dict[str, Any]:
        """Return the last action-filter event without changing the policy action schema."""
        return {
            "precontact_aabb_guard_enabled": (
                self.config.control.precontact_aabb_guard_distance_m is not None
            ),
            "precontact_aabb_gap_m": self._aabb_guard_last_gap_m,
            "precontact_aabb_guard_triggered": self._aabb_guard_last_triggered,
            "precontact_aabb_guard_reason": self._aabb_guard_last_reason,
            "precontact_aabb_nominal_target_m": self._aabb_guard_last_nominal_target_m,
            "precontact_aabb_filtered_target_m": self._aabb_guard_last_filtered_target_m,
            "precontact_aabb_guard_compute_ms": self._aabb_guard_last_compute_ms,
            "precontact_aabb_guard_filter_count": self._aabb_guard_filter_count,
            "precontact_aabb_guard_active_steps": self._aabb_guard_active_steps,
            "geometry_aware_grasp_planning_enabled": (
                self.config.task.geometry_aware_grasp_planning_enabled
            ),
            "geometry_aware_grasp_planning_active": (
                self._geometry_grasp_planning_active
            ),
            "geometry_aware_grasp_planning_geometry_eligible": (
                self._geometry_grasp_planning_eligible
            ),
            "grasp_planning_reset_fallback_gate_enabled": (
                self.config.task.grasp_planning_reset_fallback_gate_enabled
            ),
            "grasp_planning_reset_fallback_gate_satisfied": (
                self._collision_checked_reset_used
                if self.config.task.grasp_planning_reset_fallback_gate_enabled
                else None
            ),
            "grasp_plan_retry_count": self._grasp_plan_retry_count,
            "grasp_plan_selected_candidate_id": (
                self._grasp_plan_selected["candidate_id"]
                if self._grasp_plan_selected is not None
                else None
            ),
            "grasp_planning_transport_phase": self.expert.transport_phase,
            "grasp_planning_transport_lookahead_enabled": (
                self.config.task.grasp_planning_transport_lookahead_enabled
            ),
            "grasp_planning_failed_candidate_blacklist_enabled": (
                self.config.task.grasp_planning_failed_candidate_blacklist_enabled
            ),
            "diagnostic_grasp_candidate_allowlist": (
                sorted(self._diagnostic_grasp_candidate_allowlist)
                if self._diagnostic_grasp_candidate_allowlist is not None
                else None
            ),
            "transport_slip_recovery_enabled": (
                self.config.control.transport_slip_recovery_enabled
            ),
            "transport_slip_setdown_regrasp_enabled": (
                self.config.control.transport_slip_setdown_regrasp_enabled
            ),
            "transport_slip_setdown_pending": self._transport_slip_setdown_pending,
            "transport_slip_trigger_count": self._transport_slip_trigger_count,
            "transport_slip_force_remaining_steps": (
                self._transport_slip_force_remaining_steps
            ),
            "transport_slip_last_force_limit_n": (
                self._transport_slip_last_force_limit_n
            ),
            "transport_slip_last_signal": (
                asdict(self._transport_slip_last_signal)
                if self._transport_slip_last_signal is not None
                else None
            ),
            "grasp_waypoint_rejections": self._grasp_waypoint_rejections,
            "grasp_waypoint_last_collision": self._grasp_waypoint_last_collision,
            "contact_wrench_telemetry_enabled": (
                self._capture_contact_wrench_telemetry
            ),
            "contact_wrench_last": self._contact_wrench_last,
        }

    def safety_summary(self) -> dict[str, Any]:
        mean_compute_ms = (
            self._aabb_guard_compute_ms_total / self._aabb_guard_samples
            if self._aabb_guard_samples
            else 0.0
        )
        contact_wrench_summary = summarize_contact_wrench_events(
            self._contact_wrench_events,
            predictive_window_samples=max(
                1,
                round(self.config.simulation.control_hz * 0.1),
            ),
        )
        contact_branch_summary = summarize_contact_branch_events(
            self._contact_branch_events,
            self.config.task.max_contact_force_n,
        )
        return {
            "precontact_aabb_guard_enabled": (
                self.config.control.precontact_aabb_guard_distance_m is not None
            ),
            "precontact_aabb_guard_distance_m": (
                self.config.control.precontact_aabb_guard_distance_m
            ),
            "precontact_aabb_guard_filter_count": self._aabb_guard_filter_count,
            "precontact_aabb_guard_max_active_steps": self._aabb_guard_max_active_steps,
            "precontact_aabb_guard_samples": self._aabb_guard_samples,
            "precontact_aabb_guard_compute_ms_total": self._aabb_guard_compute_ms_total,
            "precontact_aabb_guard_compute_ms_mean": mean_compute_ms,
            "approach_velocity_control_enabled": (
                self.config.control.approach_velocity_control_enabled
            ),
            "approach_velocity_control_samples": self._approach_velocity_samples,
            "approach_velocity_control_compute_ms_total": (
                self._approach_velocity_compute_ms_total
            ),
            "approach_velocity_control_compute_ms_mean": (
                self._approach_velocity_compute_ms_total / self._approach_velocity_samples
                if self._approach_velocity_samples
                else 0.0
            ),
            "approach_velocity_control_max_joint_rad_s": (
                self._approach_velocity_max_joint_rad_s
            ),
            "approach_velocity_control_max_pose_error_m": (
                self._approach_velocity_max_pose_error_m
            ),
            "approach_velocity_control_last_twist": self._approach_velocity_last_twist,
            "approach_velocity_control_last_joint_command": (
                self._approach_velocity_last_joint_command
            ),
            "approach_velocity_control_last_predicted_twist": (
                self._approach_velocity_last_predicted_twist
            ),
            "approach_velocity_control_last_actual_joint_velocity": (
                self._approach_velocity_last_actual_joint_velocity
            ),
            "collision_checked_reset_enabled": (
                self.config.control.collision_checked_reset_enabled
            ),
            "collision_checked_reset_used": self._collision_checked_reset_used,
            "collision_checked_reset_compute_ms": self._collision_checked_reset_compute_ms,
            "initial_robot_parcel_collisions": self._initial_robot_parcel_collisions,
            "fallback_robot_parcel_collisions": self._fallback_robot_parcel_collisions,
            "geometry_aware_grasp_planning_enabled": (
                self.config.task.geometry_aware_grasp_planning_enabled
            ),
            "geometry_aware_grasp_planning_active": (
                self._geometry_grasp_planning_active
            ),
            "geometry_aware_grasp_planning_geometry_eligible": (
                self._geometry_grasp_planning_eligible
            ),
            "grasp_planning_reset_fallback_gate_enabled": (
                self.config.task.grasp_planning_reset_fallback_gate_enabled
            ),
            "grasp_planning_reset_fallback_gate_satisfied": (
                self._collision_checked_reset_used
                if self.config.task.grasp_planning_reset_fallback_gate_enabled
                else None
            ),
            "grasp_planning_collision_filter_enabled": (
                self.config.task.grasp_planning_collision_filter_enabled
            ),
            "grasp_planning_manipulability_ranking_enabled": (
                self.config.task.grasp_planning_manipulability_ranking_enabled
            ),
            "grasp_planning_symmetric_wrist_enabled": (
                self.config.task.grasp_planning_symmetric_wrist_enabled
            ),
            "grasp_planning_retry_replan_enabled": (
                self.config.task.grasp_planning_retry_replan_enabled
            ),
            "grasp_planning_failed_candidate_blacklist_enabled": (
                self.config.task.grasp_planning_failed_candidate_blacklist_enabled
            ),
            "diagnostic_grasp_candidate_allowlist": (
                sorted(self._diagnostic_grasp_candidate_allowlist)
                if self._diagnostic_grasp_candidate_allowlist is not None
                else None
            ),
            "grasp_planning_waypoint_collision_gate_enabled": (
                self.config.task.grasp_planning_waypoint_collision_gate_enabled
            ),
            "grasp_planning_stability_steps": (
                self.config.task.grasp_planning_stability_steps
            ),
            "grasp_planning_final_approach_step_m": (
                self.config.task.grasp_planning_final_approach_step_m
            ),
            "grasp_planning_tall_box_height_m": (
                self.config.task.grasp_planning_tall_box_height_m
            ),
            "grasp_planning_tall_box_final_approach_step_m": (
                self.config.task.grasp_planning_tall_box_final_approach_step_m
            ),
            "grasp_planning_effective_final_approach_step_m": (
                self.expert.planned_final_approach_step_m()
                if self._geometry_grasp_planning_active
                else None
            ),
            "grasp_planning_drop_step_m": (
                self.config.task.grasp_planning_drop_step_m
            ),
            "grasp_planning_transport_contract_enabled": (
                self.config.task.grasp_planning_transport_contract_enabled
            ),
            "grasp_planning_transport_lookahead_enabled": (
                self.config.task.grasp_planning_transport_lookahead_enabled
            ),
            "grasp_planning_raise_step_m": (
                self.config.task.grasp_planning_raise_step_m
            ),
            "grasp_planning_transport_step_m": (
                self.config.task.grasp_planning_transport_step_m
            ),
            "grasp_planning_transfer_settle_steps": (
                self.config.task.grasp_planning_transfer_settle_steps
            ),
            "grasp_planning_transport_final_phase": self.expert.transport_phase,
            "transport_slip_recovery_enabled": (
                self.config.control.transport_slip_recovery_enabled
            ),
            "transport_slip_setdown_regrasp_enabled": (
                self.config.control.transport_slip_setdown_regrasp_enabled
            ),
            "transport_slip_setdown_step_m": (
                self.config.control.transport_slip_setdown_step_m
            ),
            "transport_slip_setdown_max_steps": (
                self.config.control.transport_slip_setdown_max_steps
            ),
            "transport_slip_setdown_pending": self._transport_slip_setdown_pending,
            "transport_slip_relative_delta_m": (
                self.config.control.transport_slip_relative_delta_m
            ),
            "transport_slip_downward_delta_m": (
                self.config.control.transport_slip_downward_delta_m
            ),
            "transport_slip_min_contact_force_n": (
                self.config.control.transport_slip_min_contact_force_n
            ),
            "transport_slip_min_destination_distance_m": (
                self.config.control.transport_slip_min_destination_distance_m
            ),
            "transport_slip_force_boost_n": (
                self.config.control.transport_slip_force_boost_n
            ),
            "transport_slip_force_hold_steps": (
                self.config.control.transport_slip_force_hold_steps
            ),
            "transport_slip_samples": self._transport_slip_samples,
            "transport_slip_trigger_count": self._transport_slip_trigger_count,
            "transport_slip_active_steps": self._transport_slip_active_steps,
            "transport_slip_max_relative_delta_m": (
                self._transport_slip_max_relative_delta_m
            ),
            "transport_slip_last_force_limit_n": (
                self._transport_slip_last_force_limit_n
            ),
            "transport_slip_events": tuple(self._transport_slip_events),
            "grasp_planning_joint_segment_resolution_rad": (
                self.config.task.grasp_planning_joint_segment_resolution_rad
            ),
            "parcel_gripper_adapter_enabled": (
                self.config.task.parcel_gripper_adapter_enabled
            ),
            "parcel_gripper_adapter_extension_m": (
                self.config.task.parcel_gripper_adapter_extension_m
            ),
            "parcel_gripper_adapter_density_kg_m3": (
                self.config.task.parcel_gripper_adapter_density_kg_m3
            ),
            "parcel_gripper_adapter_inertia_enabled": (
                self.config.task.parcel_gripper_adapter_inertia_enabled
            ),
            "parcel_gripper_adapter_mass_per_finger_kg": (
                self._robot_adapter_mass_per_finger_kg
            ),
            "parcel_gripper_adapter_inertia_model": (
                "combined_rigid_body"
                if (
                    self.config.task.parcel_gripper_adapter_enabled
                    and self.config.task.parcel_gripper_adapter_inertia_enabled
                )
                else (
                    "stock_explicit_inertia_ablation"
                    if self.config.task.parcel_gripper_adapter_enabled
                    else "stock_explicit_inertia"
                )
            ),
            "tri_suction_enabled": self.config.task.tri_suction_enabled,
            "tri_suction_cup_count": len(self._suction_cup_geom_indices),
            "tri_suction_geom_discovery": self._suction_geom_discovery,
            "tri_suction_min_sealed_cups": self.config.task.tri_suction_min_sealed_cups,
            "tri_suction_sealed_cup_count": self._suction_sealed_cup_count,
            "tri_suction_physical_contact_cup_count": (
                self._suction_physical_contact_cup_count
            ),
            "tri_suction_geometric_seal_cup_count": (
                self._suction_geometric_seal_cup_count
            ),
            "tri_suction_commanded": self._suction_commanded,
            "tri_suction_attached": self._suction_attachment is not None,
            "tri_suction_latch_count": self._suction_latch_count,
            "tri_suction_break_count": self._suction_break_count,
            "tri_suction_last_force_n": self._suction_last_force_n,
            "tri_suction_max_force_n": self._suction_max_force_n,
            "tri_suction_last_torque_nm": self._suction_last_torque_nm,
            "tri_suction_max_position_error_m": self._suction_max_position_error_m,
            "tri_suction_max_orientation_error_rad": self._suction_max_orientation_error_rad,
            "robot_mjcf_path": self._robot_mjcf_path,
            "robot_asset_source": self._robot_asset_source,
            "grasp_plan_attempts": self._grasp_plan_attempts,
            "grasp_plan_compute_ms_total": self._grasp_plan_compute_ms_total,
            "grasp_plan_events": tuple(self._grasp_plan_events),
            "grasp_waypoint_checks": self._grasp_waypoint_checks,
            "grasp_waypoint_rejections": self._grasp_waypoint_rejections,
            "grasp_waypoint_compute_ms_total": self._grasp_waypoint_compute_ms_total,
            "grasp_waypoint_collision_samples": (
                self._grasp_waypoint_collision_samples
            ),
            "grasp_waypoint_max_segment_samples": (
                self._grasp_waypoint_max_segment_samples
            ),
            "grasp_waypoint_last_collision": self._grasp_waypoint_last_collision,
            "grasp_waypoint_last_restore_error": (
                self._grasp_waypoint_last_restore_error
            ),
            "contact_wrench_telemetry_enabled": (
                self._capture_contact_wrench_telemetry
            ),
            "contact_wrench_device": self._contact_wrench_device,
            "contact_wrench_telemetry_backend": (
                self._contact_wrench_telemetry_backend
            ),
            "contact_wrench_sample_hz": self.config.simulation.control_hz,
            "contact_wrench_samples": self._contact_wrench_samples,
            "contact_wrench_compute_ms_total": (
                self._contact_wrench_compute_ms_total
            ),
            "contact_wrench_compute_ms_mean": (
                self._contact_wrench_compute_ms_total / self._contact_wrench_samples
                if self._contact_wrench_samples
                else 0.0
            ),
            "contact_wrench_summary": contact_wrench_summary,
            "contact_wrench_events": tuple(self._contact_wrench_events),
            "contact_branch_control_window": self._contact_branch_control_window,
            "contact_branch_device": self._contact_branch_device,
            "contact_branch_sample_hz": self.config.simulation.physics_hz,
            "contact_branch_compute_ms_total": (
                self._contact_branch_compute_ms_total
            ),
            "contact_branch_summary": contact_branch_summary,
            "contact_branch_events": tuple(self._contact_branch_events),
        }

    def close(self) -> None:
        if self._closed:
            return
        try:
            if self.camera is not None and self._video_path is not None:
                self.camera.stop_recording(
                    save_to_filename=str(self._video_path),
                    fps=self.config.simulation.camera_hz,
                )
            if self.wrist_camera is not None and self._wrist_video_path is not None:
                self.wrist_camera.stop_recording(
                    save_to_filename=str(self._wrist_video_path),
                    fps=self.config.simulation.camera_hz,
                )
        finally:
            self.scene.destroy()
            self._closed = True

    def _apply_action(self, action: CartesianAction) -> None:
        action = self._filter_precontact_action(action)
        self._set_arm_stiffness_for_command(action.command)
        planned_pregrasp = (
            self._geometry_grasp_planning_active
            and action.command == "move_pregrasp"
        )
        qpos_array = None
        arm_motion_allowed = (
            not planned_pregrasp or self._grasp_plan_selected is not None
        )
        if (
            arm_motion_allowed
            and planned_pregrasp
            and self.config.task.grasp_planning_waypoint_collision_gate_enabled
        ):
            qpos_array = self._validated_grasp_waypoint_qpos(action)
            arm_motion_allowed = qpos_array is not None

        if arm_motion_allowed:
            if (
                self.config.control.approach_velocity_control_enabled
                and action.command == "move_pregrasp"
            ):
                self._apply_approach_velocity(action)
            elif qpos_array is not None:
                self.robot.control_dofs_position(qpos_array[:7], self.arm_dofs)
            else:
                qpos = self.robot.inverse_kinematics(
                    link=self.end_effector,
                    pos=self.np.asarray(action.target_position),
                    quat=self.np.asarray(action.target_quaternion),
                )
                qpos_array = self.np.asarray(
                    qpos.detach().cpu() if hasattr(qpos, "detach") else qpos
                )
                if not self.np.isfinite(qpos_array).all():
                    raise RuntimeError(
                        f"IK returned a non-finite solution for {action.command}"
                    )
                self.robot.control_dofs_position(qpos_array[:7], self.arm_dofs)
        if (
            self.config.task.tri_suction_enabled
            and self.sample.handling_class == "suction_required"
        ):
            width = self.config.control.open_width_m
            self.robot.control_dofs_position(
                self.np.asarray((width, width)),
                self.finger_dofs,
            )
            self._suction_commanded = action.gripper <= 0
            if not self._suction_commanded:
                self._release_suction_attachment()
            return
        if action.gripper > 0:
            self._gripper_force_n = 0.0
            self._transport_slip_force_remaining_steps = 0
            self._transport_slip_last_force_limit_n = (
                self._close_force_limit_n()
            )
            width = self.config.control.open_width_m
            self.robot.control_dofs_position(self.np.asarray((width, width)), self.finger_dofs)
        else:
            force_limit_n = self._close_force_limit_n()
            if self._transport_slip_force_remaining_steps > 0:
                force_limit_n += self.config.control.transport_slip_force_boost_n
                self._transport_slip_force_remaining_steps -= 1
                self._transport_slip_active_steps += 1
            self._transport_slip_last_force_limit_n = force_limit_n
            self._gripper_force_n = min(
                force_limit_n,
                self._gripper_force_n + self.config.control.close_force_ramp_n_per_step,
            )
            force = self._gripper_force_n
            self.robot.control_dofs_force(self.np.asarray((-force, -force)), self.finger_dofs)

    def _close_force_limit_n(self) -> float:
        if self.sample.close_force_n is not None:
            return self.sample.close_force_n
        return self.config.control.close_force_n

    def _validated_grasp_waypoint_qpos(self, action: CartesianAction) -> Any | None:
        """Reject a pre-contact IK waypoint with a non-finger collision."""
        started = time.perf_counter_ns()
        self._grasp_waypoint_checks += 1
        self._grasp_waypoint_last_collision = ()
        original_qpos = self._flat_tuple(self.robot.get_qpos())
        qpos, ik_error = self.robot.inverse_kinematics(
            link=self.end_effector,
            pos=self.np.asarray(action.target_position),
            quat=self.np.asarray(action.target_quaternion),
            init_qpos=self.np.asarray(original_qpos),
            respect_joint_limit=True,
            max_samples=4,
            max_solver_iters=30,
            return_error=True,
        )
        qpos_values = list(self._flat_tuple(qpos))
        qpos_values[7:] = (
            self.config.control.open_width_m,
            self.config.control.open_width_m,
        )
        qpos_array = self.np.asarray(qpos_values)
        ik_error_values = self._flat_tuple(ik_error)
        finite = all(
            math.isfinite(value) for value in (*qpos_values, *ik_error_values)
        )
        kinematically_valid = (
            finite
            and math.sqrt(sum(value * value for value in ik_error_values[:3]))
            <= 0.005
            and math.sqrt(sum(value * value for value in ik_error_values[3:]))
            <= 0.05
        )
        collisions: tuple[dict[str, Any], ...] = ()
        restore_error = math.inf
        try:
            if kinematically_valid:
                segment_start = list(original_qpos)
                segment_start[7:] = (
                    self.config.control.open_width_m,
                    self.config.control.open_width_m,
                )
                segment = interpolate_joint_segment(
                    segment_start,
                    qpos_values,
                    max_joint_delta_rad=(
                        self.config.task.grasp_planning_joint_segment_resolution_rad
                    ),
                )
                self._grasp_waypoint_max_segment_samples = max(
                    self._grasp_waypoint_max_segment_samples,
                    len(segment),
                )
                for segment_qpos in segment:
                    self.robot.set_qpos(self.np.asarray(segment_qpos))
                    self._grasp_waypoint_collision_samples += 1
                    collisions = tuple(
                        collision
                        for collision in self._describe_robot_collisions()
                        if not (
                            collision["robot_link"]
                            in {"left_finger", "right_finger"}
                            and collision["other_is_parcel"]
                        )
                    )
                    if collisions:
                        break
        finally:
            self.robot.set_qpos(self.np.asarray(original_qpos))
            restored = self._flat_tuple(self.robot.get_qpos())
            restore_error = max(
                abs(value - reference)
                for value, reference in zip(restored, original_qpos, strict=True)
            )
        self._grasp_waypoint_last_restore_error = restore_error
        self._grasp_waypoint_compute_ms_total += (
            time.perf_counter_ns() - started
        ) / 1_000_000

        if kinematically_valid and not collisions and restore_error <= 1e-7:
            return qpos_array

        self._grasp_waypoint_rejections += 1
        self._grasp_waypoint_last_collision = collisions
        if self._grasp_plan_selected is not None:
            self._grasp_plan_rejected_candidate_ids.add(
                str(self._grasp_plan_selected["candidate_id"])
            )
        self._grasp_plan_selected = None
        self._grasp_plan_pending_replan = True
        self.expert.clear_planned_grasp_pose()
        return None

    def _apply_approach_velocity(self, action: CartesianAction) -> None:
        """Execute one bounded operational-space velocity command on the Radeon."""
        started = time.perf_counter_ns()
        actual_joint_velocity = self.robot.get_dofs_velocity(self.arm_dofs)
        current_position = self._flat_tuple(self.end_effector.get_pos())
        current_quaternion = self._flat_tuple(self.end_effector.get_quat())
        control = self.config.control
        twist_values = cartesian_velocity_twist(
            current_position,
            current_quaternion,
            action.target_position,
            action.target_quaternion,
            position_gain_s=control.approach_velocity_position_gain_s,
            orientation_gain_s=control.approach_velocity_orientation_gain_s,
            max_linear_m_s=control.approach_velocity_max_linear_m_s,
            max_angular_rad_s=control.approach_velocity_max_angular_rad_s,
        )
        jacobian = self.robot.get_jacobian(self.end_effector)[..., :7]
        twist = jacobian.new_tensor(twist_values)
        task_weights = jacobian.new_tensor(
            (1.0, 1.0, 1.0) + (control.approach_velocity_orientation_weight,) * 3
        )
        weighted_jacobian = jacobian * task_weights[:, None]
        weighted_twist = twist * task_weights
        joint_velocity = damped_least_squares_velocity(
            weighted_jacobian,
            weighted_twist,
            damping=control.approach_velocity_damping,
            max_joint_velocity=control.approach_velocity_max_joint_rad_s,
            array_module=self.torch,
        )
        if not bool(self.torch.isfinite(joint_velocity).all().item()):
            raise RuntimeError("approach velocity control produced a non-finite command")
        self.robot.control_dofs_velocity(joint_velocity, self.arm_dofs)
        predicted_twist = jacobian @ joint_velocity
        compute_ms = (time.perf_counter_ns() - started) / 1_000_000
        self._approach_velocity_samples += 1
        self._approach_velocity_compute_ms_total += compute_ms
        self._approach_velocity_max_joint_rad_s = max(
            self._approach_velocity_max_joint_rad_s,
            float(joint_velocity.abs().max().item()),
        )
        self._approach_velocity_max_pose_error_m = max(
            self._approach_velocity_max_pose_error_m,
            self._distance(current_position, action.target_position),
        )
        self._approach_velocity_last_twist = tuple(float(value) for value in twist_values)
        self._approach_velocity_last_joint_command = self._flat_tuple(joint_velocity)
        self._approach_velocity_last_predicted_twist = self._flat_tuple(predicted_twist)
        self._approach_velocity_last_actual_joint_velocity = self._flat_tuple(
            actual_joint_velocity
        )

    def _set_arm_stiffness_for_command(self, command: str) -> None:
        scale = (
            self.config.control.approach_stiffness_scale
            if command == "move_pregrasp"
            else 1.0
        )
        if math.isclose(scale, self._active_arm_stiffness_scale, rel_tol=0.0, abs_tol=1e-12):
            return
        control = self.config.control
        gains_kp, gains_kv = scaled_robot_gains(
            control.arm_kp,
            control.arm_kv,
            control.finger_kp,
            control.finger_kv,
            scale,
        )
        self.robot.set_dofs_kp(self.np.asarray(gains_kp))
        self.robot.set_dofs_kv(self.np.asarray(gains_kv))
        self._active_arm_stiffness_scale = scale

    def _configure_collision_checked_reset(self) -> None:
        if not self.config.control.collision_checked_reset_enabled:
            return
        started = time.perf_counter_ns()
        initial_pairs = self._robot_parcel_collision_pairs()
        self._initial_robot_parcel_collisions = self._describe_collision_pairs(
            initial_pairs
        )
        if initial_pairs:
            self.robot.set_qpos(
                self.np.asarray(self.config.control.collision_free_reset_qpos)
            )
            self._collision_checked_reset_used = True
            fallback_pairs = self._robot_parcel_collision_pairs()
            self._fallback_robot_parcel_collisions = self._describe_collision_pairs(
                fallback_pairs
            )
            if fallback_pairs:
                raise RuntimeError(
                    "collision-free reset pose still intersects the parcel: "
                    f"{self._fallback_robot_parcel_collisions}"
                )
        self._collision_checked_reset_compute_ms = (
            time.perf_counter_ns() - started
        ) / 1_000_000

    def _refresh_geometry_grasp_planning_active(self) -> None:
        self._geometry_grasp_planning_active = resolve_geometry_grasp_planning_active(
            planning_enabled=self.config.task.geometry_aware_grasp_planning_enabled,
            geometry_eligible=self._geometry_grasp_planning_eligible,
            reset_fallback_gate_enabled=(
                self.config.task.grasp_planning_reset_fallback_gate_enabled
            ),
            reset_fallback_used=self._collision_checked_reset_used,
        )

    def _robot_parcel_collision_pairs(self) -> tuple[tuple[int, int], ...]:
        return cross_entity_collision_pairs(
            self.robot.detect_collision(),
            (self.robot.geom_start, self.robot.geom_end),
            (self.parcel.geom_start, self.parcel.geom_end),
        )

    def _describe_collision_pairs(
        self,
        pairs: tuple[tuple[int, int], ...],
    ) -> tuple[dict[str, Any], ...]:
        descriptions = []
        for robot_geom_index, parcel_geom_index in pairs:
            robot_geom = self.scene.rigid_solver.geoms[robot_geom_index]
            parcel_geom = self.scene.rigid_solver.geoms[parcel_geom_index]
            descriptions.append(
                {
                    "robot_geom_index": robot_geom_index,
                    "robot_link": str(robot_geom.link.name),
                    "parcel_geom_index": parcel_geom_index,
                    "parcel_link": str(parcel_geom.link.name),
                }
            )
        return tuple(descriptions)

    def _filter_precontact_action(self, action: CartesianAction) -> CartesianAction:
        """Apply a geometry guard before IK while preserving the 8-D action contract."""
        self._aabb_guard_last_gap_m = None
        self._aabb_guard_last_compute_ms = 0.0
        self._aabb_guard_last_triggered = False
        self._aabb_guard_last_reason = None
        self._aabb_guard_last_nominal_target_m = None
        self._aabb_guard_last_filtered_target_m = None
        threshold = self.config.control.precontact_aabb_guard_distance_m
        if threshold is None or action.command != "move_pregrasp":
            self._aabb_guard_active_steps = 0
            return action

        started = time.perf_counter_ns()
        gap_m = self._finger_parcel_aabb_gap_m()
        compute_ms = (time.perf_counter_ns() - started) / 1_000_000
        self._aabb_guard_last_gap_m = gap_m
        self._aabb_guard_last_compute_ms = compute_ms
        self._aabb_guard_compute_ms_total += compute_ms
        self._aabb_guard_samples += 1

        current = self._flat_tuple(self.end_effector.get_pos())
        parcel = self._flat_tuple(self.parcel.get_pos())
        horizontal_distance = math.hypot(current[0] - parcel[0], current[1] - parcel[1])
        target_horizontal_distance = math.hypot(
            action.target_position[0] - parcel[0],
            action.target_position[1] - parcel[1],
        )
        nominal_step_m = self._distance(current, action.target_position)
        outside_descent_window = horizontal_distance > self.config.task.position_tolerance_m
        moving_toward_parcel = target_horizontal_distance < horizontal_distance - 1e-9
        if not (
            gap_m <= threshold
            and outside_descent_window
            and moving_toward_parcel
            and nominal_step_m > 1e-9
        ):
            self._aabb_guard_active_steps = 0
            return action

        transit_z = parcel[2] + self.expert.approach_clearance_m()
        if current[2] < transit_z - self.config.task.position_tolerance_m:
            guard_target = (
                current[0],
                current[1],
                min(transit_z, current[2] + nominal_step_m),
            )
            reason = "raise_to_transit"
        else:
            dx = current[0] - parcel[0]
            dy = current[1] - parcel[1]
            if horizontal_distance <= 1e-9:
                guard_target = (current[0], current[1], current[2] + nominal_step_m)
                reason = "raise_from_centerline"
            else:
                guard_target = (
                    current[0] + nominal_step_m * dx / horizontal_distance,
                    current[1] + nominal_step_m * dy / horizontal_distance,
                    current[2],
                )
                reason = "retreat_from_parcel"

        self._aabb_guard_filter_count += 1
        self._aabb_guard_active_steps += 1
        self._aabb_guard_max_active_steps = max(
            self._aabb_guard_max_active_steps,
            self._aabb_guard_active_steps,
        )
        self._aabb_guard_last_triggered = True
        self._aabb_guard_last_reason = reason
        self._aabb_guard_last_nominal_target_m = action.target_position
        self._aabb_guard_last_filtered_target_m = guard_target
        return CartesianAction(
            target_position=guard_target,
            target_quaternion=action.target_quaternion,
            gripper=action.gripper,
            command=action.command,
        )

    def _finger_parcel_aabb_gap_m(self) -> float:
        """Compute the closest finger-to-parcel AABB gap on the ROCm device."""
        parcel_aabb = self.parcel.get_AABB()
        finger_gaps = []
        for finger in (self.left_finger, self.right_finger):
            finger_aabb = finger.get_AABB()
            axis_gap = self.torch.clamp(
                self.torch.maximum(
                    finger_aabb[0] - parcel_aabb[1],
                    parcel_aabb[0] - finger_aabb[1],
                ),
                min=0.0,
            )
            finger_gaps.append(self.torch.linalg.vector_norm(axis_gap))
        return float(self.torch.stack(finger_gaps).min().item())

    def _finger_contact_tensors(self) -> tuple[Any, Any, Any, Any]:
        """Return finger contacts on-device with forces acting on the parcel."""
        contacts = self.robot.get_contacts(with_entity=self.parcel)
        required = {
            "link_a",
            "link_b",
            "position",
            "normal",
            "penetration",
            "force_a",
            "force_b",
        }
        missing = sorted(required - set(contacts))
        if missing:
            raise RuntimeError(
                "Genesis contact telemetry is missing fields: " + ", ".join(missing)
            )
        force_a = contacts["force_a"]
        self._contact_wrench_device = str(force_a.device)
        magnitudes = self.torch.linalg.vector_norm(force_a, dim=-1)
        mask = magnitudes >= self._contact_wrench_config.minimum_active_force_n
        if "valid_mask" in contacts:
            mask &= contacts["valid_mask"]
        link_a = contacts["link_a"]
        link_b = contacts["link_b"]
        left_index = int(self.left_finger.idx)
        right_index = int(self.right_finger.idx)
        parcel_start = int(self.parcel.link_start)
        parcel_end = int(self.parcel.link_end)
        finger_a = (link_a == left_index) | (link_a == right_index)
        finger_b = (link_b == left_index) | (link_b == right_index)
        parcel_a = (link_a >= parcel_start) & (link_a < parcel_end)
        parcel_b = (link_b >= parcel_start) & (link_b < parcel_end)
        finger_is_a = finger_a & parcel_b
        finger_is_b = finger_b & parcel_a
        mask &= finger_is_a | finger_is_b

        forces_on_parcel = self.torch.where(
            finger_is_a.unsqueeze(-1),
            contacts["force_b"],
            contacts["force_a"],
        )[mask]
        finger_links = self.torch.where(finger_is_a, link_a, link_b)[mask]
        finger_indices = self.torch.where(
            finger_links == left_index,
            self.torch.zeros_like(finger_links),
            self.torch.ones_like(finger_links),
        )
        return (
            contacts["position"][mask],
            forces_on_parcel,
            contacts["normal"][mask],
            finger_indices,
        )

    def _record_contact_wrench(self, physics_substep: int) -> None:
        if self._last_applied_command not in {
            "close_gripper",
            "hold",
            "move_lift",
            "move_drop",
        }:
            return
        started = time.perf_counter_ns()
        parcel_com = self.parcel.get_pos()
        positions, forces, normals, finger_indices = self._finger_contact_tensors()
        if self._contact_wrench_telemetry_backend == "rocm":
            quality = evaluate_contact_wrench_torch(
                positions,
                forces,
                normals,
                finger_indices,
                parcel_com,
                self._contact_wrench_config,
                self.torch,
            )
        else:
            packed_contacts = self.torch.cat(
                (
                    positions,
                    forces,
                    normals,
                    finger_indices.to(dtype=positions.dtype).unsqueeze(-1),
                ),
                dim=-1,
            ).detach().cpu().tolist()
            contact_points = tuple(
                ContactPoint(
                    finger_id=(
                        "left_finger" if round(row[9]) == 0 else "right_finger"
                    ),
                    position_world_m=tuple(float(value) for value in row[0:3]),
                    force_on_parcel_world_n=tuple(
                        float(value) for value in row[3:6]
                    ),
                    normal_world=tuple(float(value) for value in row[6:9]),
                )
                for row in packed_contacts
            )
            quality = evaluate_contact_wrench(
                contact_points,
                self._flat_tuple(parcel_com),
                self._contact_wrench_config,
            )
        compute_ms = (time.perf_counter_ns() - started) / 1_000_000
        event = {
            "control_step": self.control_step,
            "physics_substep": int(physics_substep),
            "command": self._last_applied_command,
            "transport_phase": self.expert.transport_phase,
            "parcel_lift_m": float(parcel_com[2].item() - self._initial_parcel_z),
            "compute_ms": compute_ms,
            **quality.to_dict(),
        }
        self._contact_wrench_samples += 1
        self._contact_wrench_compute_ms_total += compute_ms
        self._contact_wrench_last = event
        self._contact_wrench_events.append(event)

    def _record_contact_branch(self, physics_substep: int) -> None:
        """Record high-rate contact identities and finger dynamics read-only."""
        started = time.perf_counter_ns()
        control_inputs = self._robot_dof_control_inputs()
        contacts = self.robot.get_contacts()
        required = {
            "geom_a",
            "geom_b",
            "link_a",
            "link_b",
            "position",
            "normal",
            "penetration",
            "force_a",
            "force_b",
        }
        missing = sorted(required - set(contacts))
        if missing:
            raise RuntimeError(
                "Genesis contact-branch telemetry is missing fields: "
                + ", ".join(missing)
            )
        force_a = contacts["force_a"]
        self._contact_branch_device = str(force_a.device)
        magnitudes = self.torch.linalg.vector_norm(force_a, dim=-1)
        mask = magnitudes >= self._contact_wrench_config.minimum_active_force_n
        if "valid_mask" in contacts:
            mask &= contacts["valid_mask"]
        indices = self.torch.nonzero(mask, as_tuple=False).reshape(-1)

        geom_a_values = contacts["geom_a"].detach().cpu().tolist()
        geom_b_values = contacts["geom_b"].detach().cpu().tolist()
        link_a_values = contacts["link_a"].detach().cpu().tolist()
        link_b_values = contacts["link_b"].detach().cpu().tolist()
        position_values = contacts["position"].detach().cpu().tolist()
        normal_values = contacts["normal"].detach().cpu().tolist()
        penetration_values = contacts["penetration"].detach().cpu().tolist()
        force_a_values = force_a.detach().cpu().tolist()
        force_b_values = contacts["force_b"].detach().cpu().tolist()
        magnitude_values = magnitudes.detach().cpu().tolist()

        rows = []
        parcel_fingers: set[str] = set()
        peak_parcel_force_n = 0.0
        for tensor_index in indices.detach().cpu().tolist():
            index = int(tensor_index)
            geom_a = self._contact_geom_descriptor(int(geom_a_values[index]))
            geom_b = self._contact_geom_descriptor(int(geom_b_values[index]))
            if int(link_a_values[index]) != geom_a["link_index"]:
                raise RuntimeError("contact geom/link A identity mismatch")
            if int(link_b_values[index]) != geom_b["link_index"]:
                raise RuntimeError("contact geom/link B identity mismatch")
            force_magnitude_n = float(magnitude_values[index])
            roles = {geom_a["entity_role"], geom_b["entity_role"]}
            parcel_contact = roles == {"robot", "parcel"}
            finger_parcel_contact = False
            if parcel_contact:
                robot_geom = geom_a if geom_a["entity_role"] == "robot" else geom_b
                if robot_geom["link_name"] in {"left_finger", "right_finger"}:
                    finger_parcel_contact = True
                    parcel_fingers.add(str(robot_geom["link_name"]))
                    peak_parcel_force_n = max(
                        peak_parcel_force_n,
                        force_magnitude_n,
                    )
            rows.append(
                {
                    "geom_a": geom_a,
                    "geom_b": geom_b,
                    "position_m": [float(value) for value in position_values[index]],
                    "normal": [float(value) for value in normal_values[index]],
                    "penetration_m": float(penetration_values[index]),
                    "force_a_n": [float(value) for value in force_a_values[index]],
                    "force_b_n": [float(value) for value in force_b_values[index]],
                    "force_magnitude_n": force_magnitude_n,
                    "finger_parcel_contact": finger_parcel_contact,
                }
            )

        event = {
            "control_step": self.control_step,
            "physics_substep": int(physics_substep),
            "command": self._last_applied_command,
            "transport_phase": self.expert.transport_phase,
            "end_effector_pose": [
                *self._flat_tuple(self.end_effector.get_pos()),
                *self._flat_tuple(self.end_effector.get_quat()),
            ],
            "parcel_pose": [
                *self._flat_tuple(self.parcel.get_pos()),
                *self._flat_tuple(self.parcel.get_quat()),
            ],
            "finger_dof_position_m": list(
                self._flat_tuple(self.robot.get_dofs_position(self.finger_dofs))
            ),
            "finger_dof_velocity_m_s": list(
                self._flat_tuple(self.robot.get_dofs_velocity(self.finger_dofs))
            ),
            "finger_actual_force_n": list(
                self._flat_tuple(self.robot.get_dofs_force(self.finger_dofs))
            ),
            "finger_control_force_n": list(
                self._flat_tuple(
                    self.robot.get_dofs_control_force(self.finger_dofs)
                )
            ),
            "robot_qpos": list(self._flat_tuple(self.robot.get_qpos())),
            "robot_dof_velocity": list(
                self._flat_tuple(self.robot.get_dofs_velocity())
            ),
            "robot_dof_actual_force_n": list(
                self._flat_tuple(self.robot.get_dofs_force())
            ),
            "robot_dof_control_force_n": list(
                self._flat_tuple(self.robot.get_dofs_control_force())
            ),
            **control_inputs,
            "parcel_qpos": list(self._flat_tuple(self.parcel.get_qpos())),
            "parcel_dof_velocity": list(
                self._flat_tuple(self.parcel.get_dofs_velocity())
            ),
            "contact_count": len(rows),
            "parcel_contact_count": sum(
                bool(row["finger_parcel_contact"]) for row in rows
            ),
            "bilateral_parcel_contact": parcel_fingers
            == {"left_finger", "right_finger"},
            "peak_robot_contact_force_n": max(
                (float(row["force_magnitude_n"]) for row in rows),
                default=0.0,
            ),
            "peak_parcel_contact_force_n": peak_parcel_force_n,
            "contacts": rows,
        }
        self._contact_branch_compute_ms_total += (
            time.perf_counter_ns() - started
        ) / 1_000_000
        self._contact_branch_events.append(event)

    def _robot_dof_control_inputs(self) -> dict[str, list[float] | list[int]]:
        """Read raw Genesis controller modes and targets without changing them."""
        from genesis.utils.misc import qd_to_torch

        solver = self.scene.rigid_solver
        start = int(self.robot._dof_start)
        stop = start + int(self.robot.n_dofs)

        def entity_values(field: Any) -> tuple[float, ...]:
            values = qd_to_torch(field, transpose=True, copy=True)
            if values.ndim == 2:
                if values.shape[0] != 1:
                    raise RuntimeError(
                        "contact-branch control capture requires one environment"
                    )
                values = values[0]
            return self._flat_tuple(values[start:stop])

        modes = entity_values(solver.dyn_state.dofs.ctrl_mode)
        if any(not value.is_integer() or int(value) not in {0, 1, 2} for value in modes):
            raise RuntimeError(f"unsupported Genesis control modes: {modes}")
        return {
            "robot_dof_control_mode": [int(value) for value in modes],
            "robot_dof_position_target": list(
                entity_values(solver.dyn_state.dofs.ctrl_pos)
            ),
            "robot_dof_velocity_target": list(
                entity_values(solver.dyn_state.dofs.ctrl_vel)
            ),
            "robot_dof_force_target_n": list(
                entity_values(solver.dyn_state.dofs.ctrl_force)
            ),
        }

    def _contact_geom_descriptor(self, geom_index: int) -> dict[str, Any]:
        geom = self.scene.rigid_solver.geoms[geom_index]
        entity = geom.entity
        link = geom.link
        link_geoms = list(link.geoms)
        link_local_index = next(
            (
                index
                for index, candidate in enumerate(link_geoms)
                if int(candidate.idx) == geom_index
            ),
            None,
        )
        if link_local_index is None:
            raise RuntimeError(f"geom {geom_index} is not owned by its reported link")

        entity_role = self._contact_entity_role(entity)
        geom_role = f"collision_{link_local_index}"
        if (
            entity is self.robot
            and str(link.name) in {"left_finger", "right_finger"}
        ):
            adapter_index = len(link_geoms) - 1
            if (
                self.config.task.parcel_gripper_adapter_enabled
                and link_local_index == adapter_index
            ):
                geom_role = "parcel_adapter_collision"
            else:
                geom_role = f"stock_finger_collision_{link_local_index}"
        return {
            "entity_index": int(entity.idx),
            "entity_role": entity_role,
            "geom_index": geom_index,
            "geom_role": geom_role,
            "link_index": int(link.idx),
            "link_name": str(link.name),
            "link_local_geom_index": link_local_index,
        }

    def _contact_entity_role(self, entity: Any) -> str:
        if entity is self.robot:
            return "robot"
        if entity is self.parcel:
            return "parcel"
        if entity is self.plane:
            return "plane"
        for role, target in zip(
            ("left_bin", "right_bin"),
            self.sorting_targets,
            strict=True,
        ):
            if entity is target:
                return role
        return f"entity_{int(entity.idx)}"

    def _finger_contact(self) -> tuple[bool, float]:
        contacts = self.robot.get_contacts(with_entity=self.parcel)
        forces = contacts["force_a"]
        if forces.numel() == 0:
            return False, 0.0

        link_a = contacts["link_a"]
        link_b = contacts["link_b"]
        finger_ids = (self.left_finger.idx, self.right_finger.idx)
        mask = self.torch.zeros_like(link_a, dtype=self.torch.bool)
        finger_contacts = []
        for finger_id in finger_ids:
            finger_mask = (link_a == finger_id) | (link_b == finger_id)
            if "valid_mask" in contacts:
                finger_mask &= contacts["valid_mask"]
            finger_contacts.append(bool(finger_mask.any().item()))
            mask |= finger_mask
        if not bool(mask.any().item()):
            return False, 0.0
        magnitudes = self.torch.linalg.vector_norm(forces[mask], dim=-1)
        return all(finger_contacts), float(magnitudes.max().item())

    def _grasp_contact(self) -> tuple[bool, float]:
        if (
            self.config.task.tri_suction_enabled
            and self.sample.handling_class == "suction_required"
        ):
            sealed_count, contact_force_n = self._suction_seal_contact()
            attached = self._suction_attachment is not None
            return (
                attached
                or (
                    self._suction_commanded
                    and sealed_count >= self.config.task.tri_suction_min_sealed_cups
                ),
                max(contact_force_n, self._suction_last_force_n),
            )
        return self._finger_contact()

    def _suction_seal_contact(self) -> tuple[int, float]:
        if not self._suction_cup_geom_indices:
            return 0, 0.0
        contacts = self.robot.get_contacts(with_entity=self.parcel)
        forces = contacts["force_a"]
        if forces.numel() == 0:
            self._suction_physical_contact_cup_count = 0
            self._suction_geometric_seal_cup_count = 0
            self._suction_sealed_cup_count = 0
            return 0, 0.0
        geom_a = contacts["geom_a"]
        geom_b = contacts["geom_b"]
        valid = contacts.get("valid_mask")
        sealed: set[int] = set()
        mask = self.torch.zeros_like(geom_a, dtype=self.torch.bool)
        for geom_index in self._suction_cup_geom_indices:
            cup_mask = (geom_a == geom_index) | (geom_b == geom_index)
            if valid is not None:
                cup_mask &= valid
            if bool(cup_mask.any().item()):
                sealed.add(geom_index)
                mask |= cup_mask
        self._suction_physical_contact_cup_count = len(sealed)
        if not bool(mask.any().item()):
            self._suction_geometric_seal_cup_count = 0
            self._suction_sealed_cup_count = 0
            return len(sealed), 0.0
        magnitudes = self.torch.linalg.vector_norm(forces[mask], dim=-1)
        contact_force_n = float(magnitudes.max().item())
        geometric_count = self._geometric_suction_seal_count()
        self._suction_geometric_seal_cup_count = geometric_count
        self._suction_sealed_cup_count = max(len(sealed), geometric_count)
        return self._suction_sealed_cup_count, contact_force_n

    def _geometric_suction_seal_count(self) -> int:
        """Count cup lips that cover a contacted rigid box top surface."""

        dimensions = self.sample.dimensions_m
        if self.sample.shape != "box" or dimensions is None:
            return 0
        task = self.config.task
        hand_position = self._flat_tuple(self.end_effector.get_pos())
        hand_quaternion = self._flat_tuple(self.end_effector.get_quat())
        parcel_position = self._flat_tuple(self.parcel.get_pos())
        parcel_quaternion = self._flat_tuple(self.parcel.get_quat())
        world_to_parcel = quaternion_conjugate(parcel_quaternion)
        parcel_top_normal = rotate_vector(parcel_quaternion, (0.0, 0.0, 1.0))
        cup_axis = rotate_vector(hand_quaternion, (0.0, 0.0, 1.0))
        alignment = -sum(
            axis * normal
            for axis, normal in zip(cup_axis, parcel_top_normal, strict=True)
        )
        if alignment < math.cos(task.tri_suction_seal_angle_rad):
            return 0

        half_x, half_y, half_z = (value / 2.0 for value in dimensions)
        surface_margin = task.tri_suction_cup_radius_m * 0.5
        lip_z = task.tri_suction_tip_offset_m + task.tri_suction_cup_length_m
        sealed_count = 0
        for offset_x, offset_y, _ in tri_cup_offsets(
            task.tri_suction_footprint_radius_m
        ):
            cup_world = tuple(
                hand + relative
                for hand, relative in zip(
                    hand_position,
                    rotate_vector(
                        hand_quaternion,
                        (offset_x, offset_y, lip_z),
                    ),
                    strict=True,
                )
            )
            cup_local = rotate_vector(
                world_to_parcel,
                tuple(
                    cup - parcel
                    for cup, parcel in zip(cup_world, parcel_position, strict=True)
                ),
            )
            if (
                abs(cup_local[0]) <= max(0.0, half_x - surface_margin)
                and abs(cup_local[1]) <= max(0.0, half_y - surface_margin)
                and abs(cup_local[2] - half_z) <= task.tri_suction_seal_distance_m
            ):
                sealed_count += 1
        return sealed_count

    def _update_suction_attachment(self) -> None:
        if (
            not self.config.task.tri_suction_enabled
            or self.sample.handling_class != "suction_required"
        ):
            return
        if not self._suction_commanded:
            self._release_suction_attachment()
            return

        sealed_count, _ = self._suction_seal_contact()
        if (
            self._suction_attachment is None
            and sealed_count >= self.config.task.tri_suction_min_sealed_cups
        ):
            self._suction_attachment = create_attachment(
                self._flat_tuple(self.end_effector.get_pos()),
                self._flat_tuple(self.end_effector.get_quat()),
                self._flat_tuple(self.parcel.get_pos()),
                self._flat_tuple(self.parcel.get_quat()),
                sealed_cup_count=sealed_count,
            )
            self._suction_latch_count += 1
        if self._suction_attachment is None:
            self._zero_suction_wrench()
            return

        velocity = self._flat_tuple(self.parcel.get_dofs_velocity())
        if len(velocity) != 6:
            raise RuntimeError("a free parcel must expose six velocity DoFs")
        task = self.config.task
        wrench = compliant_suction_wrench(
            self._suction_attachment,
            self._flat_tuple(self.end_effector.get_pos()),
            self._flat_tuple(self.end_effector.get_quat()),
            self._flat_tuple(self.parcel.get_pos()),
            self._flat_tuple(self.parcel.get_quat()),
            velocity[:3],
            velocity[3:],
            translational_stiffness_n_m=(
                task.tri_suction_translational_stiffness_n_m
            ),
            translational_damping_n_s_m=(
                task.tri_suction_translational_damping_n_s_m
            ),
            rotational_stiffness_nm_rad=(
                task.tri_suction_rotational_stiffness_nm_rad
            ),
            rotational_damping_nm_s_rad=(
                task.tri_suction_rotational_damping_nm_s_rad
            ),
            max_force_n=task.tri_suction_max_force_n,
            max_torque_nm=(
                task.tri_suction_max_force_n
                * task.tri_suction_footprint_radius_m
            ),
            break_distance_m=task.tri_suction_break_distance_m,
            break_angle_rad=task.tri_suction_break_angle_rad,
        )
        self._suction_max_position_error_m = max(
            self._suction_max_position_error_m,
            wrench.position_error_m,
        )
        self._suction_max_orientation_error_rad = max(
            self._suction_max_orientation_error_rad,
            wrench.orientation_error_rad,
        )
        if wrench.broken:
            self._suction_break_count += 1
            self._release_suction_attachment()
            return
        self._suction_last_force_n = math.sqrt(
            sum(value * value for value in wrench.force_world_n)
        )
        self._suction_last_torque_nm = math.sqrt(
            sum(value * value for value in wrench.torque_world_nm)
        )
        self._suction_max_force_n = max(
            self._suction_max_force_n,
            self._suction_last_force_n,
        )
        self.parcel.control_dofs_force(
            self.np.asarray((*wrench.force_world_n, *wrench.torque_world_nm))
        )

    def _release_suction_attachment(self) -> None:
        self._suction_attachment = None
        self._suction_sealed_cup_count = 0
        self._suction_physical_contact_cup_count = 0
        self._suction_geometric_seal_cup_count = 0
        self._zero_suction_wrench()

    def _zero_suction_wrench(self) -> None:
        self._suction_last_force_n = 0.0
        self._suction_last_torque_nm = 0.0
        if hasattr(self, "parcel"):
            self.parcel.control_dofs_force(self.np.zeros(6, dtype=self.np.float32))

    def _render_camera(self) -> None:
        if self.camera is None:
            return
        rgb, depth, _, _ = self.camera.render(
            rgb=self.config.sensors.rgb or self._video_path is not None,
            depth=self.config.sensors.depth,
        )
        if rgb is not None:
            self._latest_rgb = self.np.asarray(rgb)[..., :3]
        if depth is not None:
            self._latest_depth = genesis_depth_to_meters(depth, self.np)
        if self.wrist_camera is not None:
            hand_position = self._flat_tuple(self.end_effector.get_pos())
            hand_quaternion = self._flat_tuple(self.end_effector.get_quat())
            position, lookat, up = wrist_camera_pose(
                hand_position, hand_quaternion, self.np
            )
            self.wrist_camera.set_pose(pos=position, lookat=lookat, up=up)
            self.wrist_camera.render(rgb=True, depth=False)

    @staticmethod
    def _distance(left: tuple[float, ...], right: tuple[float, ...]) -> float:
        return math.sqrt(sum((a - b) ** 2 for a, b in zip(left, right, strict=True)))

    @staticmethod
    def _flat_tuple(value: Any) -> tuple[float, ...]:
        if hasattr(value, "detach"):
            value = value.detach().cpu().numpy()
        return tuple(float(item) for item in value.reshape(-1))

    def __enter__(self) -> "GenesisParcelEnv":
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()
