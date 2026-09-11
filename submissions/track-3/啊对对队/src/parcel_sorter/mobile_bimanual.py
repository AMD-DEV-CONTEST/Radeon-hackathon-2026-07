"""Mobile bimanual embodiment and deterministic task allocation.

The generated robot derives from Genesis' Apache-2.0 ``bi-franka_panda``
asset.  This module adds an original planar wheeled base and keeps navigation
and manipulation interfaces separate so the existing single-arm policies can
remain a controlled baseline.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
import xml.etree.ElementTree as ET

from .suction import tri_cup_offsets


BASE_JOINT_NAMES = ("mobile_base_x", "mobile_base_y", "mobile_base_yaw")
ARM_JOINT_NAMES = {
    "left": tuple(f"panda0_joint{index}" for index in range(1, 8)),
    "right": tuple(f"panda1_joint{index}" for index in range(1, 8)),
}
FINGER_JOINT_NAMES = {
    "left": ("panda0_finger_joint1", "panda0_finger_joint2"),
    "right": ("panda1_finger_joint1", "panda1_finger_joint2"),
}
END_EFFECTOR_LINK_NAMES = {
    "left": "panda0_gripper",
    "right": "panda1_gripper",
}
UPSTREAM_MODEL = "Genesis franka_sim/bi-franka_panda.xml"
UPSTREAM_LICENSE = "Apache-2.0"
MOBILE_TRI_SUCTION_TIP_OFFSET_M = 0.190
MOBILE_TRI_SUCTION_CUP_LENGTH_M = 0.010


@dataclass(frozen=True)
class PlanarBaseCommand:
    velocity_x_m_s: float
    velocity_y_m_s: float
    yaw_rate_rad_s: float
    distance_to_goal_m: float
    reached: bool


@dataclass(frozen=True)
class BimanualAssignment:
    mode: str
    primary_arm: str
    support_arm: str | None
    reason: str


@dataclass(frozen=True)
class PlanarObstacle:
    center_xy_m: tuple[float, float]
    half_extent_xy_m: tuple[float, float]


def joint_dof_indices(robot: object, joint_names: tuple[str, ...]) -> tuple[int, ...]:
    """Resolve named one-DoF joints and reject ambiguous control maps."""

    if not joint_names:
        raise ValueError("joint_names cannot be empty")
    indices: list[int] = []
    for name in joint_names:
        joint = robot.get_joint(name)  # type: ignore[attr-defined]
        local = tuple(int(value) for value in joint.dofs_idx_local)
        if len(local) != 1:
            raise ValueError(f"joint {name!r} must expose exactly one DoF")
        indices.append(local[0])
    if len(indices) != len(set(indices)):
        raise ValueError("joint map contains duplicate DoF indices")
    return tuple(indices)


def planar_base_command(
    current_pose_xy_yaw: tuple[float, float, float],
    goal_xy: tuple[float, float],
    *,
    max_linear_speed_m_s: float = 0.50,
    max_yaw_rate_rad_s: float = 1.20,
    position_tolerance_m: float = 0.04,
) -> PlanarBaseCommand:
    """Return a bounded holonomic-base command in world coordinates."""

    values = (*current_pose_xy_yaw, *goal_xy, max_linear_speed_m_s, max_yaw_rate_rad_s)
    if any(not math.isfinite(value) for value in values):
        raise ValueError("base pose, goal, and limits must be finite")
    if min(max_linear_speed_m_s, max_yaw_rate_rad_s, position_tolerance_m) <= 0:
        raise ValueError("base limits and tolerance must be positive")
    dx = goal_xy[0] - current_pose_xy_yaw[0]
    dy = goal_xy[1] - current_pose_xy_yaw[1]
    distance = math.hypot(dx, dy)
    if distance <= position_tolerance_m:
        return PlanarBaseCommand(0.0, 0.0, 0.0, distance, True)
    scale = min(1.0, max_linear_speed_m_s / max(distance, 1e-12))
    desired_yaw = math.atan2(dy, dx)
    yaw_error = _wrap_angle(desired_yaw - current_pose_xy_yaw[2])
    return PlanarBaseCommand(
        velocity_x_m_s=dx * scale,
        velocity_y_m_s=dy * scale,
        yaw_rate_rad_s=max(-max_yaw_rate_rad_s, min(max_yaw_rate_rad_s, 2.0 * yaw_error)),
        distance_to_goal_m=distance,
        reached=False,
    )


def assign_bimanual_roles(
    *,
    parcel_lateral_y_m: float,
    parcel_longest_dimension_m: float,
    parcel_mass_kg: float,
    cooperative_length_threshold_m: float = 0.28,
    cooperative_mass_threshold_kg: float = 1.50,
) -> BimanualAssignment:
    """Assign one-arm or cooperative transport without using test outcomes."""

    values = (
        parcel_lateral_y_m,
        parcel_longest_dimension_m,
        parcel_mass_kg,
        cooperative_length_threshold_m,
        cooperative_mass_threshold_kg,
    )
    if any(not math.isfinite(value) for value in values):
        raise ValueError("assignment inputs must be finite")
    if min(parcel_longest_dimension_m, parcel_mass_kg) <= 0:
        raise ValueError("parcel size and mass must be positive")
    primary = "left" if parcel_lateral_y_m >= 0.0 else "right"
    support = "right" if primary == "left" else "left"
    if (
        parcel_longest_dimension_m >= cooperative_length_threshold_m
        or parcel_mass_kg >= cooperative_mass_threshold_kg
    ):
        return BimanualAssignment(
            mode="cooperative_carry",
            primary_arm=primary,
            support_arm=support,
            reason="parcel exceeds single-arm length or mass threshold",
        )
    return BimanualAssignment(
        mode="single_arm_sort",
        primary_arm=primary,
        support_arm=None,
        reason="nearest-arm assignment within single-arm envelope",
    )


def plan_detour_waypoints(
    start_xy_m: tuple[float, float],
    goal_xy_m: tuple[float, float],
    obstacles: tuple[PlanarObstacle, ...],
    *,
    clearance_m: float,
) -> tuple[tuple[float, float], ...]:
    """Plan deterministic shortest-side detours around inflated AABBs."""

    if clearance_m <= 0 or not math.isfinite(clearance_m):
        raise ValueError("navigation clearance must be finite and positive")
    waypoints: list[tuple[float, float]] = []
    segment_start = start_xy_m
    for obstacle in obstacles:
        if any(value <= 0 for value in obstacle.half_extent_xy_m):
            raise ValueError("obstacle half extents must be positive")
        bounds = (
            obstacle.center_xy_m[0] - obstacle.half_extent_xy_m[0] - clearance_m,
            obstacle.center_xy_m[0] + obstacle.half_extent_xy_m[0] + clearance_m,
            obstacle.center_xy_m[1] - obstacle.half_extent_xy_m[1] - clearance_m,
            obstacle.center_xy_m[1] + obstacle.half_extent_xy_m[1] + clearance_m,
        )
        if not _segment_intersects_aabb(segment_start, goal_xy_m, bounds):
            continue
        left_x, right_x, bottom_y, top_y = bounds
        candidates = (
            ((left_x, bottom_y), (right_x, bottom_y)),
            ((left_x, top_y), (right_x, top_y)),
        )
        selected = min(
            candidates,
            key=lambda route: (
                math.dist(segment_start, route[0])
                + math.dist(route[0], route[1])
                + math.dist(route[1], goal_xy_m)
            ),
        )
        waypoints.extend(selected)
        segment_start = selected[-1]
    waypoints.append(goal_xy_m)
    return tuple(waypoints)


def build_mobile_bimanual_mjcf(
    source_path: str | Path,
    output_path: str | Path,
    *,
    left_tri_suction: bool = False,
    right_v_cradle: bool = False,
) -> Path:
    """Add an original planar wheeled base to the upstream Bi-Franka model."""

    source = Path(source_path).resolve()
    output = Path(output_path).resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Bi-Franka MJCF source does not exist: {source}")
    output.parent.mkdir(parents=True, exist_ok=True)
    parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))
    tree = ET.parse(source, parser=parser)
    root = tree.getroot()
    if root.tag != "mujoco":
        raise ValueError("mobile bimanual source must be a MuJoCo model")
    compiler = root.find("compiler")
    if compiler is None:
        raise ValueError("Bi-Franka MJCF is missing compiler configuration")
    compiler.set("angle", "radian")
    compiler.set("meshdir", str(source.parent))
    for include in root.findall(".//include"):
        include_path = source.parent / include.attrib["file"]
        if not include_path.is_file():
            raise FileNotFoundError(f"Bi-Franka include does not exist: {include_path}")
        include.set("file", str(include_path.resolve()))

    if left_tri_suction:
        _patch_mobile_tool_chain(
            root,
            arm_body_name="leftarm",
            gripper_name="panda0_gripper",
            output_path=output.parent / "mobile_chain0_tri_suction.xml",
            tool="tri_suction",
        )
    if right_v_cradle:
        _patch_mobile_tool_chain(
            root,
            arm_body_name="rightarm",
            gripper_name="panda1_gripper",
            output_path=output.parent / "mobile_chain1_v_cradle.xml",
            tool="v_cradle",
        )

    torso = root.find(".//body[@name='torso']")
    if torso is None:
        raise ValueError("Bi-Franka MJCF is missing torso body")
    for index, (name, joint_type, axis, damping) in enumerate(
        (
            (BASE_JOINT_NAMES[0], "slide", "1 0 0", "120"),
            (BASE_JOINT_NAMES[1], "slide", "0 1 0", "120"),
            (BASE_JOINT_NAMES[2], "hinge", "0 0 1", "80"),
        )
    ):
        torso.insert(
            index,
            ET.Element(
                "joint",
                {
                    "name": name,
                    "type": joint_type,
                    "axis": axis,
                    "limited": "false",
                    "damping": damping,
                    "armature": "0.5",
                },
            ),
        )
    torso.insert(
        3,
        ET.Element(
            "inertial",
            {
                "mass": "85",
                "pos": "0 0 0.55",
                "diaginertia": "12 10 8",
            },
        ),
    )
    physical_geoms = (
        {
            "name": "mobile_chassis_collision",
            "type": "box",
            "size": "0.34 0.26 0.10",
            "pos": "0 0 0.20",
            "group": "3",
            "contype": "1",
            "conaffinity": "1",
            "rgba": "0.10 0.13 0.16 1",
        },
        {
            "name": "mobile_chassis_visual",
            "type": "box",
            "size": "0.35 0.27 0.11",
            "pos": "0 0 0.20",
            "group": "2",
            "contype": "0",
            "conaffinity": "0",
            "rgba": "0.08 0.46 0.68 1",
        },
    )
    for attributes in physical_geoms:
        torso.append(ET.Element("geom", attributes))
    for index, (x, y) in enumerate(
        ((0.25, 0.28), (0.25, -0.28), (-0.25, 0.28), (-0.25, -0.28))
    ):
        torso.append(
            ET.Element(
                "geom",
                {
                    "name": f"mobile_wheel_{index}_visual",
                    "type": "cylinder",
                    "size": "0.085 0.035",
                    "pos": f"{x} {y} 0.12",
                    "quat": "0.7071067812 0.7071067812 0 0",
                    "group": "2",
                    "contype": "0",
                    "conaffinity": "0",
                    "rgba": "0.03 0.03 0.03 1",
                },
            )
        )
    root.insert(
        0,
        ET.Comment(
            " Generated mobile base and controller interface are original project work; "
            "upstream Bi-Franka remains Apache-2.0. "
        ),
    )
    tree.write(output, encoding="utf-8", xml_declaration=True)
    return output


def _patch_mobile_tool_chain(
    root: ET.Element,
    *,
    arm_body_name: str,
    gripper_name: str,
    output_path: Path,
    tool: str,
) -> None:
    arm = root.find(f".//body[@name='{arm_body_name}']")
    if arm is None:
        raise ValueError(f"Bi-Franka MJCF is missing {arm_body_name}")
    include = arm.find("include")
    if include is None:
        raise ValueError(f"{arm_body_name} must include a chain asset")
    chain_source = Path(include.attrib["file"])
    if not chain_source.is_file():
        raise FileNotFoundError(f"Bi-Franka chain does not exist: {chain_source}")
    chain_tree = ET.parse(chain_source)
    chain_root = chain_tree.getroot()
    gripper = chain_root.find(f".//body[@name='{gripper_name}']")
    if gripper is None:
        raise ValueError(f"Bi-Franka chain is missing {gripper_name}")
    if tool == "tri_suction":
        _disable_stock_gripper_collisions(gripper)
        _append_tri_suction_geometries(gripper)
    elif tool == "v_cradle":
        _append_v_cradle_geometries(gripper)
    else:
        raise ValueError(f"unsupported mobile tool: {tool}")
    chain_tree.write(output_path, encoding="utf-8", xml_declaration=True)
    include.set("file", str(output_path.resolve()))


def _disable_stock_gripper_collisions(gripper: ET.Element) -> None:
    """Turn the Panda gripper into a dedicated suction tool.

    The finger bodies and joints remain available to the upstream model, but their
    geometry must not be rendered or collide. Keeping visible fingers after
    disabling their collision makes valid suction contact look like penetration.
    """

    for geom in gripper.findall("./geom"):
        if geom.attrib.get("class", "").endswith("_col"):
            geom.set("contype", "0")
            geom.set("conaffinity", "0")
    for finger in gripper.findall("./body"):
        for parent in finger.iter():
            for geom in tuple(parent.findall("geom")):
                parent.remove(geom)


def _append_tri_suction_geometries(gripper: ET.Element) -> None:
    cup_radius = 0.012
    cup_center_z = MOBILE_TRI_SUCTION_TIP_OFFSET_M - MOBILE_TRI_SUCTION_CUP_LENGTH_M / 2.0
    cup_size = f"{cup_radius:.9f} {MOBILE_TRI_SUCTION_CUP_LENGTH_M / 2.0:.9f}"
    visual_only = {"group": "2", "contype": "0", "conaffinity": "0"}

    ET.SubElement(
        gripper,
        "geom",
        {
            "name": "mobile_left_suction_manifold_visual",
            "type": "cylinder",
            "size": "0.048000000 0.009000000",
            "pos": "0 0 0.105000000",
            "rgba": "0.04 0.34 0.14 1",
            **visual_only,
        },
    )
    for index, (x, y, _) in enumerate(tri_cup_offsets(0.035)):
        stem_start_z = 0.114
        stem_end_z = cup_center_z - MOBILE_TRI_SUCTION_CUP_LENGTH_M / 2.0
        stem_length = stem_end_z - stem_start_z
        ET.SubElement(
            gripper,
            "geom",
            {
                "name": f"mobile_left_suction_stem_{index}_visual",
                "type": "cylinder",
                "size": f"0.004500000 {stem_length / 2.0:.9f}",
                "pos": f"{x:.9f} {y:.9f} {stem_start_z + stem_length / 2.0:.9f}",
                "rgba": "0.08 0.58 0.26 1",
                **visual_only,
            },
        )
        ET.SubElement(
            gripper,
            "geom",
            {
                "name": f"mobile_left_suction_bell_{index}_visual",
                "type": "cylinder",
                "size": "0.015000000 0.004000000",
                "pos": f"{x:.9f} {y:.9f} {stem_end_z - 0.004:.9f}",
                "rgba": "0.06 0.50 0.21 1",
                **visual_only,
            },
        )
        position = f"{x:.9f} {y:.9f} {cup_center_z:.9f}"
        ET.SubElement(
            gripper,
            "geom",
            {
                "name": f"mobile_left_suction_cup_{index}_collision",
                "type": "cylinder",
                "size": cup_size,
                "pos": position,
                "density": "1100",
                "group": "3",
                "rgba": "0.10 0.82 0.38 1",
            },
        )
        ET.SubElement(
            gripper,
            "geom",
            {
                "name": f"mobile_left_suction_cup_{index}_visual",
                "type": "cylinder",
                "size": "0.012500000 0.004500000",
                "pos": f"{x:.9f} {y:.9f} {cup_center_z - 0.0005:.9f}",
                "rgba": "0.12 0.90 0.42 1",
                **visual_only,
            },
        )


def _append_v_cradle_geometries(gripper: ET.Element) -> None:
    for side, sign in (("left", -1.0), ("right", 1.0)):
        attributes = {
            "type": "box",
            "size": "0.012 0.050 0.070",
            "pos": f"{sign * 0.043:.6f} 0 0.204",
            "euler": f"0 {sign * 0.55:.6f} 0",
        }
        ET.SubElement(
            gripper,
            "geom",
            {
                **attributes,
                "name": f"mobile_right_v_cradle_{side}_collision",
                "density": "1240",
                "group": "3",
            },
        )
        ET.SubElement(
            gripper,
            "geom",
            {
                **attributes,
                "name": f"mobile_right_v_cradle_{side}_visual",
                "group": "2",
                "contype": "0",
                "conaffinity": "0",
                "rgba": "0.95 0.58 0.10 1",
            },
        )


def _wrap_angle(angle: float) -> float:
    return (angle + math.pi) % (2.0 * math.pi) - math.pi


def _segment_intersects_aabb(
    start: tuple[float, float],
    end: tuple[float, float],
    bounds: tuple[float, float, float, float],
) -> bool:
    """Liang-Barsky segment/AABB test with inclusive safety boundaries."""

    left, right, bottom, top = bounds
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    lower = 0.0
    upper = 1.0
    for p, q in (
        (-dx, start[0] - left),
        (dx, right - start[0]),
        (-dy, start[1] - bottom),
        (dy, top - start[1]),
    ):
        if abs(p) <= 1e-12:
            if q < 0:
                return False
            continue
        ratio = q / p
        if p < 0:
            lower = max(lower, ratio)
        else:
            upper = min(upper, ratio)
        if lower > upper:
            return False
    return True
