#!/usr/bin/env python3
"""Render a transformed A2RL layout in FlightGuard Genesis for visual evidence only."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import time
import uuid
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
GENESIS_SOURCE_ROOT = Path("/workspace/genesis-v1.2.3-src-b")
SOURCE_YAML_SHA256 = "101bb84602f7b3f7d11681c1d6ee5600fb13bcc702941be8d492fc502f77b8be"
SOURCE_LAYOUT = (
    (12.5, 2.0, 1.0, 3.14),
    (6.5, 6.0, 1.0, 2.36),
    (5.5, 14.0, 1.0, 2.093),
    (2.5, 24.0, 1.0, 1.57),
    (7.5, 30.0, 1.0, 6.11),
    (12.2, 22.0, 1.0, 6.28),
    (17.5, 30.0, 3.0, 7.68),
    (17.5, 30.0, 1.0, 4.54),
    (18.0, 22.0, 1.0, 4.88),
    (20.5, 14.0, 1.0, 4.54),
    (18.5, 6.0, 3.0, 3.92),
    (18.5, 6.0, 1.0, 3.92),
    (12.5, 2.0, 1.0, 3.14),
)
CORE_SHA256 = {
    "src/flightguard/genesis_env.py": "2db209890e6604f6259b0f3947ce6bc722e822f45e329f9111c846e88955c855",
    "src/flightguard/gate_math.py": "36977cb4742cbb9e11a82f3819153af7e85b5e8c513d073d4902b078b7f63117",
    "src/flightguard/controller.py": "38902e1b8781026b5566ce73e8bc24d8d87d328a206349319502d86633b194e7",
}
PLAN_SCALE = 0.60
PLAN_ORIGIN = (11.5, 16.0)
SOURCE_GATE_WIDTH_M = 1.0
SOURCE_GATE_HEIGHT_M = 2.0
FG_HALF_WIDTH_M = 0.60
FG_HALF_HEIGHT_M = 0.50
FG_PROXY_RADIUS_M = 0.08
APPROACH_EXIT_DISTANCE_M = 1.0
APPROACH_CAPTURE_RADIUS_M = 0.35
START_LOCAL_OFFSET = (-1.5, 0.0, 0.6)
START_QUATERNION_WXYZ = (1.0, 0.0, 0.0, 0.0)
SEED = 6201
MAX_STEPS = 10_000
SIM_DT_SECONDS = 0.01
FPS = 20
STEPS_PER_FRAME = 5
RESOLUTION = (1280, 720)
DISCLAIMER = "SIMULATION-ONLY | VISUAL-ONLY | METRIC-INELIGIBLE"
CAMERA_MODE = "deterministic_follow"
FOLLOW_BEHIND_M = 3.0
FOLLOW_UP_M = 1.2
FOLLOW_LOOK_AHEAD_M = 1.2
FOLLOW_LOOK_UP_M = 0.25
FOLLOW_SMOOTHING_ALPHA = 0.25
MINIMAP_PLACEMENT = "top-right"
MINIMAP_COURSE_LABEL = "A2RL-derived 13-crossing layout"
MINIMAP_APERTURE_LABEL = "FlightGuard aperture"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json(payload: object) -> bytes:
    return (json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def transformed_center(row: tuple[float, float, float, float]) -> tuple[float, float, float]:
    x, y, z_bottom, _ = row
    return (PLAN_SCALE * (x - PLAN_ORIGIN[0]), PLAN_SCALE * (y - PLAN_ORIGIN[1]), z_bottom + 1.0)


RAW_CENTERS = tuple((x, y, z + 1.0) for x, y, z, _ in SOURCE_LAYOUT)
GATE_CENTERS = tuple(transformed_center(row) for row in SOURCE_LAYOUT)
GATE_YAWS = tuple(row[3] for row in SOURCE_LAYOUT)


def raw_start() -> tuple[float, float, float]:
    x, y, z_bottom, yaw = SOURCE_LAYOUT[0]
    dx, dy, dz = START_LOCAL_OFFSET
    return (
        x + math.cos(yaw) * dx - math.sin(yaw) * dy,
        y + math.sin(yaw) * dx + math.cos(yaw) * dy,
        z_bottom + dz,
    )


RAW_START = raw_start()
START = (
    PLAN_SCALE * (RAW_START[0] - PLAN_ORIGIN[0]),
    PLAN_SCALE * (RAW_START[1] - PLAN_ORIGIN[1]),
    RAW_START[2],
)


def waypoint(center: tuple[float, float, float], yaw: float, distance: float) -> tuple[float, float, float]:
    return (center[0] + distance * math.cos(yaw), center[1] + distance * math.sin(yaw), center[2])


APPROACH_WAYPOINTS = tuple(
    waypoint(center, yaw, -APPROACH_EXIT_DISTANCE_M)
    for center, yaw in zip(GATE_CENTERS, GATE_YAWS, strict=True)
)
EXIT_WAYPOINTS = tuple(
    waypoint(center, yaw, APPROACH_EXIT_DISTANCE_M)
    for center, yaw in zip(GATE_CENTERS, GATE_YAWS, strict=True)
)


def route_length(points: tuple[tuple[float, float, float], ...]) -> float:
    return sum(math.dist(a, b) for a, b in zip(points, points[1:]))


def point_bounds(points: tuple[tuple[float, float, float], ...]) -> dict[str, list[float]]:
    return {
        "min": [min(point[axis] for point in points) for axis in range(3)],
        "max": [max(point[axis] for point in points) for axis in range(3)],
    }


def matrix_rank(rows: tuple[tuple[float, float, float], ...], tolerance: float = 1e-10) -> int:
    matrix = [list(map(float, row)) for row in rows]
    rank = 0
    for column in range(3):
        pivot = max(range(rank, len(matrix)), key=lambda index: abs(matrix[index][column]))
        if abs(matrix[pivot][column]) <= tolerance:
            continue
        matrix[rank], matrix[pivot] = matrix[pivot], matrix[rank]
        divisor = matrix[rank][column]
        matrix[rank] = [value / divisor for value in matrix[rank]]
        for index, row in enumerate(matrix):
            if index != rank:
                factor = row[column]
                matrix[index] = [value - factor * basis for value, basis in zip(row, matrix[rank], strict=True)]
        rank += 1
    return rank


def geometry_report() -> dict[str, object]:
    no_op = tuple((x, y, z) for x, y, z in RAW_CENTERS)
    no_op_diff = max(abs(a - b) for left, right in zip(no_op, RAW_CENTERS, strict=True) for a, b in zip(left, right, strict=True))
    killed = list(GATE_CENTERS)
    killed[0] = (killed[0][0] + 0.8, killed[0][1], killed[0][2])
    kill_diff = max(abs(a - b) for left, right in zip(killed, GATE_CENTERS, strict=True) for a, b in zip(left, right, strict=True))
    mean = tuple(sum(point[axis] for point in GATE_CENTERS[:12]) / 12.0 for axis in range(3))
    centered = tuple(tuple(point[axis] - mean[axis] for axis in range(3)) for point in GATE_CENTERS[:12])
    all_values = [value for row in SOURCE_LAYOUT for value in row]
    all_values += [value for point in GATE_CENTERS for value in point]
    all_values += list(RAW_START) + list(START)
    return {
        "status": "GEOMETRY_ONLY_PASS",
        "simulation_only": True,
        "visual_only": True,
        "metric_eligible": False,
        "script_sha256": sha256_file(Path(__file__).resolve()),
        "source": {
            "description": "user A2RL training layout from DroneRace_v147.emitted.yaml",
            "yaml_sha256": SOURCE_YAML_SHA256,
            "units": "meters and radians",
            "coordinate_convention": "Z-up; yaw about +Z; gate local +X is forward normal",
            "gate_width_m": SOURCE_GATE_WIDTH_M,
            "gate_height_m": SOURCE_GATE_HEIGHT_M,
            "obstacles": "none beyond ground and gate frames",
            "poses_xy_zbottom_yaw": SOURCE_LAYOUT,
        },
        "layout": {
            "crossing_count": len(SOURCE_LAYOUT),
            "unique_physical_pose_count": len(set(SOURCE_LAYOUT)),
            "gate13_exactly_equals_gate1": SOURCE_LAYOUT[-1] == SOURCE_LAYOUT[0],
            "stacked_gate_pairs_1based": [[7, 8], [11, 12]],
            "raw_center_bounds_m": point_bounds(RAW_CENTERS),
            "transformed_center_bounds_m": point_bounds(GATE_CENTERS),
            "raw_route_length_m": route_length(RAW_CENTERS),
            "transformed_route_length_m": route_length(GATE_CENTERS),
            "transformed_gate_centers_m": GATE_CENTERS,
            "gate_yaws_rad": GATE_YAWS,
        },
        "adapter": {
            "plan_transform": "x'=0.60*(x-11.5), y'=0.60*(y-16), z'=z_bottom+1",
            "plan_scale": PLAN_SCALE,
            "exact_physical_scale_claim": False,
            "aperture": "imported layout under FlightGuard 1.2m x 1.0m scoring aperture",
            "flightguard_aperture_width_m": 2.0 * FG_HALF_WIDTH_M,
            "flightguard_aperture_height_m": 2.0 * FG_HALF_HEIGHT_M,
            "proxy_radius_m": FG_PROXY_RADIUS_M,
            "visual_adapter_start": {
                "provenance": "derived from the original reset-code convention; not a YAML runtime fact",
                "source_frame_m": RAW_START,
                "transformed_m": START,
                "quaternion_wxyz": START_QUATERNION_WXYZ,
            },
            "waypoint_policy": "per gate: approach center-1.0*n, then exit center+1.0*n",
            "approach_waypoints_m": APPROACH_WAYPOINTS,
            "exit_waypoints_m": EXIT_WAYPOINTS,
        },
        "camera_mode": CAMERA_MODE,
        "minimap": {
            "enabled": True,
            "placement": MINIMAP_PLACEMENT,
            "course_label": MINIMAP_COURSE_LABEL,
            "aperture_label": MINIMAP_APERTURE_LABEL,
        },
        "route_scout": {
            "no_op_max_abs_difference": no_op_diff,
            "kill_magnitude_max_abs_m": round(kill_diff, 12),
            "segment_rank": matrix_rank(centered),
        },
        "all_finite": all(math.isfinite(value) for value in all_values),
        "controller_profile": "robust_z",
        "seed": SEED,
        "max_steps": MAX_STEPS,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--geometry-only", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    if args.geometry_only:
        if args.output is not None or args.receipt is not None:
            parser.error("--geometry-only does not accept output paths")
    elif args.output is None:
        parser.error("--output is required for a real render")
    return args


def gate_offset(center, yaw, local_y, local_z):
    return (center[0] - math.sin(yaw) * local_y, center[1] + math.cos(yaw) * local_y, center[2] + local_z)


def make_scene_hook(width: int, height: int):
    def hook(*, gs, scene, drone, num_envs):
        del drone
        if num_envs != 1 or getattr(scene, "_is_built", None) is not False:
            raise RuntimeError("A2RL visual hook requires one unbuilt environment")
        frames = []
        colors = ((1.0, 0.3, 0.05, 1.0), (0.05, 0.45, 1.0, 1.0), (0.1, 0.85, 0.3, 1.0))
        for index, (center, yaw) in enumerate(zip(GATE_CENTERS, GATE_YAWS, strict=True)):
            members = ((-0.63, 0.0, (0.08, 0.06, 1.12)), (0.63, 0.0, (0.08, 0.06, 1.12)), (0.0, -0.53, (0.08, 1.32, 0.06)), (0.0, 0.53, (0.08, 1.32, 0.06)))
            frame = []
            for local_y, local_z, size in members:
                frame.append(scene.add_entity(material=gs.materials.Rigid(), morph=gs.morphs.Box(pos=gate_offset(center, yaw, local_y, local_z), euler=(0.0, 0.0, math.degrees(yaw)), size=size, fixed=True, collision=False, visualization=True), surface=gs.surfaces.Default(color=colors[index % len(colors)])))
            frames.append(tuple(frame))
        camera = scene.add_camera(model="pinhole", res=(width, height), pos=(0.0, -18.0, 15.0), lookat=(0.0, 0.0, 2.0), up=(0.0, 0.0, 1.0), fov=55.0, GUI=False, near=0.1, far=50.0, env_idx=0)
        return {"camera": camera, "gate_frames": tuple(frames)}
    return hook


def render(output: Path, receipt: Path | None) -> dict[str, object]:
    output = output.expanduser().resolve()
    receipt = (output.with_suffix(".json") if receipt is None else receipt.expanduser().resolve())
    if output.suffix.lower() != ".mp4" or receipt.suffix.lower() != ".json" or output == receipt:
        raise ValueError("real render requires distinct .mp4 output and .json receipt")
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists() or receipt.exists():
        raise FileExistsError("output or receipt already exists")
    for relative, expected in CORE_SHA256.items():
        actual = sha256_file(PROJECT_ROOT / relative)
        if actual != expected:
            raise RuntimeError(f"core source drift: {relative}: {actual}")
    sys.path.insert(0, str((PROJECT_ROOT / "src").resolve()))
    sys.path.insert(0, str(GENESIS_SOURCE_ROOT.resolve()))
    os.environ["HOME"] = "/root"
    import cv2
    import genesis as gs
    import numpy as np
    import torch
    gs.init(backend=gs.amdgpu, precision="32", seed=SEED, performance_mode=False, logging_level="warning")
    if str(getattr(gs, "__version__", "")) != "1.2.3" or gs.backend != gs.amdgpu:
        raise RuntimeError("frozen Genesis 1.2.3 AMD backend is required")
    if torch.version.hip is None or not torch.cuda.is_available() or torch.cuda.device_count() != 1:
        raise RuntimeError("exactly one visible Radeon GPU is required")
    from flightguard.controller import BatchedWaypointController, controller_config_for_profile
    from flightguard.genesis_env import FlightGuardGenesisEnv
    env = FlightGuardGenesisEnv(1, dt=SIM_DT_SECONDS, show_viewer=False, prebuild_scene_hook=make_scene_hook(*RESOLUTION))
    env.gates = torch.tensor(GATE_CENTERS, dtype=torch.float32, device=env.device).unsqueeze(0)
    env.gate_yaws = torch.tensor(GATE_YAWS, dtype=torch.float32, device=env.device).unsqueeze(0)
    env.base_position = torch.tensor(START, dtype=torch.float32, device=env.device)
    env.base_quaternion = torch.tensor(START_QUATERNION_WXYZ, dtype=torch.float32, device=env.device)
    env.reset(torch.arange(1, device=env.device))
    attachment = env.prebuild_attachment
    if not isinstance(attachment, dict) or len(attachment["gate_frames"]) != 13:
        raise RuntimeError("dynamic 13-gate geometry is missing")
    controller = BatchedWaypointController(controller_config_for_profile("robust_z"))
    stage_dir = output.parent / f".{output.name}.stage-{os.getpid()}-{uuid.uuid4().hex}"
    stage_dir.mkdir(mode=0o700)
    stage_video = stage_dir / "render.mp4"
    writer = cv2.VideoWriter(str(stage_video), cv2.VideoWriter_fourcc(*"FMP4"), FPS, RESOLUTION, True)
    if not writer.isOpened():
        raise RuntimeError("OpenCV could not open stage video")
    phase = "approach"
    passed_steps: list[int] = []
    failure_reasons: list[str] = []
    finite_latches = {
        "action": True,
        "position": True,
        "quaternion": True,
        "velocity": True,
        "angular_velocity": True,
    }
    out_of_bounds = False
    struck_any = False
    post_step_samples = 0
    max_action = 0.0
    saturated = 0
    action_count = 0
    started = time.monotonic()

    follow_state: dict[str, np.ndarray | None] = {"position": None, "lookat": None}
    minimap_course_xy = np.asarray([center[:2] for center in GATE_CENTERS], dtype=np.float64)
    minimap_x_min = float(minimap_course_xy[:, 0].min())
    minimap_x_max = float(minimap_course_xy[:, 0].max())
    minimap_y_min = float(minimap_course_xy[:, 1].min())
    minimap_y_max = float(minimap_course_xy[:, 1].max())
    if (
        not np.isfinite(minimap_course_xy).all()
        or minimap_x_max <= minimap_x_min
        or minimap_y_max <= minimap_y_min
    ):
        raise RuntimeError("invalid fixed minimap geometry")

    def set_follow_camera(position: np.ndarray, velocity: np.ndarray, target: tuple[float, float, float], gate_index: int) -> None:
        position = np.asarray(position, dtype=np.float64)
        velocity = np.asarray(velocity, dtype=np.float64)
        target_array = np.asarray(target, dtype=np.float64)
        if (
            position.shape != (3,)
            or velocity.shape != (3,)
            or target_array.shape != (3,)
            or not np.isfinite(position).all()
            or not np.isfinite(velocity).all()
            or not np.isfinite(target_array).all()
        ):
            raise RuntimeError("nonfinite follow-camera input")
        direction_xy = target_array[:2] - position[:2]
        direction_norm = float(np.linalg.norm(direction_xy))
        if direction_norm <= 1.0e-9:
            direction_xy = velocity[:2]
            direction_norm = float(np.linalg.norm(direction_xy))
        if direction_norm <= 1.0e-9:
            yaw = float(GATE_YAWS[gate_index])
            direction_xy = np.asarray((math.cos(yaw), math.sin(yaw)), dtype=np.float64)
            direction_norm = float(np.linalg.norm(direction_xy))
        if not math.isfinite(direction_norm) or direction_norm <= 1.0e-9:
            raise RuntimeError("follow-camera direction is undefined")
        direction_xy = direction_xy / direction_norm
        desired_position = np.asarray(
            (
                position[0] - FOLLOW_BEHIND_M * direction_xy[0],
                position[1] - FOLLOW_BEHIND_M * direction_xy[1],
                position[2] + FOLLOW_UP_M,
            ),
            dtype=np.float64,
        )
        desired_lookat = np.asarray(
            (
                position[0] + FOLLOW_LOOK_AHEAD_M * direction_xy[0],
                position[1] + FOLLOW_LOOK_AHEAD_M * direction_xy[1],
                position[2] + FOLLOW_LOOK_UP_M,
            ),
            dtype=np.float64,
        )
        if follow_state["position"] is None:
            smoothed_position = desired_position
            smoothed_lookat = desired_lookat
        else:
            smoothed_position = (
                (1.0 - FOLLOW_SMOOTHING_ALPHA) * follow_state["position"]
                + FOLLOW_SMOOTHING_ALPHA * desired_position
            )
            smoothed_lookat = (
                (1.0 - FOLLOW_SMOOTHING_ALPHA) * follow_state["lookat"]
                + FOLLOW_SMOOTHING_ALPHA * desired_lookat
            )
        if (
            not np.isfinite(smoothed_position).all()
            or not np.isfinite(smoothed_lookat).all()
            or float(np.linalg.norm(smoothed_lookat - smoothed_position)) <= 0.1
        ):
            raise RuntimeError("invalid smoothed follow-camera pose")
        follow_state["position"] = smoothed_position
        follow_state["lookat"] = smoothed_lookat
        attachment["camera"].set_pose(
            pos=tuple(float(value) for value in smoothed_position),
            lookat=tuple(float(value) for value in smoothed_lookat),
            up=(0.0, 0.0, 1.0),
        )

    def draw_minimap(frame: np.ndarray, position: np.ndarray, gate_index: int) -> None:
        panel_width, panel_height = 318, 224
        panel_x = RESOLUTION[0] - panel_width - 18
        panel_y = 88
        plot_left, plot_right = panel_x + 16, panel_x + panel_width - 16
        plot_top, plot_bottom = panel_y + 51, panel_y + panel_height - 13

        def map_xy(point: np.ndarray) -> tuple[int, int]:
            x_value, y_value = float(point[0]), float(point[1])
            if not math.isfinite(x_value) or not math.isfinite(y_value):
                raise RuntimeError("nonfinite minimap coordinate")
            x_pixel = plot_left + (x_value - minimap_x_min) / (minimap_x_max - minimap_x_min) * (plot_right - plot_left)
            y_pixel = plot_bottom - (y_value - minimap_y_min) / (minimap_y_max - minimap_y_min) * (plot_bottom - plot_top)
            return int(round(x_pixel)), int(round(y_pixel))

        cv2.rectangle(
            frame,
            (panel_x, panel_y),
            (panel_x + panel_width, panel_y + panel_height),
            (12, 16, 22),
            -1,
        )
        cv2.rectangle(
            frame,
            (panel_x, panel_y),
            (panel_x + panel_width, panel_y + panel_height),
            (105, 120, 142),
            1,
        )
        cv2.putText(
            frame,
            MINIMAP_COURSE_LABEL,
            (panel_x + 10, panel_y + 20),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.40,
            (235, 240, 248),
            1,
            cv2.LINE_AA,
        )
        cv2.putText(
            frame,
            MINIMAP_APERTURE_LABEL,
            (panel_x + 10, panel_y + 40),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.40,
            (180, 220, 255),
            1,
            cv2.LINE_AA,
        )
        course_pixels = np.asarray([map_xy(point) for point in minimap_course_xy], dtype=np.int32).reshape((-1, 1, 2))
        cv2.polylines(frame, [course_pixels], False, (120, 145, 175), 2, cv2.LINE_AA)
        for point in minimap_course_xy:
            cv2.circle(frame, map_xy(point), 3, (188, 196, 210), -1, cv2.LINE_AA)
        cv2.circle(frame, map_xy(minimap_course_xy[gate_index]), 7, (0, 210, 255), 2, cv2.LINE_AA)
        cv2.circle(frame, map_xy(position[:2]), 5, (255, 255, 255), -1, cv2.LINE_AA)

    def write_frame(step: int, gate_index: int, active_phase: str) -> None:
        current_gate_index = min(max(int(env.gate_index[0].item()), 0), len(GATE_CENTERS) - 1)
        if active_phase not in {"approach", "exit"}:
            raise RuntimeError(f"unknown visual phase: {active_phase}")
        position = env.drone.get_pos()[0].detach().to("cpu").numpy()
        velocity = env.drone.get_vel()[0].detach().to("cpu").numpy()
        target = (
            APPROACH_WAYPOINTS[current_gate_index]
            if active_phase == "approach"
            else EXIT_WAYPOINTS[current_gate_index]
        )
        if step != 0:
            set_follow_camera(position, velocity, target, current_gate_index)
        rgb = np.asarray(attachment["camera"].render(rgb=True)[0])
        if (
            rgb.shape != (RESOLUTION[1], RESOLUTION[0], 3)
            or rgb.dtype != np.uint8
            or not np.isfinite(rgb).all()
        ):
            raise RuntimeError("invalid RGB frame")
        bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        cv2.rectangle(bgr, (0, 0), (RESOLUTION[0], 76), (0, 0, 0), -1)
        cv2.putText(bgr, DISCLAIMER, (18, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.68, (255, 255, 255), 2, cv2.LINE_AA)
        cv2.putText(bgr, f"A2RL layout | step={step} | gate={min(gate_index + 1, 13)}/13 | phase={active_phase}", (18, 61), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (180, 220, 255), 2, cv2.LINE_AA)
        draw_minimap(bgr, position, current_gate_index)
        writer.write(bgr)

    write_frame(0, 0, phase)
    try:
        with torch.inference_mode():
            for step in range(1, MAX_STEPS + 1):
                gate_index = int(env.gate_index[0].item())
                if gate_index >= len(GATE_CENTERS):
                    break
                position = env.drone.get_pos()
                quaternion = env.drone.get_quat()
                velocity = env.drone.get_vel()
                angular_velocity = env.drone.get_ang()
                if phase == "approach":
                    approach = position.new_tensor(APPROACH_WAYPOINTS[gate_index]).unsqueeze(0)
                    if float(torch.linalg.vector_norm(position - approach).item()) <= APPROACH_CAPTURE_RADIUS_M:
                        phase = "exit"
                phase_before_step = phase
                target_data = APPROACH_WAYPOINTS[gate_index] if phase == "approach" else EXIT_WAYPOINTS[gate_index]
                action = controller(position, quaternion, velocity, angular_velocity, position.new_tensor(target_data))
                action_finite = bool(torch.isfinite(action).all().item())
                finite_latches["action"] = finite_latches["action"] and action_finite
                if not action_finite:
                    failure_reasons.append("nonfinite_action")
                    break
                max_action = max(max_action, float(action.abs().max().item()))
                saturated += int((action.abs() >= 1.0).sum().item())
                action_count += action.numel()
                result = env.step(action)
                post_position = env.drone.get_pos()
                post_quaternion = env.drone.get_quat()
                post_velocity = env.drone.get_vel()
                post_angular_velocity = env.drone.get_ang()
                post_step_samples += 1
                post_fields = {
                    "position": post_position,
                    "quaternion": post_quaternion,
                    "velocity": post_velocity,
                    "angular_velocity": post_angular_velocity,
                }
                for name, value in post_fields.items():
                    finite_latches[name] = finite_latches[name] and bool(torch.isfinite(value).all().item())
                post_out_of_bounds = bool(
                    (
                        (post_position[:, 2] < 0.1)
                        | (post_position[:, :2].abs() > 10.0).any(dim=1)
                        | (post_position[:, 2] > 5.0)
                    )[0].item()
                )
                out_of_bounds = out_of_bounds or post_out_of_bounds
                passed = bool(result.passed[0].item())
                struck_now = bool(result.struck[0].item())
                struck_any = struck_any or struck_now
                if phase_before_step == "approach" and (passed or struck_now):
                    failure_reasons.append("crossing_or_strike_during_approach")
                elif passed:
                    passed_steps.append(step)
                    phase = "approach"
                all_finite_now = all(finite_latches.values())
                completed = int(env.gate_index[0].item()) >= len(GATE_CENTERS)
                if all_finite_now and (
                    step % STEPS_PER_FRAME == 0 or passed or bool(result.done[0].item())
                ):
                    write_frame(step, gate_index, phase)
                if not all_finite_now:
                    failure_reasons.append("nonfinite_post_step_state")
                if out_of_bounds:
                    failure_reasons.append("out_of_bounds")
                if struck_any:
                    failure_reasons.append("gate_frame_strike")
                if bool(result.done[0].item()) and not completed:
                    failure_reasons.append("terminated_before_completion")
                if failure_reasons or bool(result.done[0].item()):
                    break
    finally:
        writer.release()
    final_gate_index = int(env.gate_index[0].item())
    completed = final_gate_index >= len(GATE_CENTERS) and len(passed_steps) == 13
    all_finite = all(finite_latches.values())
    saturation_fraction = saturated / action_count if action_count else 1.0
    saturation_threshold = 0.05
    if not completed:
        failure_reasons.append("course_incomplete")
    if not all_finite:
        failure_reasons.append("nonfinite")
    if out_of_bounds:
        failure_reasons.append("out_of_bounds")
    if struck_any:
        failure_reasons.append("struck")
    if saturation_fraction > saturation_threshold:
        failure_reasons.append("saturation_above_threshold")
    failure_reasons = list(dict.fromkeys(failure_reasons))
    passed_science_gate = (
        completed
        and all_finite
        and not out_of_bounds
        and not struck_any
        and saturation_fraction <= saturation_threshold
        and not failure_reasons
    )
    capture = cv2.VideoCapture(str(stage_video))
    decoded = 0
    while True:
        ok, frame = capture.read()
        if not ok:
            break
        if frame.shape != (RESOLUTION[1], RESOLUTION[0], 3):
            raise RuntimeError("decoded frame shape mismatch")
        decoded += 1
    capture.release()
    if decoded <= 0 or stage_video.stat().st_size <= 0:
        raise RuntimeError("empty rendered video")
    os.link(stage_video, output)
    payload = geometry_report()
    payload.update({
        "status": "PASS" if passed_science_gate else "FAIL",
        "failure_reasons": failure_reasons,
        "output": str(output),
        "output_sha256": sha256_file(output),
        "output_size_bytes": output.stat().st_size,
        "receipt": str(receipt),
        "passed_gates": len(passed_steps),
        "passed_steps": passed_steps,
        "completion_step": passed_steps[-1] if completed else None,
        "final_gate_index": final_gate_index,
        "decoded_frames": decoded,
        "fps": FPS,
        "simulation_steps_per_frame": STEPS_PER_FRAME,
        "maximum_abs_action": max_action,
        "saturation_fraction": saturation_fraction,
        "saturation_threshold": saturation_threshold,
        "all_finite": all_finite,
        "finite_latches": finite_latches,
        "post_step_samples": post_step_samples,
        "out_of_bounds": out_of_bounds,
        "struck": struck_any,
        "pass_criteria": {
            "completion_13_of_13": completed,
            "all_finite": all_finite,
            "out_of_bounds_false": not out_of_bounds,
            "struck_false": not struck_any,
            "saturation_fraction_lte_0_05": saturation_fraction <= saturation_threshold,
        },
        "walltime_seconds": time.monotonic() - started,
        "visible_gpu_count": torch.cuda.device_count(),
        "torch_version": torch.__version__,
        "torch_hip": torch.version.hip,
        "genesis_version": gs.__version__,
    })
    stage_receipt = stage_dir / "receipt.json"
    fd = os.open(stage_receipt, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
    with os.fdopen(fd, "wb") as handle:
        handle.write(canonical_json(payload))
        handle.flush()
        os.fsync(handle.fileno())
    os.link(stage_receipt, receipt)
    stage_video.unlink()
    stage_receipt.unlink()
    stage_dir.rmdir()
    return payload


def main() -> None:
    args = parse_args()
    payload = geometry_report() if args.geometry_only else render(args.output, args.receipt)
    print(canonical_json(payload).decode(), end="", flush=True)
    if not args.geometry_only and payload["status"] != "PASS":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
