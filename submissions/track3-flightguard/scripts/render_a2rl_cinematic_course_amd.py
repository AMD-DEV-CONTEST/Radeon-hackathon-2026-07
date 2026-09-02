#!/usr/bin/env python3
"""Render a continuous-lookahead cinematic FlightGuard run on the A2RL-derived layout."""

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
FPS = 50
STEPS_PER_FRAME = 2
RESOLUTION = (1280, 720)
DISCLAIMER = "SIMULATION-ONLY | VISUAL-ONLY | METRIC-INELIGIBLE"
HUD_TITLE = "A2RL-derived training layout"
LOOKAHEAD_DISTANCE_M = 1.35
CURVATURE_LOOKAHEAD_M = 1.50
CRUISE_SPEED_MPS = 2.20
MIN_CORNER_SPEED_MPS = 1.00
PATH_KP_CROSS_XY = 1.50
PATH_KP_ALONG_XY = 0.25
PATH_KD_XY = 1.80
PATH_KP_CROSS_Z = 4.00
PATH_KP_ALONG_Z = 0.60
PATH_KD_Z = 3.00
STOP_SPEED_THRESHOLD_MPS = 0.20
SPEED_WINDOW_EDGE_STEPS = 100
CAMERA_MODE = "velocity_tangent_cinematic"
FOLLOW_BEHIND_M = 2.50
FOLLOW_BEHIND_VARIATION_M = 0.15
FOLLOW_UP_M = 0.90
FOLLOW_LOOK_AHEAD_M = 1.60
FOLLOW_LOOK_UP_M = 0.20
FOLLOW_TRANSLATION_ALPHA = 0.30
FOLLOW_MAX_YAW_RATE_DEG_S = 75.0
CAMERA_FOV_DEG = 50.0
MINIMAP_PLACEMENT = "top-right"
MINIMAP_SIZE_PX = (240, 170)
MINIMAP_OPACITY = 0.75
MINIMAP_COURSE_LABEL = "A2RL-derived"
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

CINEMATIC_PATH_POINTS = (START,) + tuple(
    point
    for approach, center, exit_point in zip(APPROACH_WAYPOINTS, GATE_CENTERS, EXIT_WAYPOINTS, strict=True)
    for point in (approach, center, exit_point)
)
CINEMATIC_PATH_LENGTH_M = route_length(CINEMATIC_PATH_POINTS) if "route_length" in globals() else sum(
    math.dist(left, right) for left, right in zip(CINEMATIC_PATH_POINTS, CINEMATIC_PATH_POINTS[1:])
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
            "waypoint_policy": "arc-length continuous polyline over start + per-gate approach/center/exit",
            "approach_waypoints_m": APPROACH_WAYPOINTS,
            "exit_waypoints_m": EXIT_WAYPOINTS,
            "cinematic_path_points_m": CINEMATIC_PATH_POINTS,
            "cinematic_path_length_m": CINEMATIC_PATH_LENGTH_M,
        },
        "camera_mode": CAMERA_MODE,
        "camera": {
            "mode": CAMERA_MODE,
            "direction_source": "rate-limited blend of velocity and route tangent; never instantaneous waypoint",
            "behind_m": FOLLOW_BEHIND_M,
            "behind_variation_m": FOLLOW_BEHIND_VARIATION_M,
            "up_m": FOLLOW_UP_M,
            "look_ahead_m": FOLLOW_LOOK_AHEAD_M,
            "look_up_m": FOLLOW_LOOK_UP_M,
            "translation_alpha": FOLLOW_TRANSLATION_ALPHA,
            "max_yaw_rate_deg_s": FOLLOW_MAX_YAW_RATE_DEG_S,
            "fov_deg": CAMERA_FOV_DEG,
        },
        "minimap": {
            "enabled": True,
            "placement": MINIMAP_PLACEMENT,
            "size_px": MINIMAP_SIZE_PX,
            "opacity": MINIMAP_OPACITY,
            "course_label": MINIMAP_COURSE_LABEL,
            "aperture_label": MINIMAP_APERTURE_LABEL,
        },
        "raw_sampling": {
            "physics_dt_seconds": SIM_DT_SECONDS,
            "steps_per_frame": STEPS_PER_FRAME,
            "raw_fps": FPS,
            "uniform_schedule": True,
            "gate_event_extra_frames": False,
        },
        "route_scout": {
            "no_op_max_abs_difference": no_op_diff,
            "kill_magnitude_max_abs_m": round(kill_diff, 12),
            "segment_rank": matrix_rank(centered),
        },
        "all_finite": all(math.isfinite(value) for value in all_values),
        "controller_profile": "cinematic_velocity_pd_over_robust_z_actuator_mapping",
        "controller": {
            "path_parameterization": "arc_length_polyline",
            "lookahead_m": LOOKAHEAD_DISTANCE_M,
            "curvature_lookahead_m": CURVATURE_LOOKAHEAD_M,
            "cruise_speed_mps": CRUISE_SPEED_MPS,
            "minimum_corner_speed_mps": MIN_CORNER_SPEED_MPS,
            "nonzero_velocity_reference": True,
        },
        "seed": SEED,
        "max_steps": MAX_STEPS,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--geometry-only", action="store_true", help="CPU-only geometry/no-op/kill/rank report")
    parser.add_argument("--headless", action="store_true", help="run identical control and gate logic without rendering frames")
    parser.add_argument("--output", type=Path, help="new raw .mp4 path; forbidden with --headless")
    parser.add_argument("--receipt", type=Path, help="new canonical .json receipt path")
    args = parser.parse_args()
    if args.geometry_only:
        if args.headless or args.output is not None or args.receipt is not None:
            parser.error("--geometry-only does not accept --headless or output paths")
    elif args.headless:
        if args.output is not None or args.receipt is None:
            parser.error("--headless requires --receipt and forbids --output")
    elif args.output is None or args.receipt is None:
        parser.error("render mode requires distinct --output and --receipt")
    return args


