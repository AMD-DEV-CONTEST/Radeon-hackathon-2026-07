"""Single-scene mobile manipulation with the official Franka MJCF gripper.

The navigation planner works in the 6 x 6 metre room frame.  Manipulation
targets are specified in the successful fixed-base Franka scene's local frame.
This module adds three planar root joints to a generated copy of the official
MJCF, converts local targets through the measured docking pose, and keeps the
same physical object in the gripper while the base follows the delivery path.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, replace
import json
import math
import os
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

try:
    import numpy as np
except ModuleNotFoundError:  # Coordinate/XML unit tests run without cloud deps.
    np = None

from .mjcf_reference import UPSTREAM_COMMIT, UPSTREAM_URL, resolve_reference_root
from .spatial_tasks import SEMANTIC_DOCKS, build_room_grid, generate_task, plan_transport


PLACE_TARGET = "024_bowl"
ARM_QPOS = (0.0, -0.3, 0.0, -2.0, 0.0, 1.7, 0.79)
OPEN = 0.04
CLOSE_FORCE = -12.0


@dataclass(frozen=True)
class PlanarPose:
    """A planar rigid transform from the Franka-local frame to room world."""

    x: float
    y: float
    yaw: float

    @property
    def rotation(self) -> tuple[tuple[float, float], tuple[float, float]]:
        c, s = math.cos(self.yaw), math.sin(self.yaw)
        return ((c, -s), (s, c))

    def local_to_world(self, point) -> list[float]:
        result = [float(value) for value in point]
        c, s = self.rotation[0][0], self.rotation[1][0]
        px, py = result[:2]
        result[:2] = [self.x + c * px - s * py, self.y + s * px + c * py]
        return result

    def world_to_local(self, point) -> list[float]:
        result = [float(value) for value in point]
        c, s = self.rotation[0][0], self.rotation[1][0]
        dx, dy = result[0] - self.x, result[1] - self.y
        result[:2] = [c * dx + s * dy, -s * dx + c * dy]
        return result

    def matrix(self) -> list[list[float]]:
        c, s = self.rotation[0][0], self.rotation[1][0]
        return [
            [c, -s, 0.0, self.x],
            [s, c, 0.0, self.y],
            [0.0, 0.0, 1.0, 0.0],
            [0.0, 0.0, 0.0, 1.0],
        ]


@dataclass(frozen=True)
class PhysicalObjectProfile:
    """Controlled object geometry and dynamics for multi-object evaluation."""

    name: str
    size_xyz_m: tuple[float, float, float]
    mass_kg: float
    friction: float
    color_rgba: tuple[float, float, float, float]
    close_force_n: float = -12.0
    yaw_deg: float = 0.0

    @property
    def density_kg_m3(self) -> float:
        volume = math.prod(self.size_xyz_m)
        return self.mass_kg / volume


OBJECT_PROFILES: dict[str, PhysicalObjectProfile] = {
    "parcel_small": PhysicalObjectProfile(
        "parcel_small", (0.035, 0.035, 0.050), 0.025, 2.5, (0.98, 0.72, 0.20, 1.0)
    ),
    "parcel_medium": PhysicalObjectProfile(
        "parcel_medium", (0.045, 0.045, 0.070), 0.040, 3.0, (0.94, 0.48, 0.12, 1.0)
    ),
    "parcel_wide": PhysicalObjectProfile(
        "parcel_wide", (0.060, 0.040, 0.055), 0.090, 2.8, (0.30, 0.65, 0.92, 1.0)
    ),
    "carton_tall": PhysicalObjectProfile(
        "carton_tall", (0.040, 0.040, 0.100), 0.120, 2.7, (0.42, 0.76, 0.40, 1.0)
    ),
    "package_heavy": PhysicalObjectProfile(
        "package_heavy",
        (0.050, 0.040, 0.060),
        0.200,
        3.2,
        (0.62, 0.43, 0.82, 1.0),
        close_force_n=-14.0,
    ),
}


@dataclass
class SlipDetector:
    """Detect payload drift continuously in the hand-relative frame."""

    desired_relative_xyz: tuple[float, float, float]
    dt: float = 0.01
    drift_threshold_m: float = 0.025
    velocity_threshold_m_s: float = 0.12
    consecutive_required: int = 2
    previous_relative_xyz: tuple[float, float, float] | None = None
    consecutive_count: int = 0
    max_drift_m: float = 0.0
    max_slip_velocity_m_s: float = 0.0

    def observe(self, relative_xyz) -> dict | None:
        relative = tuple(float(value) for value in relative_xyz)
        drift = math.dist(relative, self.desired_relative_xyz)
        velocity = 0.0
        if self.previous_relative_xyz is not None:
            velocity = math.dist(relative, self.previous_relative_xyz) / self.dt
        self.previous_relative_xyz = relative
        self.max_drift_m = max(self.max_drift_m, drift)
        self.max_slip_velocity_m_s = max(self.max_slip_velocity_m_s, velocity)
        suspicious = drift >= self.drift_threshold_m or (
            drift >= self.drift_threshold_m * 0.5
            and velocity >= self.velocity_threshold_m_s
        )
        self.consecutive_count = self.consecutive_count + 1 if suspicious else 0
        if self.consecutive_count < self.consecutive_required:
            return None
        return {
            "relative_xyz": list(relative),
            "drift_m": drift,
            "slip_velocity_m_s": velocity,
            "trigger": (
                "relative_drift"
                if drift >= self.drift_threshold_m
                else "slip_velocity"
            ),
        }

    def reset_observation(self, relative_xyz) -> None:
        self.previous_relative_xyz = tuple(float(value) for value in relative_xyz)
        self.consecutive_count = 0


def unload_instability_reasons(
    *,
    bilateral_contact: bool,
    relative_drift_m: float,
    hand_payload_distance_m: float,
    drift_threshold_m: float,
    preloss_distance_m: float,
) -> list[str]:
    """Return the independently measured reasons to stop tray unloading."""
    reasons = []
    if not bilateral_contact:
        reasons.append("bilateral_finger_contact_lost")
    if relative_drift_m >= drift_threshold_m:
        reasons.append("hand_relative_payload_drift")
    if hand_payload_distance_m >= preloss_distance_m:
        reasons.append("preloss_distance_threshold")
    return reasons


def docking_pose(zone: str) -> PlanarPose:
    """Face local +x toward furniture on the nearest north/south room wall."""
    x, y = SEMANTIC_DOCKS[zone]
    return PlanarPose(x, y, math.copysign(math.pi / 2, y))


def delivery_pose_with_payload_heading(source_zone: str, target_zone: str) -> PlanarPose:
    """Use holonomic translation while preserving the verified grasp heading."""
    source = docking_pose(source_zone)
    target_x, target_y = SEMANTIC_DOCKS[target_zone]
    return PlanarPose(target_x, target_y, source.yaw)


WORK_SURFACE_SIZE_M = (0.90, 0.80, 0.05)
WORK_SURFACE_NEAR_EDGE_M = 0.20
PICKUP_OBJECT_LOCAL_X_M = 0.34
PLACE_TARGET_LOCAL_X_M = 0.55


def work_surface_center_local_x() -> float:
    """Keep the tabletop entirely in front of the mobile Franka base."""
    return WORK_SURFACE_NEAR_EDGE_M + WORK_SURFACE_SIZE_M[0] / 2.0


def prepare_planar_franka_mjcf(reference_root: Path, output_dir: Path) -> Path:
    """Generate a planar-root copy while preserving official finger geometry."""
    source = reference_root / "assets" / "robots" / "franka" / "panda.xml"
    if not source.is_file():
        raise FileNotFoundError(f"Official Franka MJCF not found: {source}")
    tree = ET.parse(source)
    root = tree.getroot()
    compiler = root.find("compiler")
    if compiler is None:
        raise ValueError("Official Franka MJCF has no <compiler> element")
    compiler.set("meshdir", str((source.parent / "assets").resolve()))
    link0 = root.find("./worldbody/body[@name='link0']")
    if link0 is None:
        raise ValueError("Official Franka MJCF has no link0 root body")

    joints = (
        {
            "name": "base_x",
            "type": "slide",
            "axis": "1 0 0",
            "range": "-10 10",
            "limited": "true",
            "damping": "80",
            "armature": "0",
        },
        {
            "name": "base_y",
            "type": "slide",
            "axis": "0 1 0",
            "range": "-10 10",
            "limited": "true",
            "damping": "80",
            "armature": "0",
        },
        {
            "name": "base_yaw",
            "type": "hinge",
            "axis": "0 0 1",
            "range": "-6.283185 6.283185",
            "limited": "true",
            "damping": "60",
            "armature": "0",
        },
    )
    for attributes in reversed(joints):
        link0.insert(0, ET.Element("joint", attributes))

    # The upstream link0 collision includes fixed tabletop-mounting geometry
    # and blocks a mobile base long before the visible root reaches furniture.
    # Replace only that mounting collision with a bounded mobile-root proxy;
    # all seven arm links, the hand, and the official fingertip pads remain
    # collidable.
    for geom in link0.findall("geom"):
        if geom.get("mesh") == "link0_c":
            geom.set("contype", "0")
            geom.set("conaffinity", "0")
    link0.insert(
        len(joints),
        ET.Element(
            "geom",
            {
                "name": "mobile_root_collision_proxy",
                "type": "cylinder",
                "size": "0.22 0.10",
                "pos": "0 0 -0.65",
                "rgba": "0.16 0.22 0.30 0",
                "friction": "1.0 0.01 0.001",
                "mass": "0.01",
            },
        ),
    )

    # Visual-only mobile pedestal.  Navigation safety is evaluated by the
    # inflated A* footprint, while the official arm/finger collision geometry
    # remains untouched.
    link0.insert(
        len(joints) + 1,
        ET.Element(
            "geom",
            {
                "name": "mobile_pedestal_visual",
                "type": "cylinder",
                "size": "0.24 0.10",
                "pos": "0 0 -0.65",
                "rgba": "0.16 0.22 0.30 1",
                "contype": "0",
                "conaffinity": "0",
                "mass": "0",
            },
        ),
    )
    link0.insert(
        len(joints) + 2,
        ET.Element(
            "geom",
            {
                "name": "mobile_column_visual",
                "type": "cylinder",
                "size": "0.08 0.28",
                "pos": "0 0 -0.32",
                "rgba": "0.36 0.42 0.50 1",
                "contype": "0",
                "conaffinity": "0",
                "mass": "0",
            },
        ),
    )
    # A physical support tray under the low carry pose. Tall/heavy payloads
    # remain gripped, but downward slip can settle onto this base-mounted
    # surface instead of falling. This is ordinary collision contact: no weld,
    # latch, teleport, or kinematic attachment is introduced.
    tray_body = ET.Element(
        "body",
        {
            "name": "payload_tray_body",
            "pos": "-0.20 -0.05 0.05",
        },
    )
    ET.SubElement(
        tray_body,
        "joint",
        {
            "name": "tray_slide",
            "type": "slide",
            "axis": "1 0 0",
            "range": "0 0.46",
            "limited": "true",
            "damping": "80",
            "armature": "0",
        },
    )
    ET.SubElement(
        tray_body,
        "geom",
        {
            "name": "mobile_payload_support_tray",
            "type": "box",
            "size": "0.12 0.10 0.01",
            "rgba": "0.20 0.28 0.38 1",
            "friction": "1.5 0.01 0.001",
            "mass": "0.05",
        },
    )
    link0.append(tray_body)
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / "panda_planar_official_gripper.xml"
    tree.write(destination, encoding="utf-8", xml_declaration=True)
    return destination


def _angle_delta(target: float, current: float) -> float:
    return math.atan2(math.sin(target - current), math.cos(target - current))


def _entity_pos(entity) -> np.ndarray:
    return entity.get_pos().detach().cpu().numpy().reshape(-1)[:3]


def _entity_aabb(entity) -> np.ndarray:
    value = entity.get_AABB().detach().cpu().numpy()
    return value[0] if value.ndim == 3 else value


def _joint_index(robot, name: str) -> int:
    return int(robot.get_joint(name).dof_idx_local)


class RunRecorder:
    def __init__(
        self,
        output_dir: Path,
        overview,
        pickup_camera,
        delivery_camera,
        stride: int,
        *,
        enabled: bool = True,
    ):
        self.output_dir = output_dir
        self.cameras = {
            "overview": overview,
            "pickup": pickup_camera,
            "delivery": delivery_camera,
        }
        self.mode = "overview"
        self.stride = stride
        self.enabled = enabled
        self.steps = 0
        self.frames: list[np.ndarray] = []
        self.key_frames: list[str] = []
        self.depth_key_frames: list[str] = []
        self.latest_event = "initializing"
        self.preview_updates = 0

    def _write_live_status(self) -> None:
        """Atomically publish the latest real simulator state to the dashboard."""
        payload = {
            "control_steps": self.steps,
            "camera_mode": self.mode,
            "latest_event": self.latest_event,
            "preview_updates": self.preview_updates,
        }
        temporary = self.output_dir / "live_status.tmp.json"
        temporary.write_text(json.dumps(payload), encoding="utf-8")
        os.replace(temporary, self.output_dir / "live_status.json")

    def _write_latest_rgb(self, frame: np.ndarray) -> None:
        import imageio.v2 as imageio

        temporary = self.output_dir / "live_rgb.tmp.jpg"
        imageio.imwrite(temporary, frame, quality=85)
        os.replace(temporary, self.output_dir / "live_rgb.jpg")

    def _write_latest_depth(self) -> None:
        import imageio.v2 as imageio

        _, depth, _, _ = self.cameras[self.mode].render(rgb=False, depth=True)
        depth_array = np.asarray(depth, dtype=np.float32)
        finite = depth_array[np.isfinite(depth_array)]
        if finite.size:
            low, high = np.percentile(finite, (2, 98))
            depth_view = np.clip((depth_array - low) / max(float(high - low), 1e-6), 0.0, 1.0)
        else:
            depth_view = np.zeros_like(depth_array)
        temporary = self.output_dir / "live_depth.tmp.png"
        imageio.imwrite(temporary, (depth_view * 255).astype(np.uint8))
        os.replace(temporary, self.output_dir / "live_depth.png")

    def on_step(self) -> None:
        self.steps += 1
        if self.enabled and self.steps % self.stride == 0:
            frame = self.cameras[self.mode].render(rgb=True)[0]
            self.frames.append(frame)
            self.preview_updates += 1
            self._write_latest_rgb(frame)
            if self.preview_updates % 5 == 0:
                self._write_latest_depth()
            self._write_live_status()

    def capture(self, tag: str, *, mode: str | None = None) -> None:
        if mode is not None:
            self.mode = mode
        self.latest_event = tag
        if not self.enabled:
            return
        frame, depth, _, _ = self.cameras[self.mode].render(rgb=True, depth=True)
        filename = f"{len(self.key_frames):02d}_{tag}.png"
        import imageio.v2 as imageio

        imageio.imwrite(self.output_dir / filename, frame)
        self.key_frames.append(filename)
        # Keep metric depth for reproducibility and an 8-bit visualization for
        # the dashboard. The visualization never replaces the raw .npy array.
        depth_raw_name = f"{len(self.depth_key_frames):02d}_{tag}_depth.npy"
        depth_png_name = f"{len(self.depth_key_frames):02d}_{tag}_depth.png"
        depth_array = np.asarray(depth, dtype=np.float32)
        np.save(self.output_dir / depth_raw_name, depth_array)
        finite = depth_array[np.isfinite(depth_array)]
        if finite.size:
            low, high = np.percentile(finite, (2, 98))
            scale = max(float(high - low), 1e-6)
            depth_view = np.clip((depth_array - low) / scale, 0.0, 1.0)
        else:
            depth_view = np.zeros_like(depth_array)
        imageio.imwrite(self.output_dir / depth_png_name, (depth_view * 255).astype(np.uint8))
        self.depth_key_frames.append(depth_png_name)
        self.frames.extend([frame] * 4)
        self._write_latest_rgb(frame)
        self._write_latest_depth()
        self._write_live_status()


class PlanarFrankaController:
    def __init__(
        self,
        bundle,
        recorder: RunRecorder,
        start_xy: np.ndarray,
        *,
        close_force: float = CLOSE_FORCE,
    ):
        self.bundle = bundle
        self.robot = bundle["robot"]
        self.scene = bundle["scene"]
        self.recorder = recorder
        self.start_xy = np.asarray(start_xy, dtype=float)
        self.close_force = close_force
        self.base_indices = [_joint_index(self.robot, name) for name in ("base_x", "base_y", "base_yaw")]
        self.arm_indices = [_joint_index(self.robot, f"joint{i}") for i in range(1, 8)]
        self.tray_index = _joint_index(self.robot, "tray_slide")
        self.finger_indices = [_joint_index(self.robot, name) for name in ("finger_joint1", "finger_joint2")]
        self.hand = self.robot.get_link("hand")
        self.base_target = np.zeros(3)
        self.arm_target = np.asarray(ARM_QPOS, dtype=float)
        self.finger_closed = False
        self.finger_hold_target = None
        self.tray_target = 0.0

        qpos = self.robot.get_qpos().detach().cpu().numpy().reshape(-1)
        qpos[self.base_indices] = self.base_target
        qpos[self.arm_indices] = self.arm_target
        qpos[self.finger_indices] = OPEN
        self.robot.set_qpos(qpos)
        kp = np.full_like(qpos, 1200.0)
        kv = np.full_like(qpos, 120.0)
        force_min = np.full_like(qpos, -800.0)
        force_max = np.full_like(qpos, 800.0)
        kp[self.base_indices] = (12000.0, 12000.0, 8000.0)
        kv[self.base_indices] = (900.0, 900.0, 600.0)
        force_min[self.base_indices] = (-3000.0, -3000.0, -2000.0)
        force_max[self.base_indices] = (3000.0, 3000.0, 2000.0)
        kp[self.arm_indices] = (4500, 4500, 3500, 3500, 2000, 2000, 2000)
        kv[self.arm_indices] = (450, 450, 350, 350, 200, 200, 200)
        force_min[self.arm_indices] = (-87, -87, -87, -87, -12, -12, -12)
        force_max[self.arm_indices] = (87, 87, 87, 87, 12, 12, 12)
        kp[self.finger_indices] = 10000.0
        kv[self.finger_indices] = 1000.0
        force_min[self.finger_indices] = -70.0
        force_max[self.finger_indices] = 70.0
        kp[self.tray_index] = 3000.0
        kv[self.tray_index] = 300.0
        force_min[self.tray_index] = -500.0
        force_max[self.tray_index] = 500.0
        self.robot.set_dofs_kp(kp)
        self.robot.set_dofs_kv(kv)
        self.robot.set_dofs_force_range(force_min, force_max)

    def _command(self) -> None:
        self.robot.control_dofs_position(self.base_target, self.base_indices)
        self.robot.control_dofs_position(self.arm_target, self.arm_indices)
        self.robot.control_dofs_position(
            np.array([self.tray_target]), [self.tray_index]
        )
        if self.finger_closed:
            if self.finger_hold_target is None:
                self.robot.control_dofs_force(
                    np.array([self.close_force, self.close_force]),
                    self.finger_indices,
                )
            else:
                self.robot.control_dofs_position(
                    self.finger_hold_target, self.finger_indices
                )
        else:
            self.robot.control_dofs_position(
                np.array([OPEN, OPEN]), self.finger_indices
            )

    def step(self) -> None:
        self._command()
        self.scene.step()
        self.recorder.on_step()

    def hold(self, steps: int) -> None:
        for _ in range(steps):
            self.step()

    def measured_base_pose(self) -> PlanarPose:
        base = self.robot.get_link("link0")
        xy = _entity_pos(base)[:2]
        quat = base.get_quat().detach().cpu().numpy().reshape(-1)[:4]
        w, x, y, z = quat
        yaw = math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))
        return PlanarPose(float(xy[0]), float(xy[1]), float(yaw))

    def move_base(
        self,
        start: PlanarPose,
        target: PlanarPose,
        steps: int,
        *,
        payload=None,
        slip_detector: SlipDetector | None = None,
    ) -> dict | None:
        yaw_delta = _angle_delta(target.yaw, start.yaw)
        for linear_alpha in np.linspace(0.0, 1.0, steps):
            # Cubic smoothstep gives zero velocity at both endpoints.  A
            # linear interpolation creates a one-step velocity jump that can
            # exceed 8 m/s² and pry a smooth payload out of the fingers.
            alpha = linear_alpha * linear_alpha * (3.0 - 2.0 * linear_alpha)
            world_xy = np.array([start.x, start.y]) * (1 - alpha) + np.array(
                [target.x, target.y]
            ) * alpha
            self.base_target = np.array(
                [
                    world_xy[0] - self.start_xy[0],
                    world_xy[1] - self.start_xy[1],
                    start.yaw + yaw_delta * alpha,
                ]
            )
            self.step()
            if payload is not None and slip_detector is not None:
                relative = _entity_pos(payload) - _entity_pos(self.hand)
                event = slip_detector.observe(relative)
                if event is not None:
                    event["base_pose"] = vars(self.measured_base_pose())
                    event["hand_payload_distance_m"] = float(
                        np.linalg.norm(relative)
                    )
                    return event
        return None

    def recenter_payload(
        self,
        payload,
        desired_relative_xyz: np.ndarray,
        grasp_quat: np.ndarray,
    ) -> dict:
        """Stop the base, re-establish finger contact, and rebaseline slip."""
        before_relative = _entity_pos(payload) - _entity_pos(self.hand)
        requested_hand = _entity_pos(payload) - desired_relative_xyz
        current_hand = _entity_pos(self.hand)
        # Airborne hand-following corrections of even 5 mm were observed to
        # pull the fingertips clear of tall payloads. Keep the arm stationary,
        # return the fingers to force control, then apply only a 0.1 mm
        # symmetric preload before continuing from the stopped base pose.
        self.finger_hold_target = None
        self.hold(50)
        self.ramp_grip_width(preload_m=0.0001, steps=100)
        self.hold(30)
        after_relative = _entity_pos(payload) - _entity_pos(self.hand)
        after_drift = float(
            np.linalg.norm(after_relative - desired_relative_xyz)
        )
        distance = float(np.linalg.norm(after_relative))
        return {
            "before_relative_xyz": before_relative.tolist(),
            "requested_hand_xyz": requested_hand.tolist(),
            "bounded_hand_target_xyz": current_hand.tolist(),
            "bounded_adjustment_m": 0.0,
            "motion": {
                "strategy": "stationary_arm_force_regrip_and_rebaseline",
                "force_control_steps": 50,
                "preload_per_finger_m": 0.0001,
                "preload_steps": 100,
                "settle_steps": 30,
            },
            "after_relative_xyz": after_relative.tolist(),
            "after_drift_m": after_drift,
            "hand_payload_distance_m": distance,
            "success": bool(distance <= 0.18),
        }

    def follow_path(
        self,
        grid,
        cells,
        *,
        final_yaw: float,
        steps_per_cell: int,
        payload=None,
        max_payload_distance: float = 0.18,
        grasp_quat=None,
        max_recenters: int = 2,
        slip_drift_threshold_m: float = 0.025,
        slip_monitoring: bool = True,
    ) -> tuple[bool, list[dict]]:
        current = self.measured_base_pose()
        checkpoints = []
        recovery_events = 0
        slip_detector = None
        desired_relative = None
        if payload is not None:
            desired_relative = _entity_pos(payload) - _entity_pos(self.hand)
            if slip_monitoring:
                slip_detector = SlipDetector(
                    tuple(desired_relative.tolist()),
                    drift_threshold_m=slip_drift_threshold_m,
                )
        for segment_index, cell in enumerate(cells[1:], start=1):
            next_xy = grid.cell_to_world(cell)
            segment_yaw = (
                current.yaw
                if payload is not None
                else math.atan2(next_xy[1] - current.y, next_xy[0] - current.x)
            )
            if payload is not None and abs(_angle_delta(segment_yaw, current.yaw)) > math.radians(2):
                rotation_steps = max(
                    240,
                    int(
                        math.ceil(
                            abs(_angle_delta(segment_yaw, current.yaw))
                            / math.pi
                            * steps_per_cell
                            * 6
                        )
                    ),
                )
                rotated = PlanarPose(current.x, current.y, segment_yaw)
                event = self.move_base(
                    current,
                    rotated,
                    rotation_steps,
                    payload=payload,
                    slip_detector=slip_detector,
                )
                current = rotated
                if event is not None:
                    checkpoints.append(
                        {
                            "segment": f"{segment_index}_rotation_slip_stop",
                            **event,
                        }
                    )
                    return True, checkpoints
                rotation_distance = float(
                    np.linalg.norm(_entity_pos(payload) - _entity_pos(self.hand))
                )
                checkpoints.append(
                    {
                        "segment": f"{segment_index}_rotation",
                        "base_xy": [current.x, current.y],
                        "base_yaw": current.yaw,
                        "payload_hand_distance_m": rotation_distance,
                        "finger_qpos_m": (
                            self.robot.get_dofs_position(self.finger_indices)
                            .detach()
                            .cpu()
                            .numpy()
                            .reshape(-1)
                            .tolist()
                        ),
                    }
                )
                if rotation_distance > max_payload_distance:
                    return True, checkpoints
            target = PlanarPose(next_xy[0], next_xy[1], segment_yaw)
            event = self.move_base(
                current,
                target,
                steps_per_cell,
                payload=payload,
                slip_detector=slip_detector,
            )
            while (
                event is not None
                and payload is not None
                and grasp_quat is not None
                and recovery_events < max_recenters
            ):
                stopped_pose = self.measured_base_pose()
                recovery = self.recenter_payload(
                    payload, desired_relative, grasp_quat
                )
                recovery_events += 1
                checkpoints.append(
                    {
                        "segment": f"{segment_index}_slip_recovery",
                        "slip_event": event,
                        "recovery_index": recovery_events,
                        "recovery": recovery,
                    }
                )
                if not recovery["success"]:
                    return True, checkpoints
                desired_relative[:] = np.asarray(
                    recovery["after_relative_xyz"], dtype=float
                )
                slip_detector.desired_relative_xyz = tuple(
                    desired_relative.tolist()
                )
                slip_detector.reset_observation(
                    _entity_pos(payload) - _entity_pos(self.hand)
                )
                event = self.move_base(
                    stopped_pose,
                    target,
                    steps_per_cell,
                    payload=payload,
                    slip_detector=slip_detector,
                )
            if event is not None:
                checkpoints.append(
                    {
                        "segment": f"{segment_index}_slip_stop",
                        **event,
                    }
                )
                return True, checkpoints
            current = target
            if payload is not None:
                distance = float(
                    np.linalg.norm(_entity_pos(payload) - _entity_pos(self.hand))
                )
                checkpoints.append(
                    {
                        "segment": segment_index,
                        "base_xy": [target.x, target.y],
                        "payload_hand_distance_m": distance,
                        "finger_qpos_m": (
                            self.robot.get_dofs_position(self.finger_indices)
                            .detach()
                            .cpu()
                            .numpy()
                            .reshape(-1)
                            .tolist()
                        ),
                    }
                )
                if distance > max_payload_distance:
                    return True, checkpoints
        target_xy = grid.cell_to_world(cells[-1])
        final_target = PlanarPose(target_xy[0], target_xy[1], final_yaw)
        event = self.move_base(
            current,
            final_target,
            max(80, steps_per_cell),
            payload=payload,
            slip_detector=slip_detector,
        )
        while (
            event is not None
            and payload is not None
            and grasp_quat is not None
            and recovery_events < max_recenters
        ):
            stopped_pose = self.measured_base_pose()
            recovery = self.recenter_payload(
                payload, desired_relative, grasp_quat
            )
            recovery_events += 1
            checkpoints.append(
                {
                    "segment": "final_slip_recovery",
                    "slip_event": event,
                    "recovery_index": recovery_events,
                    "recovery": recovery,
                }
            )
            if not recovery["success"]:
                return True, checkpoints
            desired_relative[:] = np.asarray(
                recovery["after_relative_xyz"], dtype=float
            )
            slip_detector.desired_relative_xyz = tuple(
                desired_relative.tolist()
            )
            slip_detector.reset_observation(
                _entity_pos(payload) - _entity_pos(self.hand)
            )
            event = self.move_base(
                stopped_pose,
                final_target,
                max(80, steps_per_cell),
                payload=payload,
                slip_detector=slip_detector,
            )
        if event is not None:
            checkpoints.append({"segment": "final_slip_stop", **event})
            return True, checkpoints
        self.hold(120)
        if payload is not None:
            distance = float(
                np.linalg.norm(_entity_pos(payload) - _entity_pos(self.hand))
            )
            checkpoints.append(
                {
                    "segment": "final_orientation",
                    "base_xy": list(target_xy),
                    "payload_hand_distance_m": distance,
                }
            )
            if distance > max_payload_distance:
                return True, checkpoints
        return False, checkpoints

    def _solve_arm(self, target: np.ndarray, quat: np.ndarray) -> np.ndarray:
        q_goal = self.robot.inverse_kinematics(
            link=self.hand,
            pos=target,
            quat=quat,
            init_qpos=self.robot.get_qpos(),
            dofs_idx_local=self.arm_indices,
            max_samples=40,
            max_solver_iters=50,
        )
        return q_goal.detach().cpu().numpy().reshape(-1)[self.arm_indices]

    def move_hand(
        self,
        target: np.ndarray,
        quat: np.ndarray,
        *,
        minimum_steps: int,
        max_joint_delta: float = 0.006,
    ) -> dict:
        goal = self._solve_arm(target, quat)
        start = (
            self.robot.get_dofs_position(self.arm_indices)
            .detach()
            .cpu()
            .numpy()
            .reshape(-1)
        )
        count = max(
            minimum_steps,
            int(math.ceil(float(np.max(np.abs(goal - start))) / max_joint_delta)),
        )
        for arm in np.linspace(start, goal, count):
            self.arm_target = arm
            self.step()
        self.hold(20)
        measured = _entity_pos(self.hand)
        return {
            "commanded_hand_xyz": np.asarray(target).tolist(),
            "measured_hand_xyz": measured.tolist(),
            "hand_error_m": float(np.linalg.norm(measured - target)),
            "control_steps": count + 20,
        }

    def close(self, steps: int = 100) -> None:
        self.finger_closed = True
        self.finger_hold_target = None
        self.hold(steps)

    def ramp_grip_width(
        self, preload_m: float = 0.0003, steps: int = 160
    ) -> list[float]:
        """Gradually preload, then hold width without attaching the payload."""
        measured = (
            self.robot.get_dofs_position(self.finger_indices)
            .detach()
            .cpu()
            .numpy()
            .reshape(-1)
        )
        final_target = np.maximum(measured - preload_m, 0.0)
        for target in np.linspace(measured, final_target, steps):
            self.finger_hold_target = target
            self.step()
        self.finger_hold_target = final_target
        return self.finger_hold_target.tolist()

    def open(self, steps: int = 80) -> None:
        self.finger_closed = False
        self.finger_hold_target = None
        self.hold(steps)

    def deploy_tray(self, steps: int = 120) -> dict:
        start = float(
            self.robot.get_dofs_position([self.tray_index])
            .detach()
            .cpu()
            .numpy()
            .reshape(-1)[0]
        )
        for target in np.linspace(start, 0.46, steps):
            self.tray_target = float(target)
            self.step()
        self.hold(20)
        measured = float(
            self.robot.get_dofs_position([self.tray_index])
            .detach()
            .cpu()
            .numpy()
            .reshape(-1)[0]
        )
        return {
            "commanded_extension_m": self.tray_target,
            "measured_extension_m": measured,
            "control_steps": steps + 20,
        }

    def retract_tray_checked(
        self,
        payload,
        grasp_quat: np.ndarray,
        stable_relative: np.ndarray,
        *,
        step_extension_m: float,
        drift_threshold_m: float,
        preloss_distance_m: float,
        max_regrips: int,
    ) -> dict:
        """Transfer payload weight to the gripper while withdrawing support."""
        start_extension = float(
            self.robot.get_dofs_position([self.tray_index])
            .detach()
            .cpu()
            .numpy()
            .reshape(-1)[0]
        )
        increments = max(
            1, int(math.ceil(start_extension / step_extension_m))
        )
        checkpoints = []
        regrips = 0
        failure_reasons: list[str] = []

        for index in range(1, increments + 1):
            target_extension = max(
                0.0, start_extension - index * step_extension_m
            )
            measured_start = float(
                self.robot.get_dofs_position([self.tray_index])
                .detach()
                .cpu()
                .numpy()
                .reshape(-1)[0]
            )
            for target in np.linspace(measured_start, target_extension, 12):
                self.tray_target = float(target)
                self.step()
            self.hold(4)
            relative = _entity_pos(payload) - _entity_pos(self.hand)
            distance = float(np.linalg.norm(relative))
            drift = float(np.linalg.norm(relative - stable_relative))
            contacts = _finger_contact_summary(self.robot, payload)
            reasons = unload_instability_reasons(
                bilateral_contact=contacts["bilateral_finger_contact"],
                relative_drift_m=drift,
                hand_payload_distance_m=distance,
                drift_threshold_m=drift_threshold_m,
                preloss_distance_m=preloss_distance_m,
            )
            recovery = None
            if reasons and regrips < max_regrips and distance < 0.18:
                recovery = self.recenter_payload(
                    payload, stable_relative, grasp_quat
                )
                regrips += 1
                relative = _entity_pos(payload) - _entity_pos(self.hand)
                distance = float(np.linalg.norm(relative))
                contacts = _finger_contact_summary(self.robot, payload)
                # A stationary regrip intentionally accepts the new relative
                # pose as its reference. It must restore bilateral contact and
                # remain below the pre-loss distance; it need not undo drift
                # that already happened.
                reasons = unload_instability_reasons(
                    bilateral_contact=contacts["bilateral_finger_contact"],
                    relative_drift_m=0.0,
                    hand_payload_distance_m=distance,
                    drift_threshold_m=drift_threshold_m,
                    preloss_distance_m=preloss_distance_m,
                )
                recovery["post_regrip_contacts"] = contacts
                recovery["post_regrip_instability_reasons"] = reasons
                recovery["success"] = bool(
                    recovery["success"] and not reasons and distance < 0.18
                )
                if recovery["success"]:
                    stable_relative = relative.copy()

            checkpoints.append(
                {
                    "increment": index,
                    "commanded_extension_m": target_extension,
                    "measured_extension_m": float(
                        self.robot.get_dofs_position([self.tray_index])
                        .detach()
                        .cpu()
                        .numpy()
                        .reshape(-1)[0]
                    ),
                    "hand_payload_relative_xyz": relative.tolist(),
                    "hand_payload_distance_m": distance,
                    "relative_drift_m": float(
                        np.linalg.norm(relative - stable_relative)
                    ),
                    "finger_contacts": contacts,
                    "instability_reasons": reasons,
                    "recovery": recovery,
                }
            )
            if reasons or distance >= 0.18:
                failure_reasons = reasons or [
                    "payload_loss_distance_threshold"
                ]
                break

        return {
            "strategy": "incremental_contact_verified_tray_retraction",
            "start_extension_m": start_extension,
            "step_extension_m": step_extension_m,
            "regrip_count": regrips,
            "completed_increments": len(checkpoints),
            "checkpoints": checkpoints,
            "final_extension_m": checkpoints[-1]["measured_extension_m"],
            "stable_relative_xyz": stable_relative.tolist(),
            "failure_reasons": failure_reasons,
            "success": not failure_reasons
            and checkpoints[-1]["measured_extension_m"] <= 0.01,
        }

    def incremental_unload(
        self,
        payload,
        grasp_quat: np.ndarray,
        *,
        total_height_m: float = 0.04,
        step_height_m: float = 0.005,
        drift_threshold_m: float = 0.004,
        preloss_distance_m: float = 0.150,
        max_regrips: int = 8,
        tray_step_extension_m: float = 0.02,
    ) -> dict:
        """Lift from the tray in checked increments and regrip before loss."""
        start_hand = _entity_pos(self.hand)
        stable_relative = _entity_pos(payload) - start_hand
        checkpoints = []
        regrips = 0
        tray_retraction = None
        increments = max(1, int(math.ceil(total_height_m / step_height_m)))
        success = True
        failure_reasons: list[str] = []

        # Establish the strongest measured two-finger hold before asking the
        # gripper to break payload/tray static contact.
        initial_regrip = self.recenter_payload(
            payload, stable_relative, grasp_quat
        )
        regrips += 1
        stable_relative = _entity_pos(payload) - _entity_pos(self.hand)
        initial_contacts = _finger_contact_summary(self.robot, payload)
        initial_distance = float(np.linalg.norm(stable_relative))
        initial_reasons = unload_instability_reasons(
            bilateral_contact=initial_contacts["bilateral_finger_contact"],
            relative_drift_m=0.0,
            hand_payload_distance_m=initial_distance,
            drift_threshold_m=drift_threshold_m,
            preloss_distance_m=preloss_distance_m,
        )
        initial_regrip["post_regrip_contacts"] = initial_contacts
        initial_regrip["post_regrip_instability_reasons"] = initial_reasons
        initial_regrip["success"] = bool(
            initial_regrip["success"] and not initial_reasons
        )
        if not initial_regrip["success"]:
            return {
                "strategy": "incremental_contact_verified_tray_unload",
                "commanded_total_height_m": total_height_m,
                "step_height_m": step_height_m,
                "drift_threshold_m": drift_threshold_m,
                "preloss_distance_m": preloss_distance_m,
                "max_regrips": max_regrips,
                "initial_regrip": initial_regrip,
                "regrip_count": regrips,
                "completed_increments": 0,
                "checkpoints": [],
                "hand_payload_distance_m": initial_distance,
                "failure_reasons": initial_reasons
                or ["initial_unload_regrip_failed"],
                "success": False,
            }

        for index in range(1, increments + 1):
            commanded_height = min(total_height_m, index * step_height_m)
            target = start_hand + np.array([0.0, 0.0, commanded_height])
            motion = self.move_hand(
                target,
                grasp_quat,
                minimum_steps=35,
                max_joint_delta=0.001,
            )
            self.hold(8)
            relative = _entity_pos(payload) - _entity_pos(self.hand)
            distance = float(np.linalg.norm(relative))
            drift = float(np.linalg.norm(relative - stable_relative))
            contacts = _finger_contact_summary(self.robot, payload)
            reasons = unload_instability_reasons(
                bilateral_contact=contacts["bilateral_finger_contact"],
                relative_drift_m=drift,
                hand_payload_distance_m=distance,
                drift_threshold_m=drift_threshold_m,
                preloss_distance_m=preloss_distance_m,
            )
            recovery = None

            if reasons and regrips < max_regrips and distance < 0.18:
                recovery = self.recenter_payload(
                    payload, stable_relative, grasp_quat
                )
                regrips += 1
                relative = _entity_pos(payload) - _entity_pos(self.hand)
                distance = float(np.linalg.norm(relative))
                drift = float(np.linalg.norm(relative - stable_relative))
                contacts = _finger_contact_summary(self.robot, payload)
                reasons = unload_instability_reasons(
                    bilateral_contact=contacts["bilateral_finger_contact"],
                    relative_drift_m=0.0,
                    hand_payload_distance_m=distance,
                    drift_threshold_m=drift_threshold_m,
                    preloss_distance_m=preloss_distance_m,
                )
                recovery["post_regrip_contacts"] = contacts
                recovery["post_regrip_instability_reasons"] = reasons
                recovery["success"] = bool(
                    recovery["success"] and not reasons and distance < 0.18
                )
                if recovery["success"]:
                    stable_relative = relative.copy()

            checkpoint = {
                "increment": index,
                "commanded_unload_height_m": commanded_height,
                "motion": motion,
                "hand_payload_relative_xyz": relative.tolist(),
                "hand_payload_distance_m": distance,
                "relative_drift_m": drift,
                "finger_contacts": contacts,
                "instability_reasons": reasons,
                "recovery": recovery,
            }
            checkpoints.append(checkpoint)

            if reasons or distance >= 0.18:
                success = False
                failure_reasons = reasons or ["payload_loss_distance_threshold"]
                break

            if index == 1:
                tray_retraction = self.retract_tray_checked(
                    payload,
                    grasp_quat,
                    stable_relative,
                    step_extension_m=tray_step_extension_m,
                    drift_threshold_m=drift_threshold_m,
                    preloss_distance_m=preloss_distance_m,
                    max_regrips=max(0, max_regrips - regrips),
                )
                regrips += tray_retraction["regrip_count"]
                stable_relative = np.asarray(
                    tray_retraction["stable_relative_xyz"], dtype=float
                )
                if not tray_retraction["success"]:
                    success = False
                    failure_reasons = [
                        "tray_retraction_failed",
                        *tray_retraction["failure_reasons"],
                    ]
                    break

        return {
            "strategy": "incremental_contact_verified_tray_unload",
            "commanded_total_height_m": total_height_m,
            "step_height_m": step_height_m,
            "drift_threshold_m": drift_threshold_m,
            "preloss_distance_m": preloss_distance_m,
            "max_regrips": max_regrips,
            "tray_step_extension_m": tray_step_extension_m,
            "initial_regrip": initial_regrip,
            "tray_retraction": tray_retraction,
            "regrip_count": regrips,
            "completed_increments": len(checkpoints),
            "checkpoints": checkpoints,
            "hand_payload_distance_m": (
                checkpoints[-1]["hand_payload_distance_m"]
                if checkpoints
                else float(np.linalg.norm(stable_relative))
            ),
            "failure_reasons": failure_reasons,
            "success": success,
        }


def _camera_pose(frame: PlanarPose, local_xyz: tuple[float, float, float]) -> tuple[float, float, float]:
    return tuple(frame.local_to_world(np.asarray(local_xyz, dtype=float)))


def _build_scene(
    *,
    reference_root: Path,
    planar_mjcf: Path,
    task,
    object_profile: PhysicalObjectProfile,
    output_dir: Path,
):
    import genesis as gs
    from franka_fruit_pick.scene_config import get_ycb_assets

    pickup_frame = docking_pose(task.source_zone)
    delivery_frame = delivery_pose_with_payload_heading(
        task.source_zone, task.target_zone
    )
    assets = get_ycb_assets()
    scene = gs.Scene(
        sim_options=gs.options.SimOptions(dt=0.01, substeps=2),
        rigid_options=gs.options.RigidOptions(
            dt=0.01,
            constraint_solver=gs.constraint_solver.Newton,
            enable_collision=True,
            enable_joint_limit=True,
        ),
        show_viewer=False,
        profiling_options=gs.options.ProfilingOptions(show_FPS=False),
    )
    scene.add_entity(gs.morphs.Plane())

    def add_box(size, pos, color, *, euler=(0, 0, 0), fixed=True):
        return scene.add_entity(
            morph=gs.morphs.Box(size=size, pos=pos, euler=euler, fixed=fixed),
            material=gs.materials.Rigid(rho=300.0, friction=1.0),
            surface=gs.surfaces.Default(color=color),
        )

    wall_color = (0.72, 0.77, 0.82, 1.0)
    for size, pos in (
        ((6.2, 0.08, 0.45), (0.0, -3.06, 0.225)),
        ((6.2, 0.08, 0.45), (0.0, 3.06, 0.225)),
        ((0.08, 6.2, 0.45), (-3.06, 0.0, 0.225)),
        ((0.08, 6.2, 0.45), (3.06, 0.0, 0.225)),
    ):
        add_box(size, pos, wall_color)
    obstacle_color = (0.35, 0.42, 0.50, 1.0)
    add_box((1.40, 0.70, 0.65), (0.0, 0.0, 0.325), obstacle_color)
    add_box((0.50, 0.50, 0.75), (-1.55, 0.25, 0.375), obstacle_color)
    add_box((0.50, 0.50, 0.75), (1.55, 0.25, 0.375), obstacle_color)

    table_color = (0.62, 0.47, 0.35, 1.0)
    for frame in (pickup_frame, delivery_frame):
        center = frame.local_to_world(
            np.array([work_surface_center_local_x(), 0.0, 0.725])
        )
        add_box(
            WORK_SURFACE_SIZE_M,
            tuple(center),
            table_color,
            euler=(0.0, 0.0, math.degrees(frame.yaw)),
        )

    payload_local = np.array(
        [
            PICKUP_OBJECT_LOCAL_X_M,
            -0.08,
            0.75 + object_profile.size_xyz_m[2] / 2.0,
        ]
    )
    payload_world = pickup_frame.local_to_world(payload_local)
    payload = scene.add_entity(
        morph=gs.morphs.Box(
            size=object_profile.size_xyz_m,
            pos=tuple(payload_world),
            euler=(
                0.0,
                0.0,
                math.degrees(pickup_frame.yaw) + object_profile.yaw_deg,
            ),
            fixed=False,
        ),
        material=gs.materials.Rigid(
            rho=object_profile.density_kg_m3,
            friction=object_profile.friction,
        ),
        surface=gs.surfaces.Default(color=object_profile.color_rgba),
    )
    bowl_local = np.array(
        [
            PLACE_TARGET_LOCAL_X_M,
            -0.10,
            0.75 + assets[PLACE_TARGET].rest_z_offset,
        ]
    )
    bowl_world = delivery_frame.local_to_world(bowl_local)
    bowl = scene.add_entity(
        morph=gs.morphs.Mesh(
            file=str(assets[PLACE_TARGET].mesh_path),
            pos=tuple(bowl_world),
            euler=(0.0, 0.0, math.degrees(delivery_frame.yaw)),
            align=False,
            convexify=True,
            decimate_face_num=500,
        ),
        material=gs.materials.Rigid(rho=300.0, friction=1.0),
    )
    robot = scene.add_entity(
        gs.morphs.MJCF(
            file=str(planar_mjcf),
            pos=(task.start_xy[0], task.start_xy[1], 0.75),
        )
    )
    overview = scene.add_camera(
        res=(1280, 720),
        pos=(6.4, -7.0, 7.5),
        lookat=(0.0, 0.0, 0.3),
        fov=48,
        GUI=False,
    )
    pickup_camera = scene.add_camera(
        res=(1280, 720),
        pos=_camera_pose(pickup_frame, (1.15, -1.00, 1.55)),
        lookat=_camera_pose(pickup_frame, (0.38, 0.0, 0.92)),
        fov=42,
        GUI=False,
    )
    delivery_camera = scene.add_camera(
        res=(1280, 720),
        pos=_camera_pose(delivery_frame, (1.15, -1.00, 1.55)),
        lookat=_camera_pose(delivery_frame, (0.48, -0.05, 0.90)),
        fov=42,
        GUI=False,
    )
    scene.build()
    return {
        "scene": scene,
        "robot": robot,
        "payload": payload,
        "bowl": bowl,
        "overview": overview,
        "pickup_camera": pickup_camera,
        "delivery_camera": delivery_camera,
        "pickup_frame": pickup_frame,
        "delivery_frame": delivery_frame,
        "payload_local": payload_local,
        "bowl_local": bowl_local,
    }


def _finger_contact_summary(robot, obj) -> dict:
    contacts = robot.get_contacts(with_entity=obj, exclude_self_contact=True)
    positions = contacts["position"].detach().cpu().numpy()
    forces = contacts["force_a"].detach().cpu().numpy()
    link_a = contacts["link_a"].detach().cpu().numpy().reshape(-1)
    link_b = contacts["link_b"].detach().cpu().numpy().reshape(-1)
    link_names = {
        int(link.idx): link.name
        for entity in (robot, obj)
        for link in entity.links
    }
    finger_ids = {
        int(robot.get_link(name).idx): name
        for name in ("left_finger", "right_finger")
    }
    contacted_fingers = sorted(
        {
            finger_ids[index]
            for index in np.concatenate((link_a, link_b)).astype(int)
            if index in finger_ids
        }
    )
    return {
        "contact_count": int(len(positions)),
        "contact_positions_xyz": positions.tolist(),
        "contact_force_norms_n": np.linalg.norm(forces, axis=-1).tolist(),
        "contact_link_pairs": [
            {
                "link_a": link_names.get(int(a), f"global_link_{int(a)}"),
                "link_b": link_names.get(int(b), f"global_link_{int(b)}"),
            }
            for a, b in zip(link_a, link_b)
        ],
        "contacted_fingers": contacted_fingers,
        "bilateral_finger_contact": len(contacted_fingers) == 2,
    }


def _contact_summary(robot, obj) -> dict:
    return _finger_contact_summary(robot, obj)


def _inside_bowl(payload, bowl, tolerance: float = 0.07) -> tuple[bool, dict]:
    payload_pos = _entity_pos(payload)
    bowl_pos = _entity_pos(bowl)
    payload_aabb = _entity_aabb(payload)
    bowl_aabb = _entity_aabb(bowl)
    horizontal = float(np.linalg.norm(payload_pos[:2] - bowl_pos[:2]))
    below_rim = float(payload_aabb[0, 2]) < float(bowl_aabb[1, 2]) - 0.005
    return horizontal < tolerance and below_rim, {
        "horizontal_error_m": horizontal,
        "payload_bottom_z_m": float(payload_aabb[0, 2]),
        "bowl_rim_z_m": float(bowl_aabb[1, 2]),
        "below_rim": bool(below_rim),
    }


def run(args: argparse.Namespace) -> dict:
    if np is None:
        raise RuntimeError("numpy is required to run the Genesis mobile pipeline")
    reference_root = resolve_reference_root(args.reference_root)
    sys.path.insert(0, str(reference_root))
    import genesis as gs
    import imageio.v2 as imageio
    from franka_fruit_pick.grasp_demo import (
        HAND_TO_FINGERTIP,
        PREGRASP_CLEARANCE,
        RETREAT_HAND_Z,
        _grasp_hand_z,
        _obj_xy_yaw,
        _topdown_quat,
        GraspProfile,
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    object_profile = OBJECT_PROFILES[args.object_profile]
    planar_mjcf = prepare_planar_franka_mjcf(
        reference_root, args.output_dir / "generated_assets"
    )
    grid = build_room_grid()
    task = generate_task(args.seed, grid)
    if args.source_zone is not None:
        task = replace(task, source_zone=args.source_zone)
    if args.target_zone is not None:
        task = replace(task, target_zone=args.target_zone)
    plan = plan_transport(task, grid)
    gs.init(backend=gs.gpu, seed=args.seed)
    bundle = _build_scene(
        reference_root=reference_root,
        planar_mjcf=planar_mjcf,
        task=task,
        object_profile=object_profile,
        output_dir=args.output_dir,
    )
    recorder = RunRecorder(
        args.output_dir,
        bundle["overview"],
        bundle["pickup_camera"],
        bundle["delivery_camera"],
        args.video_stride,
        enabled=not args.no_video,
    )
    controller = PlanarFrankaController(
        bundle,
        recorder,
        np.asarray(task.start_xy),
        close_force=object_profile.close_force_n,
    )
    controller.hold(60)
    recorder.capture("start", mode="overview")

    pickup_target = bundle["pickup_frame"]
    controller.follow_path(
        grid,
        plan.pickup_path,
        final_yaw=pickup_target.yaw,
        steps_per_cell=args.navigation_steps,
    )
    measured_pickup = controller.measured_base_pose()
    pickup_error = float(
        np.linalg.norm(
            np.array([measured_pickup.x, measured_pickup.y])
            - np.array([pickup_target.x, pickup_target.y])
        )
    )
    recorder.capture("pickup_dock", mode="pickup")

    payload = bundle["payload"]
    payload_initial = _entity_pos(payload)
    _, object_yaw = _obj_xy_yaw(payload)
    profile = GraspProfile(
        yaw_offset=0.0,
        close_force=object_profile.close_force_n,
        center_align=True,
    )
    grasp_quat = _topdown_quat(object_yaw + profile.yaw_offset)
    grasp_hand_z = _grasp_hand_z(payload, profile) + args.grasp_z_offset_m
    pregrasp = np.array(
        [payload_initial[0], payload_initial[1], payload_initial[2] + PREGRASP_CLEARANCE]
    )
    grasp = np.array([payload_initial[0], payload_initial[1], grasp_hand_z])
    phase_metrics = {
        "pregrasp": controller.move_hand(pregrasp, grasp_quat, minimum_steps=100),
        "reach": controller.move_hand(grasp, grasp_quat, minimum_steps=80),
    }
    recorder.capture("reach", mode="pickup")
    controller.close(100)
    close_contacts = _contact_summary(controller.robot, payload)
    recorder.capture("grasp", mode="pickup")

    lift = np.array([grasp[0], grasp[1], 1.05])
    phase_metrics["lift"] = controller.move_hand(
        lift, grasp_quat, minimum_steps=100, max_joint_delta=0.004
    )
    phase_metrics["grip_width_hold"] = {
        "finger_target_qpos_m": controller.ramp_grip_width(
            preload_m=args.grip_preload_m,
            steps=args.grip_preload_steps,
        ),
        "preload_per_finger_m": args.grip_preload_m,
        "preload_control_steps": args.grip_preload_steps,
        "mode": "post_lift_position_hold_after_force_close",
        "kinematic_object_attachment": False,
    }
    controller.hold(10)
    payload_lifted = _entity_pos(payload)
    lift_m = float(payload_lifted[2] - payload_initial[2])
    hand_payload_distance = float(
        np.linalg.norm(payload_lifted - _entity_pos(controller.hand))
    )
    grasp_success = lift_m >= 0.10 and hand_payload_distance <= 0.18
    recorder.capture("physical_lift", mode="pickup")

    payload_lost = not grasp_success
    payload_distance_after_retract = hand_payload_distance
    carry_mode = args.carry_mode
    if not payload_lost:
        if carry_mode == "auto":
            carry_mode = (
                "body_centered"
                if object_profile.mass_kg >= 0.10
                or object_profile.size_xyz_m[2] >= 0.09
                else "lifted"
            )
        if carry_mode == "body_centered":
            phase_metrics["tray_deploy"] = controller.deploy_tray()
            relative_after_lift = _entity_pos(payload) - _entity_pos(
                controller.hand
            )
            tray_top_z = 0.75 + 0.05 + 0.01
            desired_payload_on_tray = np.asarray(
                pickup_target.local_to_world(
                    [
                        0.26,
                        -0.05,
                        tray_top_z
                        + object_profile.size_xyz_m[2] / 2.0
                        + 0.002,
                    ]
                ),
                dtype=float,
            )
            carry = desired_payload_on_tray - relative_after_lift
            phase_metrics["carry_pose_hold"] = {
                **controller.move_hand(
                    carry,
                    grasp_quat,
                    minimum_steps=140,
                    max_joint_delta=0.002,
                ),
                "strategy": "lower_body_centered_carry_pose",
                "carry_mode": carry_mode,
                "desired_payload_on_support_xyz": (
                    desired_payload_on_tray.tolist()
                ),
                "payload_relative_after_lift_xyz": (
                    relative_after_lift.tolist()
                ),
                "physical_support": "mobile_payload_support_tray",
            }
            controller.hold(20)
        else:
            carry = _entity_pos(controller.hand)
            controller.hold(10)
            phase_metrics["carry_pose_hold"] = {
                "commanded_hand_xyz": carry.tolist(),
                "measured_hand_xyz": _entity_pos(controller.hand).tolist(),
                "control_steps": 10,
                "strategy": "retain_verified_lift_pose",
                "carry_mode": carry_mode,
            }
        payload_distance_after_retract = float(
            np.linalg.norm(_entity_pos(payload) - _entity_pos(controller.hand))
        )
        payload_lost = payload_distance_after_retract > 0.18
        recorder.capture("verified_carry_pose", mode="pickup")

    measured_delivery = None
    delivery_error = None
    transport_checkpoints = []
    if not payload_lost:
        recorder.mode = "overview"
        payload_lost, transport_checkpoints = controller.follow_path(
            grid,
            plan.delivery_path,
            final_yaw=bundle["delivery_frame"].yaw,
            steps_per_cell=args.transport_steps,
            payload=payload,
            grasp_quat=grasp_quat,
            max_recenters=args.max_recenters,
            slip_drift_threshold_m=args.slip_drift_threshold_m,
            slip_monitoring=not args.disable_slip_monitoring,
        )
        measured_delivery = controller.measured_base_pose()
        delivery_error = float(
            np.linalg.norm(
                np.array([measured_delivery.x, measured_delivery.y])
                - np.array(
                    [bundle["delivery_frame"].x, bundle["delivery_frame"].y]
                )
            )
        )
        payload_distance_after_transport = float(
            np.linalg.norm(_entity_pos(payload) - _entity_pos(controller.hand))
        )
        payload_lost = (
            payload_lost or payload_distance_after_transport > 0.18
        )
        recorder.capture("delivery_dock", mode="delivery")
    else:
        payload_distance_after_transport = hand_payload_distance

    place_success = False
    placement_metrics = {}
    if not payload_lost:
        bowl = bundle["bowl"]
        bowl_pos = _entity_pos(bowl)
        bowl_aabb = _entity_aabb(bowl)
        if carry_mode == "body_centered":
            phase_metrics["unload_from_support"] = controller.incremental_unload(
                payload,
                grasp_quat,
                total_height_m=args.unload_height_m,
                step_height_m=args.unload_step_m,
                drift_threshold_m=args.unload_drift_threshold_m,
                preloss_distance_m=args.unload_preloss_distance_m,
                max_regrips=args.unload_max_regrips,
            )
            if not phase_metrics["unload_from_support"]["success"]:
                payload_lost = True
        if payload_lost:
            placement_metrics = {
                "skipped": True,
                "reason": "payload_lost_while_unloading_support",
            }
        else:
            current_payload_relative = _entity_pos(payload) - _entity_pos(
                controller.hand
            )
            desired_payload_release = np.array(
                [
                    bowl_pos[0],
                    bowl_pos[1],
                    float(bowl_aabb[1, 2]) + 0.03,
                ]
            )
            above = desired_payload_release - current_payload_relative
            phase_metrics["above_target"] = controller.move_hand(
                above, grasp_quat, minimum_steps=120, max_joint_delta=0.004
            )
            recorder.capture("above_target", mode="delivery")
            phase_metrics["payload_aware_release_target"] = {
                "payload_relative_to_hand_xyz": (
                    current_payload_relative.tolist()
                ),
                "desired_payload_release_xyz": desired_payload_release.tolist(),
                "compensated_hand_target_xyz": above.tolist(),
            }
            controller.open(80)
            controller.hold(60)
            retreat = np.array([above[0], above[1], RETREAT_HAND_Z])
            phase_metrics["retreat"] = controller.move_hand(
                retreat, grasp_quat, minimum_steps=80
            )
            controller.hold(80)
            place_success, placement_metrics = _inside_bowl(payload, bowl)
            recorder.capture("released_and_settled", mode="delivery")

    pickup_predicted = np.asarray(
        pickup_target.local_to_world(bundle["payload_local"]), dtype=float
    )
    transform_error = float(np.linalg.norm(pickup_predicted - payload_initial))
    result = {
        "backend": "gpu",
        "seed": args.seed,
        "pipeline": "single_scene_planar_mjcf_physical_contact",
        "task": {
            "semantic_object_id": task.object_id,
            "physical_object": object_profile.name,
            "physical_object_profile": {
                "size_xyz_m": object_profile.size_xyz_m,
                "mass_kg": object_profile.mass_kg,
                "density_kg_m3": object_profile.density_kg_m3,
                "friction": object_profile.friction,
                "close_force_n": object_profile.close_force_n,
                "yaw_deg": object_profile.yaw_deg,
                "grasp_z_offset_m": args.grasp_z_offset_m,
                "carry_mode_requested": args.carry_mode,
                "slip_monitoring_enabled": not args.disable_slip_monitoring,
            },
            "source_zone": task.source_zone,
            "target_zone": task.target_zone,
            "start_xy": task.start_xy,
            "planned_distance_m": plan.total_distance_m,
        },
        "coordinate_transforms": {
            "pickup_T_room_from_mjcf": pickup_target.matrix(),
            "delivery_T_room_from_mjcf": bundle["delivery_frame"].matrix(),
            "pickup_local_object_xyz": bundle["payload_local"].tolist(),
            "pickup_predicted_world_xyz": pickup_predicted.tolist(),
            "pickup_actual_world_xyz": payload_initial.tolist(),
            "transform_error_m": transform_error,
        },
        "navigation": {
            "pickup_target_pose": vars(pickup_target),
            "pickup_measured_pose": vars(measured_pickup),
            "pickup_error_m": pickup_error,
            "delivery_target_pose": vars(bundle["delivery_frame"]),
            "delivery_measured_pose": (
                None if measured_delivery is None else vars(measured_delivery)
            ),
            "delivery_error_m": delivery_error,
            "base_joint_target": controller.base_target.tolist(),
            "base_joint_measured": (
                controller.robot.get_dofs_position(controller.base_indices)
                .detach()
                .cpu()
                .numpy()
                .reshape(-1)
                .tolist()
            ),
        },
        "manipulation": {
            "robot_asset": "official_franka_mjcf_with_generated_planar_root",
            "close_contacts": close_contacts,
            "initial_object_xyz": payload_initial.tolist(),
            "lifted_object_xyz": payload_lifted.tolist(),
            "object_lift_m": lift_m,
            "hand_payload_distance_after_lift_m": hand_payload_distance,
            "hand_payload_distance_after_retract_m": payload_distance_after_retract,
            "hand_payload_distance_after_transport_m": payload_distance_after_transport,
            "transport_checkpoints": transport_checkpoints,
            "phase_metrics": phase_metrics,
            "placement_metrics": placement_metrics,
        },
        "grasp_success": bool(grasp_success),
        "payload_lost_during_transport": bool(payload_lost),
        "place_success": bool(place_success),
        "transport_success": bool(grasp_success and not payload_lost and place_success),
        "recorded_control_steps": recorder.steps,
        "recorded_video_frames": len(recorder.frames),
        "recorded_rgb_key_frames": recorder.key_frames,
        "recorded_depth_key_frames": recorder.depth_key_frames,
        "upstream": {
            "url": UPSTREAM_URL,
            "tested_commit": UPSTREAM_COMMIT,
            "local_root": str(reference_root),
        },
        "limitations": [
            "The planar base is position-controlled and navigation collision safety is enforced by the inflated A* grid.",
            "The holonomic base preserves its verified grasp heading while loaded instead of rotating the payload at path corners.",
            "The official Franka arm, finger pads, object contacts, payload retention, and release remain physically simulated.",
        ],
    }
    video_name = "mobile_mjcf_pipeline.mp4"
    if recorder.frames:
        imageio.mimsave(
            args.output_dir / video_name,
            recorder.frames,
            fps=max(1, round(100 / args.video_stride)),
        )
    result_name = "mobile_mjcf_pipeline_result.json"
    (args.output_dir / result_name).write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    artifacts = {
        "provenance": "Rendered directly from one continuous Genesis simulation state",
        "synthetic_or_reconstructed": False,
        "key_frames": recorder.key_frames,
        "depth_key_frames": recorder.depth_key_frames,
        "full_run_video": video_name if recorder.frames else None,
        "structured_result": result_name,
        "generated_robot_asset": str(planar_mjcf.relative_to(args.output_dir)),
        "upstream_credit": UPSTREAM_URL,
        "upstream_commit": UPSTREAM_COMMIT,
    }
    (args.output_dir / "artifact_manifest.json").write_text(
        json.dumps(artifacts, indent=2), encoding="utf-8"
    )
    print(json.dumps({**result, "artifacts": artifacts}, indent=2))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run navigation, official-MJCF grasp, transport, and placement"
    )
    parser.add_argument("--reference-root", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20260729)
    parser.add_argument(
        "--object-profile",
        choices=sorted(OBJECT_PROFILES),
        default="parcel_medium",
    )
    parser.add_argument("--source-zone", choices=sorted(SEMANTIC_DOCKS))
    parser.add_argument("--target-zone", choices=sorted(SEMANTIC_DOCKS))
    parser.add_argument("--navigation-steps", type=int, default=30)
    parser.add_argument("--transport-steps", type=int, default=100)
    parser.add_argument(
        "--carry-mode",
        choices=("auto", "lifted", "body_centered"),
        default="auto",
    )
    parser.add_argument("--max-recenters", type=int, default=2)
    parser.add_argument("--slip-drift-threshold-m", type=float, default=0.025)
    parser.add_argument(
        "--disable-slip-monitoring",
        action="store_true",
        help="Ablation only: disable continuous transport slip monitoring.",
    )
    parser.add_argument("--unload-height-m", type=float, default=0.04)
    parser.add_argument("--unload-step-m", type=float, default=0.005)
    parser.add_argument("--unload-drift-threshold-m", type=float, default=0.004)
    parser.add_argument("--unload-preloss-distance-m", type=float, default=0.150)
    parser.add_argument("--unload-max-regrips", type=int, default=8)
    parser.add_argument("--video-stride", type=int, default=12)
    parser.add_argument(
        "--no-video",
        action="store_true",
        help="Skip frame rendering for faster batch evaluation; JSON metrics remain.",
    )
    parser.add_argument(
        "--grip-preload-m",
        type=float,
        default=0.0,
        help="Per-finger position preload applied after force-contact closure",
    )
    parser.add_argument("--grip-preload-steps", type=int, default=1)
    parser.add_argument(
        "--grasp-z-offset-m",
        type=float,
        default=0.0,
        help="Adjustment applied to the geometry-derived hand grasp height.",
    )
    args = parser.parse_args()
    run(args)


if __name__ == "__main__":
    main()