def gate_offset(center, yaw, local_y, local_z):
    return (center[0] - math.sin(yaw) * local_y, center[1] + math.cos(yaw) * local_y, center[2] + local_z)


def make_scene_hook(width: int, height: int, *, with_camera: bool):
    def hook(*, gs, scene, drone, num_envs):
        del drone
        if num_envs != 1 or getattr(scene, "_is_built", None) is not False:
            raise RuntimeError("A2RL cinematic hook requires one unbuilt environment")
        frames = []
        colors = ((1.0, 0.3, 0.05, 1.0), (0.05, 0.45, 1.0, 1.0), (0.1, 0.85, 0.3, 1.0))
        for index, (center, yaw) in enumerate(zip(GATE_CENTERS, GATE_YAWS, strict=True)):
            members = ((-0.63, 0.0, (0.08, 0.06, 1.12)), (0.63, 0.0, (0.08, 0.06, 1.12)), (0.0, -0.53, (0.08, 1.32, 0.06)), (0.0, 0.53, (0.08, 1.32, 0.06)))
            frame = []
            for local_y, local_z, size in members:
                frame.append(scene.add_entity(material=gs.materials.Rigid(), morph=gs.morphs.Box(pos=gate_offset(center, yaw, local_y, local_z), euler=(0.0, 0.0, math.degrees(yaw)), size=size, fixed=True, collision=False, visualization=True), surface=gs.surfaces.Default(color=colors[index % len(colors)])))
            frames.append(tuple(frame))
        camera = None
        if with_camera:
            camera = scene.add_camera(model="pinhole", res=(width, height), pos=(0.0, -12.0, 8.0), lookat=(0.0, 0.0, 2.0), up=(0.0, 0.0, 1.0), fov=CAMERA_FOV_DEG, GUI=False, near=0.1, far=50.0, env_idx=0)
        return {"camera": camera, "gate_frames": tuple(frames)}
    return hook


def run_course(*, output: Path | None, receipt: Path, headless: bool) -> dict[str, object]:
    receipt = receipt.expanduser().resolve()
    output = None if output is None else output.expanduser().resolve()
    if receipt.suffix.lower() != ".json":
        raise ValueError("receipt must have .json suffix")
    if headless:
        if output is not None:
            raise ValueError("headless mode forbids video output")
    elif output is None or output.suffix.lower() != ".mp4" or output == receipt:
        raise ValueError("render mode requires distinct .mp4 output and .json receipt")
    receipt.parent.mkdir(parents=True, exist_ok=True)
    if receipt.exists() or (output is not None and output.exists()):
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

    config = controller_config_for_profile("robust_z")
    env = FlightGuardGenesisEnv(
        1,
        dt=SIM_DT_SECONDS,
        show_viewer=False,
        prebuild_scene_hook=make_scene_hook(*RESOLUTION, with_camera=not headless),
    )
    env.gates = torch.tensor(GATE_CENTERS, dtype=torch.float32, device=env.device).unsqueeze(0)
    env.gate_yaws = torch.tensor(GATE_YAWS, dtype=torch.float32, device=env.device).unsqueeze(0)
    env.base_position = torch.tensor(START, dtype=torch.float32, device=env.device)
    env.base_quaternion = torch.tensor(START_QUATERNION_WXYZ, dtype=torch.float32, device=env.device)
    env.reset(torch.arange(1, device=env.device))
    attachment = env.prebuild_attachment
    if not isinstance(attachment, dict) or len(attachment["gate_frames"]) != 13:
        raise RuntimeError("dynamic 13-gate geometry is missing")
    if headless and attachment["camera"] is not None:
        raise RuntimeError("headless mode unexpectedly created a camera")
    if not headless and attachment["camera"] is None:
        raise RuntimeError("render mode is missing its camera")

    controller = BatchedWaypointController(config)
    stage_dir = receipt.parent / f".{receipt.stem}.stage-{os.getpid()}-{uuid.uuid4().hex}"
    stage_dir.mkdir(mode=0o700)
    stage_video = stage_dir / "render.mp4"
    writer = None
    if not headless:
        writer = cv2.VideoWriter(str(stage_video), cv2.VideoWriter_fourcc(*"FMP4"), FPS, RESOLUTION, True)
        if not writer.isOpened():
            raise RuntimeError("OpenCV could not open stage video")

    path = np.asarray(CINEMATIC_PATH_POINTS, dtype=np.float64)
    segments = path[1:] - path[:-1]
    segment_lengths = np.linalg.norm(segments, axis=1)
    if path.shape != (40, 3) or not np.isfinite(path).all() or np.any(segment_lengths <= 1.0e-6):
        raise RuntimeError("invalid cinematic path")
    segment_length_sq = segment_lengths * segment_lengths
    cumulative = np.concatenate((np.asarray((0.0,), dtype=np.float64), np.cumsum(segment_lengths)))
    progress_s = 0.0

    def sample_path(distance: float) -> tuple[np.ndarray, np.ndarray]:
        clipped = min(max(float(distance), 0.0), float(cumulative[-1]))
        index = min(int(np.searchsorted(cumulative, clipped, side="right") - 1), len(segments) - 1)
        fraction = (clipped - cumulative[index]) / segment_lengths[index]
        point = path[index] + fraction * segments[index]
        tangent = segments[index] / segment_lengths[index]
        return point, tangent

    def project_path(position: np.ndarray, previous: float) -> float:
        relative = position[None, :] - path[:-1]
        fractions = np.clip(np.sum(relative * segments, axis=1) / segment_length_sq, 0.0, 1.0)
        projections = path[:-1] + fractions[:, None] * segments
        distances = np.sum((projections - position[None, :]) ** 2, axis=1)
        candidates = cumulative[:-1] + fractions * segment_lengths
        valid = (candidates >= max(0.0, previous - 0.25)) & (candidates <= previous + 5.0)
        if not bool(valid.any()):
            raise RuntimeError("no local arc-length projection candidate")
        distances = np.where(valid, distances, np.inf)
        selected = float(candidates[int(np.argmin(distances))])
        if not math.isfinite(selected):
            raise RuntimeError("nonfinite path projection")
        return max(previous, selected)

    def control_target(
        position_tensor: torch.Tensor,
        velocity_tensor: torch.Tensor,
    ) -> tuple[torch.Tensor, np.ndarray, float, float]:
        nonlocal progress_s
        position_np = position_tensor[0].detach().to("cpu").numpy().astype(np.float64, copy=False)
        velocity_np = velocity_tensor[0].detach().to("cpu").numpy().astype(np.float64, copy=False)
        progress_s = project_path(position_np, progress_s)
        path_target, tangent = sample_path(progress_s + LOOKAHEAD_DISTANCE_M)
        _, future_tangent = sample_path(progress_s + LOOKAHEAD_DISTANCE_M + CURVATURE_LOOKAHEAD_M)
        cosine = float(np.clip(np.dot(tangent, future_tangent), -1.0, 1.0))
        turn = math.acos(cosine)
        turn_fraction = min(turn / (0.5 * math.pi), 1.0)
        speed_reference = CRUISE_SPEED_MPS - (CRUISE_SPEED_MPS - MIN_CORNER_SPEED_MPS) * turn_fraction
        speed_reference = min(max(speed_reference, MIN_CORNER_SPEED_MPS), CRUISE_SPEED_MPS)
        velocity_reference = speed_reference * tangent
        error = path_target - position_np
        along = float(np.dot(error, tangent))
        cross = error - along * tangent
        desired_acceleration = np.asarray(
            (
                PATH_KP_CROSS_XY * cross[0] + PATH_KP_ALONG_XY * along * tangent[0] + PATH_KD_XY * (velocity_reference[0] - velocity_np[0]),
                PATH_KP_CROSS_XY * cross[1] + PATH_KP_ALONG_XY * along * tangent[1] + PATH_KD_XY * (velocity_reference[1] - velocity_np[1]),
                PATH_KP_CROSS_Z * cross[2] + PATH_KP_ALONG_Z * along * tangent[2] + PATH_KD_Z * (velocity_reference[2] - velocity_np[2]),
            ),
            dtype=np.float64,
        )
        if not np.isfinite(desired_acceleration).all():
            raise RuntimeError("nonfinite cinematic PD acceleration")
        effective_target = position_np.copy()
        effective_target[:2] += (
            desired_acceleration[:2] + config.velocity_kd_xy * velocity_np[:2]
        ) / config.position_kp_xy
        effective_target[2] += (
            desired_acceleration[2] + config.velocity_kd_z * velocity_np[2]
        ) / config.position_kp_z
        target_tensor = position_tensor.new_tensor(effective_target).unsqueeze(0)
        return target_tensor, tangent, speed_reference, progress_s

    finite_latches = {
        "action": True,
        "position": True,
        "quaternion": True,
        "velocity": True,
        "angular_velocity": True,
    }
    passed_steps: list[int] = []
    failure_reasons: list[str] = []
    speed_samples: list[float] = []
    reference_speed_samples: list[float] = []
    out_of_bounds = False
    struck_any = False
    post_step_samples = 0
    max_action = 0.0
    saturated = 0
    action_count = 0
    started = time.monotonic()
    camera_state: dict[str, np.ndarray | None] = {
        "direction": None,
        "position": None,
        "lookat": None,
    }
    last_tangent = np.asarray((1.0, 0.0, 0.0), dtype=np.float64)
    last_rendered_step = -1

    minimap_path_xy = path[:, :2]
    minimap_x_min = float(minimap_path_xy[:, 0].min())
    minimap_x_max = float(minimap_path_xy[:, 0].max())
    minimap_y_min = float(minimap_path_xy[:, 1].min())
    minimap_y_max = float(minimap_path_xy[:, 1].max())

    def set_follow_camera(position: np.ndarray, velocity: np.ndarray, route_tangent: np.ndarray) -> None:
        position = np.asarray(position, dtype=np.float64)
        velocity = np.asarray(velocity, dtype=np.float64)
        route_tangent = np.asarray(route_tangent, dtype=np.float64)
        if not (np.isfinite(position).all() and np.isfinite(velocity).all() and np.isfinite(route_tangent).all()):
            raise RuntimeError("nonfinite cinematic camera input")
        velocity_xy = velocity[:2]
        tangent_xy = route_tangent[:2]
        velocity_norm = float(np.linalg.norm(velocity_xy))
        tangent_norm = float(np.linalg.norm(tangent_xy))
        if tangent_norm <= 1.0e-9:
            tangent_xy = camera_state["direction"] if camera_state["direction"] is not None else np.asarray((1.0, 0.0))
            tangent_norm = float(np.linalg.norm(tangent_xy))
        tangent_xy = tangent_xy / tangent_norm
        if velocity_norm > 0.25:
            desired_direction = 0.75 * (velocity_xy / velocity_norm) + 0.25 * tangent_xy
        else:
            desired_direction = tangent_xy
        desired_norm = float(np.linalg.norm(desired_direction))
        if desired_norm <= 1.0e-9 or not math.isfinite(desired_norm):
            raise RuntimeError("undefined cinematic camera direction")
        desired_direction = desired_direction / desired_norm
        previous_direction = camera_state["direction"]
        if previous_direction is None:
            direction = desired_direction
        else:
            dot = float(np.clip(np.dot(previous_direction, desired_direction), -1.0, 1.0))
            cross = float(previous_direction[0] * desired_direction[1] - previous_direction[1] * desired_direction[0])
            delta = math.atan2(cross, dot)
            max_delta = math.radians(FOLLOW_MAX_YAW_RATE_DEG_S) * SIM_DT_SECONDS * STEPS_PER_FRAME
            delta = min(max(delta, -max_delta), max_delta)
            c, s = math.cos(delta), math.sin(delta)
            direction = np.asarray(
                (c * previous_direction[0] - s * previous_direction[1], s * previous_direction[0] + c * previous_direction[1]),
                dtype=np.float64,
            )
            direction /= np.linalg.norm(direction)
        speed = float(np.linalg.norm(velocity))
        variation = FOLLOW_BEHIND_VARIATION_M * min(max((speed - 1.5) / 1.5, -1.0), 1.0)
        behind = FOLLOW_BEHIND_M + variation
        desired_position = np.asarray(
            (position[0] - behind * direction[0], position[1] - behind * direction[1], position[2] + FOLLOW_UP_M),
            dtype=np.float64,
        )
        desired_lookat = np.asarray(
            (position[0] + FOLLOW_LOOK_AHEAD_M * direction[0], position[1] + FOLLOW_LOOK_AHEAD_M * direction[1], position[2] + FOLLOW_LOOK_UP_M),
            dtype=np.float64,
        )
        if camera_state["position"] is None:
            smoothed_position, smoothed_lookat = desired_position, desired_lookat
        else:
            alpha = FOLLOW_TRANSLATION_ALPHA
            smoothed_position = (1.0 - alpha) * camera_state["position"] + alpha * desired_position
            smoothed_lookat = (1.0 - alpha) * camera_state["lookat"] + alpha * desired_lookat
        if float(np.linalg.norm(smoothed_lookat - smoothed_position)) <= 0.1:
            raise RuntimeError("invalid cinematic camera pose")
        camera_state["direction"] = direction
        camera_state["position"] = smoothed_position
        camera_state["lookat"] = smoothed_lookat
        attachment["camera"].set_pose(
            pos=tuple(float(value) for value in smoothed_position),
            lookat=tuple(float(value) for value in smoothed_lookat),
            up=(0.0, 0.0, 1.0),
        )

    def draw_minimap(frame: np.ndarray, position: np.ndarray, gate_index: int) -> None:
        panel_width, panel_height = MINIMAP_SIZE_PX
        panel_x = RESOLUTION[0] - panel_width - 18
        panel_y = 88
        plot_left, plot_right = panel_x + 12, panel_x + panel_width - 12
        plot_top, plot_bottom = panel_y + 36, panel_y + panel_height - 12
        x_padding = max(0.5, 0.08 * (minimap_x_max - minimap_x_min))
        y_padding = max(0.5, 0.08 * (minimap_y_max - minimap_y_min))
        x_min, x_max = minimap_x_min - x_padding, minimap_x_max + x_padding
        y_min, y_max = minimap_y_min - y_padding, minimap_y_max + y_padding

        def map_xy(point: np.ndarray) -> tuple[int, int]:
            x = plot_left + (float(point[0]) - x_min) / (x_max - x_min) * (plot_right - plot_left)
            y = plot_bottom - (float(point[1]) - y_min) / (y_max - y_min) * (plot_bottom - plot_top)
            return int(round(x)), int(round(y))

        overlay = frame.copy()
        cv2.rectangle(overlay, (panel_x, panel_y), (panel_x + panel_width, panel_y + panel_height), (12, 16, 24), -1)
        course_pixels = np.asarray([map_xy(point) for point in minimap_path_xy], dtype=np.int32).reshape((-1, 1, 2))
        cv2.polylines(overlay, [course_pixels], False, (95, 120, 150), 1, cv2.LINE_AA)
        for point in np.asarray(GATE_CENTERS, dtype=np.float64):
            cv2.circle(overlay, map_xy(point[:2]), 2, (188, 196, 210), -1, cv2.LINE_AA)
        current = min(max(gate_index, 0), 12)
        cv2.circle(overlay, map_xy(np.asarray(GATE_CENTERS[current][:2])), 5, (0, 210, 255), 2, cv2.LINE_AA)
        cv2.circle(overlay, map_xy(position[:2]), 4, (255, 255, 255), -1, cv2.LINE_AA)
        cv2.putText(overlay, MINIMAP_COURSE_LABEL, (panel_x + 10, panel_y + 22), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (220, 228, 240), 1, cv2.LINE_AA)
        cv2.addWeighted(overlay, MINIMAP_OPACITY, frame, 1.0 - MINIMAP_OPACITY, 0.0, frame)

    def write_frame(step: int) -> None:
        nonlocal last_rendered_step
        if writer is None:
            raise RuntimeError("headless mode attempted to render")
        position = env.drone.get_pos()[0].detach().to("cpu").numpy()
        velocity = env.drone.get_vel()[0].detach().to("cpu").numpy()
        if step != 0:
            set_follow_camera(position, velocity, last_tangent)
        rgb = np.asarray(attachment["camera"].render(rgb=True)[0])
        if rgb.shape != (RESOLUTION[1], RESOLUTION[0], 3) or rgb.dtype != np.uint8 or not np.isfinite(rgb).all():
            raise RuntimeError("invalid RGB frame")
        bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        cv2.rectangle(bgr, (0, 0), (RESOLUTION[0], 76), (0, 0, 0), -1)
        cv2.putText(bgr, DISCLAIMER, (18, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.64, (255, 255, 255), 2, cv2.LINE_AA)
        gate_index = min(max(int(env.gate_index[0].item()), 0), 13)
        cv2.putText(bgr, f"{HUD_TITLE} | step={step} | gate={gate_index}/13", (18, 58), cv2.FONT_HERSHEY_SIMPLEX, 0.58, (180, 220, 255), 2, cv2.LINE_AA)
        draw_minimap(bgr, position, min(gate_index, 12))
        writer.write(bgr)
        last_rendered_step = step

    if not headless:
        write_frame(0)
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
                target, tangent, speed_reference, _ = control_target(position, velocity)
                last_tangent = tangent
                reference_speed_samples.append(speed_reference)
                action = controller(position, quaternion, velocity, angular_velocity, target)
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
                speed_samples.append(float(torch.linalg.vector_norm(post_velocity[0]).item()))
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
                if passed:
                    passed_steps.append(step)
                all_finite_now = all(finite_latches.values())
                completed = int(env.gate_index[0].item()) >= len(GATE_CENTERS)
                if not headless and all_finite_now and step % STEPS_PER_FRAME == 0:
                    write_frame(step)
                if not all_finite_now:
                    failure_reasons.append("nonfinite_post_step_state")
                if out_of_bounds:
                    failure_reasons.append("out_of_bounds")
                if struck_any:
                    failure_reasons.append("gate_frame_strike")
                if bool(result.done[0].item()) and not completed:
                    failure_reasons.append("terminated_before_completion")
                if failure_reasons or bool(result.done[0].item()):
                    if not headless and all_finite_now and step != last_rendered_step:
                        write_frame(step)
                    break
    finally:
        if writer is not None:
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

    edge = SPEED_WINDOW_EDGE_STEPS
    moving_speeds = speed_samples[edge:-edge] if len(speed_samples) > 2 * edge else []
    if moving_speeds:
        speed_quantiles = np.quantile(np.asarray(moving_speeds, dtype=np.float64), (0.05, 0.50, 0.95))
        stop_fraction = sum(value < STOP_SPEED_THRESHOLD_MPS for value in moving_speeds) / len(moving_speeds)
    else:
        speed_quantiles = np.asarray((float("nan"),) * 3)
        stop_fraction = 1.0
        failure_reasons.append("insufficient_moving_speed_window")
    if not np.isfinite(speed_quantiles).all() or not math.isfinite(stop_fraction):
        failure_reasons.append("nonfinite_speed_audit")
    if stop_fraction > 0.05:
        failure_reasons.append("stop_fraction_above_threshold")
    failure_reasons = list(dict.fromkeys(failure_reasons))
    passed_science_gate = (
        completed
        and all_finite
        and not out_of_bounds
        and not struck_any
        and saturation_fraction <= saturation_threshold
        and stop_fraction <= 0.05
        and not failure_reasons
    )

    decoded = 0
    output_sha = None
    output_size = None
    if not headless:
        capture = cv2.VideoCapture(str(stage_video))
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
        output_sha = sha256_file(output)
        output_size = output.stat().st_size

    payload = geometry_report()
    payload.update({
        "status": "PASS" if passed_science_gate else "FAIL",
        "failure_reasons": failure_reasons,
        "mode": "headless" if headless else "render",
        "headless": headless,
        "output": None if output is None else str(output),
        "output_sha256": output_sha,
        "output_size_bytes": output_size,
        "receipt": str(receipt),
        "passed_gates": len(passed_steps),
        "passed_steps": passed_steps,
        "completion_step": passed_steps[-1] if completed else None,
        "final_gate_index": final_gate_index,
        "decoded_frames": decoded,
        "raw_sampling": {
            "physics_dt_seconds": SIM_DT_SECONDS,
            "steps_per_frame": STEPS_PER_FRAME,
            "raw_fps": FPS,
            "uniform_schedule": True,
            "gate_event_extra_frames": False,
            "last_rendered_step": None if headless else last_rendered_step,
        },
        "speed_mps": {
            "p05": float(speed_quantiles[0]),
            "median": float(speed_quantiles[1]),
            "p95": float(speed_quantiles[2]),
            "stop_threshold_mps": STOP_SPEED_THRESHOLD_MPS,
            "stop_fraction": stop_fraction,
            "window_excludes_first_steps": edge,
            "window_excludes_final_steps": edge,
            "sample_count": len(moving_speeds),
            "reference_min_mps": min(reference_speed_samples) if reference_speed_samples else None,
            "reference_max_mps": max(reference_speed_samples) if reference_speed_samples else None,
        },
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
            "stop_fraction_lte_0_05": stop_fraction <= 0.05,
        },
        "walltime_seconds": time.monotonic() - started,
        "process_pid": os.getpid(),
        "visible_gpu_count": torch.cuda.device_count(),
        "torch_version": torch.__version__,
        "torch_hip": torch.version.hip,
        "genesis_version": gs.__version__,
        "core_sha256": CORE_SHA256,
    })
    stage_receipt = stage_dir / "receipt.json"
    fd = os.open(stage_receipt, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
    with os.fdopen(fd, "wb") as handle:
        handle.write(canonical_json(payload))
        handle.flush()
        os.fsync(handle.fileno())
    os.link(stage_receipt, receipt)
    if stage_video.exists():
        stage_video.unlink()
    stage_receipt.unlink()
    stage_dir.rmdir()
    return payload


def main() -> None:
    args = parse_args()
    payload = (
        geometry_report()
        if args.geometry_only
        else run_course(output=args.output, receipt=args.receipt, headless=args.headless)
    )
    print(canonical_json(payload).decode(), end="", flush=True)
    if not args.geometry_only and payload["status"] != "PASS":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
