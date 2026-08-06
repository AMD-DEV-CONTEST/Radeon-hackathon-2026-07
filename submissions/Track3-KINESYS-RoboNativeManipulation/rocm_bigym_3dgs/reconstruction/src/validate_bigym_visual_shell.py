#!/usr/bin/env python3
"""Run a deterministic 300-frame BiGym three-camera visual-shell acceptance."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

import av
import numpy as np
from PIL import Image, ImageDraw, ImageOps


ALIGNMENT_THRESHOLDS = {
    "floor_normal_tilt_degrees_max": 2.0,
    "capture_path_translation_m_max": 0.5,
    "capture_path_rotation_degrees_max": 65.0,
    "relative_scale_min": 0.4,
    "relative_scale_max": 1.2,
    "room_height_m_min": 2.0,
    "room_height_m_max": 5.0,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--task", default="DishwasherLoadPlates")
    parser.add_argument("--frames", type=int, default=300)
    parser.add_argument("--seed", type=int, default=20260727)
    parser.add_argument(
        "--bigym-dir",
        type=Path,
        default=Path(os.environ["BIGYM_DIR"]) if os.environ.get("BIGYM_DIR") else None,
        help="Patched BiGym checkout; defaults to the BIGYM_DIR environment variable.",
    )
    parser.add_argument(
        "--profile-already-calibrated",
        action="store_true",
        help=(
            "Reuse the profile's existing BiGym three-camera Sim(3). The "
            "stored camera poses must exactly match the current environment, "
            "preventing a second transform of an already-refined shell."
        ),
    )
    parser.add_argument(
        "--source-camera-index",
        type=int,
        help=(
            "Prefer one source capture view while still fitting an upright "
            "yaw-only Sim(3). This preserves a visually approved source "
            "direction without pitching or rolling the room."
        ),
    )
    return parser.parse_args()


def digest(frame: np.ndarray) -> str:
    return hashlib.sha256(frame.tobytes()).hexdigest()


def chw_to_pil(frame: np.ndarray, size: tuple[int, int]) -> Image.Image:
    rgb = np.moveaxis(np.asarray(frame, dtype=np.uint8), 0, -1)
    return ImageOps.fit(Image.fromarray(rgb, "RGB"), size, Image.Resampling.LANCZOS)


def mosaic(observation: dict[str, np.ndarray]) -> np.ndarray:
    canvas = Image.new("RGB", (1280, 960), "#070a0b")
    draw = ImageDraw.Draw(canvas)
    head = chw_to_pil(observation["rgb_head"], (848, 480))
    left = chw_to_pil(observation["rgb_left_wrist"], (640, 480))
    right = chw_to_pil(observation["rgb_right_wrist"], (640, 480))
    canvas.paste(head, (216, 0))
    canvas.paste(left, (0, 480))
    canvas.paste(right, (640, 480))
    draw.rectangle((216, 0, 1064, 34), fill=(4, 8, 10))
    draw.rectangle((0, 480, 640, 514), fill=(4, 8, 10))
    draw.rectangle((640, 480, 1280, 514), fill=(4, 8, 10))
    draw.text((228, 9), "head · D455 · 848x480", fill="#f2f6f7")
    draw.text((12, 489), "left wrist · D405 · 640x480", fill="#f2f6f7")
    draw.text((652, 489), "right wrist · D405 · 640x480", fill="#f2f6f7")
    return np.asarray(canvas)


def termination_diagnostics(env) -> dict[str, object]:
    """Explain task termination without confusing prop failure with robot failure."""

    pelvis_position = np.zeros(3, dtype=np.float64)
    pelvis_bind = env._mojo.physics.bind(env.robot.pelvis.mjcf)
    for index, actuator in enumerate(env.robot.floating_base.position_actuators):
        if actuator:
            pelvis_position[index] = float(
                env._mojo.physics.bind(actuator.joint).qpos.item()
            )
        else:
            pelvis_position[index] = float(pelvis_bind.pos[index])
    plates = list(getattr(env, "plates", []))
    plate_floor_collisions = sum(
        bool(plate.is_colliding(env.floor)) for plate in plates
    )
    return {
        "robot_pelvis_position_m": pelvis_position.tolist(),
        "robot_pelvis_norm_m": float(np.linalg.norm(pelvis_position)),
        "robot_distance_failure": bool(np.linalg.norm(pelvis_position) > 10.0),
        "plate_floor_collision_count": int(plate_floor_collisions),
        "task_success": bool(env.success),
        "task_fail": bool(env.fail),
        "simulation_healthy": bool(env.is_healthy),
    }


def normalized_rotation(linear: np.ndarray) -> np.ndarray:
    """Return the closest proper rotation to a uniformly scaled rotation."""

    u, _singular_values, vh = np.linalg.svd(
        np.asarray(linear, dtype=np.float64)
    )
    rotation = u @ vh
    if np.linalg.det(rotation) < 0.0:
        u[:, -1] *= -1.0
        rotation = u @ vh
    return rotation


def rotation_error_degrees(
    expected: np.ndarray,
    actual: np.ndarray,
) -> float:
    delta = normalized_rotation(expected).T @ normalized_rotation(actual)
    cosine = np.clip((np.trace(delta) - 1.0) / 2.0, -1.0, 1.0)
    return float(np.degrees(np.arccos(cosine)))


def rotation_errors_degrees(
    expected: np.ndarray,
    actual: np.ndarray,
) -> np.ndarray:
    """Return rotation error for every camera in ``actual``."""

    expected_rotation = normalized_rotation(expected)
    actual_rotations = np.asarray(
        [normalized_rotation(value) for value in np.asarray(actual)],
        dtype=np.float64,
    )
    delta = np.einsum(
        "ij,njk->nik",
        expected_rotation.T,
        actual_rotations,
    )
    cosine = np.clip(
        (np.trace(delta, axis1=1, axis2=2) - 1.0) / 2.0,
        -1.0,
        1.0,
    )
    return np.degrees(np.arccos(cosine))


def transform_bounds(
    minimum: np.ndarray,
    maximum: np.ndarray,
    transform: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    corners = np.asarray(
        [
            [x, y, z]
            for x in (minimum[0], maximum[0])
            for y in (minimum[1], maximum[1])
            for z in (minimum[2], maximum[2])
        ],
        dtype=np.float64,
    )
    transformed = (
        corners @ np.asarray(transform[:3, :3], dtype=np.float64).T
        + np.asarray(transform[:3, 3], dtype=np.float64)
    )
    return transformed.min(axis=0), transformed.max(axis=0)


def validate_precalibrated_profile(
    profile_path: Path,
    target_cameras: dict[str, dict[str, np.ndarray]],
) -> Path:
    """Accept an existing three-camera calibration only when it is not stale."""

    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    quality = profile.get("alignment_quality", {})
    if quality.get("status") != "passed" or not all(
        bool(value) for value in quality.get("checks", {}).values()
    ):
        raise RuntimeError(
            "precalibrated profile does not contain a passed alignment gate"
        )
    integration = profile.get("camera_integration", {})
    required = {"head", "left_wrist", "right_wrist"}
    if set(integration.get("target_cameras", [])) != required:
        raise RuntimeError(
            "precalibrated profile does not target all three BiGym cameras"
        )
    stored_poses = integration.get("target_camera_poses", {})
    if set(stored_poses) != required or set(target_cameras) != required:
        raise RuntimeError(
            "precalibrated profile camera-pose set does not match BiGym"
        )
    maximum_position_error = 0.0
    maximum_rotation_error = 0.0
    for name in sorted(required):
        stored_position = np.asarray(
            stored_poses[name]["position_m"],
            dtype=np.float64,
        )
        stored_rotation = np.asarray(
            stored_poses[name]["rotation_mujoco"],
            dtype=np.float64,
        )
        actual_position = np.asarray(
            target_cameras[name]["position"],
            dtype=np.float64,
        )
        actual_rotation = np.asarray(
            target_cameras[name]["rotation_mujoco"],
            dtype=np.float64,
        )
        packed = np.concatenate(
            [
                stored_position.ravel(),
                stored_rotation.ravel(),
                actual_position.ravel(),
                actual_rotation.ravel(),
            ]
        )
        if (
            stored_position.shape != (3,)
            or stored_rotation.shape != (3, 3)
            or actual_position.shape != (3,)
            or actual_rotation.shape != (3, 3)
            or not np.isfinite(packed).all()
        ):
            raise RuntimeError(f"invalid precalibrated camera pose for {name}")
        maximum_position_error = max(
            maximum_position_error,
            float(np.linalg.norm(stored_position - actual_position)),
        )
        maximum_rotation_error = max(
            maximum_rotation_error,
            rotation_error_degrees(stored_rotation, actual_rotation),
        )
    if maximum_position_error > 1e-6 or maximum_rotation_error > 1e-5:
        raise RuntimeError(
            "precalibrated profile is stale for the current BiGym camera rig: "
            f"position error={maximum_position_error:.9g} m, "
            f"rotation error={maximum_rotation_error:.9g} deg"
        )
    alignment_name = profile.get("alignment", {}).get(
        "path",
        "alignment.json",
    )
    alignment_path = profile_path.parent / alignment_name
    if not alignment_path.is_file():
        raise RuntimeError(
            f"precalibrated profile is missing alignment: {alignment_path}"
        )
    return profile_path


def calibrated_profile_for_three_cameras(
    profile_path: Path,
    output_dir: Path,
    target_cameras: dict[str, dict[str, np.ndarray]],
    preferred_source_index: int | None = None,
) -> Path:
    """Fit one upright Sim(3) to the initial head and both wrist cameras.

    The post-calibration deliberately has yaw only.  Pitching or rolling the
    photographed room to match one robot camera would make the floor and walls
    physically implausible for the other two cameras.
    """

    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    source_dir = profile_path.parent
    alignment_name = profile.get("alignment", {}).get("path", "alignment.json")
    base_alignment = json.loads(
        (source_dir / alignment_name).read_text(encoding="utf-8")
    )
    base_transform = np.asarray(
        base_alignment["gaussian_to_mujoco"],
        dtype=np.float64,
    )
    base_scale = float(
        np.mean(np.linalg.norm(base_transform[:3, :3], axis=0))
    )
    if not np.isfinite(base_scale) or base_scale <= 0.0:
        raise RuntimeError("invalid source-shell Sim(3) scale")
    base_rotation = normalized_rotation(base_transform[:3, :3])

    camera_payload = json.loads(
        (source_dir / "camera-path.json").read_text(encoding="utf-8")
    )
    source_cameras = np.asarray(
        camera_payload.get("camtoworlds")
        or [
            frame.get("transform_matrix") or frame.get("camtoworld")
            for frame in camera_payload["frames"]
        ],
        dtype=np.float64,
    )
    if source_cameras.ndim != 3 or source_cameras.shape[1:] != (4, 4):
        raise RuntimeError("invalid visual-shell camera path")
    if len(source_cameras) < 3:
        raise RuntimeError("visual-shell camera path is too short")

    required_cameras = {"head", "left_wrist", "right_wrist"}
    if set(target_cameras) != required_cameras:
        raise RuntimeError(
            "three-camera calibration requires exactly "
            f"{sorted(required_cameras)}"
        )
    conversion = np.diag([1.0, -1.0, -1.0])
    target_positions = {
        name: np.asarray(value["position"], dtype=np.float64)
        for name, value in target_cameras.items()
    }
    target_rotations_cv = {
        name: normalized_rotation(value["rotation_mujoco"]) @ conversion
        for name, value in target_cameras.items()
    }
    if not all(
        np.isfinite(value).all()
        for value in [
            *target_positions.values(),
            *target_rotations_cv.values(),
            source_cameras,
            base_transform,
        ]
    ):
        raise RuntimeError("camera calibration contains non-finite values")

    base_path_positions = (
        source_cameras[:, :3, 3] @ base_transform[:3, :3].T
        + base_transform[:3, 3]
    )
    base_path_rotations = np.einsum(
        "ij,njk->nik",
        base_rotation,
        source_cameras[:, :3, :3],
    )
    target_forward = np.mean(
        [rotation[:, 2] for rotation in target_rotations_cv.values()],
        axis=0,
    )
    target_forward[2] = 0.0
    if np.linalg.norm(target_forward) < 1e-8:
        raise RuntimeError("target cameras have no horizontal forward direction")
    target_forward /= np.linalg.norm(target_forward)
    target_yaw = float(np.arctan2(target_forward[1], target_forward[0]))
    target_position_array = np.asarray(list(target_positions.values()))
    target_xy = np.mean(target_position_array[:, :2], axis=0)
    target_mid_height = float(
        (
            np.min(target_position_array[:, 2])
            + np.max(target_position_array[:, 2])
        )
        / 2.0
    )

    room = profile.get("room_obb", {})
    floor_z = float(room.get("floor_z_m", 0.0))
    ceiling_z = float(room.get("ceiling_z_m", floor_z + 3.0))
    base_room_height = ceiling_z - floor_z
    if base_room_height <= 0.0:
        raise RuntimeError("invalid source-shell room height")

    candidates: list[dict[str, object]] = []
    # The generated path runs forward and then returns.  Searching only its
    # first leg avoids selecting the duplicated reverse frame as the anchor.
    candidate_count = (len(source_cameras) + 1) // 2
    for source_index in range(candidate_count):
        source_forward = base_path_rotations[source_index, :, 2].copy()
        source_forward[2] = 0.0
        if np.linalg.norm(source_forward) < 1e-8:
            continue
        source_forward /= np.linalg.norm(source_forward)
        source_yaw = float(
            np.arctan2(source_forward[1], source_forward[0])
        )
        yaw = target_yaw - source_yaw
        cosine = float(np.cos(yaw))
        sine = float(np.sin(yaw))
        yaw_rotation = np.asarray(
            [
                [cosine, -sine, 0.0],
                [sine, cosine, 0.0],
                [0.0, 0.0, 1.0],
            ],
            dtype=np.float64,
        )
        source_height = float(
            base_path_positions[source_index, 2] - floor_z
        )
        if source_height <= 1e-8:
            continue
        relative_scale = target_mid_height / source_height
        room_height = base_room_height * relative_scale
        if not (
            ALIGNMENT_THRESHOLDS["relative_scale_min"]
            <= relative_scale
            <= ALIGNMENT_THRESHOLDS["relative_scale_max"]
            and ALIGNMENT_THRESHOLDS["room_height_m_min"]
            <= room_height
            <= ALIGNMENT_THRESHOLDS["room_height_m_max"]
        ):
            continue

        post_transform = np.eye(4, dtype=np.float64)
        post_transform[:3, :3] = relative_scale * yaw_rotation
        anchor_xy = (
            relative_scale
            * yaw_rotation
            @ base_path_positions[source_index]
        )[:2]
        post_transform[:2, 3] = target_xy - anchor_xy
        post_transform[2, 3] = -relative_scale * floor_z
        transform = post_transform @ base_transform
        transform_rotation = normalized_rotation(transform[:3, :3])
        path_positions = (
            source_cameras[:, :3, 3] @ transform[:3, :3].T
            + transform[:3, 3]
        )
        path_rotations = np.einsum(
            "ij,njk->nik",
            transform_rotation,
            source_cameras[:, :3, :3],
        )

        nearest: dict[str, dict[str, object]] = {}
        distances: list[float] = []
        rotations: list[float] = []
        for name in sorted(required_cameras):
            distance_to_path = np.linalg.norm(
                path_positions - target_positions[name],
                axis=1,
            )
            rotation_to_path = rotation_errors_degrees(
                target_rotations_cv[name],
                path_rotations,
            )
            within_translation_gate = np.flatnonzero(
                distance_to_path
                <= ALIGNMENT_THRESHOLDS["capture_path_translation_m_max"]
            )
            if len(within_translation_gate):
                # 3DGS novel-view quality degrades much faster with unsupported
                # orientation than with a modest translation offset.  Select the
                # best-oriented captured view that is still spatially valid.
                order = np.lexsort(
                    (
                        distance_to_path[within_translation_gate],
                        rotation_to_path[within_translation_gate],
                    )
                )
                nearest_index = int(within_translation_gate[order[0]])
            else:
                nearest_index = int(np.argmin(distance_to_path))
            distance = float(distance_to_path[nearest_index])
            rotation_error = float(rotation_to_path[nearest_index])
            distances.append(distance)
            rotations.append(rotation_error)
            nearest[name] = {
                "path_index": nearest_index,
                "translation_m": distance,
                "rotation_degrees": rotation_error,
            }
        score = (
            max(rotations),
            float(np.mean(rotations)),
            max(distances),
            float(np.mean(distances)),
        )
        candidates.append(
            {
                "score": score,
                "source_index": source_index,
                "relative_scale": relative_scale,
                "room_height_m": room_height,
                "yaw_degrees": float(np.degrees(yaw)),
                "post_transform": post_transform,
                "transform": transform,
                "path_positions": path_positions,
                "nearest": nearest,
                "maximum_translation": max(distances),
                "maximum_rotation": max(rotations),
            }
        )
    if not candidates:
        raise RuntimeError(
            "no upright three-camera alignment satisfies scale and room bounds"
        )

    if preferred_source_index is not None:
        preferred = [
            candidate
            for candidate in candidates
            if int(candidate["source_index"]) == preferred_source_index
        ]
        if not preferred:
            raise RuntimeError(
                "preferred source camera does not satisfy upright scale and "
                f"room bounds: {preferred_source_index}"
            )
        selected = preferred[0]
    else:
        # Prefer a candidate that already satisfies both camera-coverage
        # thresholds.  Sorting every candidate by translation first can pick a
        # marginally closer view whose rotation fails even when another view
        # passes both gates.
        passing_candidates = [
            candidate
            for candidate in candidates
            if candidate["maximum_translation"]
            <= ALIGNMENT_THRESHOLDS["capture_path_translation_m_max"]
            and candidate["maximum_rotation"]
            <= ALIGNMENT_THRESHOLDS["capture_path_rotation_degrees_max"]
        ]
        selected = min(
            passing_candidates or candidates,
            key=lambda candidate: candidate["score"],
        )
    transform = np.asarray(selected["transform"], dtype=np.float64)
    post_transform = np.asarray(
        selected["post_transform"],
        dtype=np.float64,
    )
    path_positions = np.asarray(
        selected["path_positions"],
        dtype=np.float64,
    )
    nearest = selected["nearest"]
    post_rotation = normalized_rotation(post_transform[:3, :3])
    floor_normal = post_rotation @ np.asarray([0.0, 0.0, 1.0])
    floor_tilt = float(
        np.degrees(
            np.arccos(np.clip(floor_normal[2], -1.0, 1.0))
        )
    )
    maximum_translation = max(
        float(item["translation_m"]) for item in nearest.values()
    )
    maximum_rotation = max(
        float(item["rotation_degrees"]) for item in nearest.values()
    )
    checks = {
        "floor_normal_upright": (
            floor_tilt
            <= ALIGNMENT_THRESHOLDS["floor_normal_tilt_degrees_max"]
        ),
        "all_cameras_near_capture_path": (
            maximum_translation
            <= ALIGNMENT_THRESHOLDS["capture_path_translation_m_max"]
        ),
        "all_cameras_within_rotation_coverage": (
            maximum_rotation
            <= ALIGNMENT_THRESHOLDS[
                "capture_path_rotation_degrees_max"
            ]
        ),
        "relative_scale_valid": (
            ALIGNMENT_THRESHOLDS["relative_scale_min"]
            <= float(selected["relative_scale"])
            <= ALIGNMENT_THRESHOLDS["relative_scale_max"]
        ),
        "room_height_valid": (
            ALIGNMENT_THRESHOLDS["room_height_m_min"]
            <= float(selected["room_height_m"])
            <= ALIGNMENT_THRESHOLDS["room_height_m_max"]
        ),
    }
    alignment_quality = {
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "thresholds": ALIGNMENT_THRESHOLDS,
        "floor_normal_mujoco": floor_normal.tolist(),
        "floor_normal_tilt_degrees": floor_tilt,
        "maximum_capture_path_translation_m": maximum_translation,
        "maximum_capture_path_rotation_degrees": maximum_rotation,
        "per_camera_capture_path": nearest,
    }
    if alignment_quality["status"] != "passed":
        raise RuntimeError(
            "three-camera alignment quality gate failed: "
            + json.dumps(alignment_quality, ensure_ascii=False)
        )

    final_scale = float(
        np.mean(np.linalg.norm(transform[:3, :3], axis=0))
    )
    integration_calibration = {
        "method": (
            "upright Sim(3) fitted jointly to initial BiGym head and both "
            "wrist cameras"
        ),
        "target_cameras": sorted(required_cameras),
        "source_camera_index": int(selected["source_index"]),
        "source_camera_selection": (
            "user-preserved visual anchor"
            if preferred_source_index is not None
            else "automatic three-camera score"
        ),
        "post_yaw_degrees": float(selected["yaw_degrees"]),
        "relative_scale": float(selected["relative_scale"]),
        "base_scale": base_scale,
        "final_scale": final_scale,
        "source_floor_z_m": floor_z,
        "target_floor_z_m": 0.0,
        "target_camera_mid_height_m": target_mid_height,
        "source_support_selection": (
            "minimum rotation among captured views within the translation gate"
        ),
        "post_transform": post_transform.tolist(),
        "target_camera_poses": {
            name: {
                "position_m": target_positions[name].tolist(),
                "rotation_mujoco": np.asarray(
                    target_cameras[name]["rotation_mujoco"],
                    dtype=np.float64,
                ).tolist(),
            }
            for name in sorted(required_cameras)
        },
    }
    calibrated_alignment = {
        **base_alignment,
        "gaussian_to_mujoco": transform.tolist(),
        "mujoco_to_gaussian": np.linalg.inv(transform).tolist(),
        "integration_calibration": integration_calibration,
        "alignment_quality": alignment_quality,
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    alignment_path = output_dir / "alignment.json"
    alignment_path.write_text(
        json.dumps(calibrated_alignment, indent=2) + "\n",
        encoding="utf-8",
    )
    for filename in set(profile["layer_files"].values()):
        target = output_dir / filename
        if target.exists() or target.is_symlink():
            target.unlink()
        os.symlink(source_dir / filename, target)
    camera_target = output_dir / "camera-path.json"
    if camera_target.exists() or camera_target.is_symlink():
        camera_target.unlink()
    os.symlink(source_dir / "camera-path.json", camera_target)
    profile["alignment"] = {
        "path": alignment_path.name,
        "integration_calibration": integration_calibration,
        "quality": alignment_quality,
    }
    profile["camera_integration"] = integration_calibration
    profile["alignment_quality"] = alignment_quality
    profile["camera_envelope_m"] = {
        "min": path_positions.min(axis=0).tolist(),
        "max": path_positions.max(axis=0).tolist(),
        "center": np.median(path_positions, axis=0).tolist(),
        "source": "camera-path.json after BiGym three-camera Sim(3)",
    }
    if {"min_m", "max_m"} <= set(room):
        room_minimum, room_maximum = transform_bounds(
            np.asarray(room["min_m"], dtype=np.float64),
            np.asarray(room["max_m"], dtype=np.float64),
            post_transform,
        )
        profile["room_obb"] = {
            **room,
            "min_m": room_minimum.tolist(),
            "max_m": room_maximum.tolist(),
            "floor_z_m": 0.0,
            "ceiling_z_m": float(selected["room_height_m"]),
        }
    profile["status"] = "technical_pass_awaiting_visual_approval"
    calibrated_profile = output_dir / "scene-shell-profile.json"
    calibrated_profile.write_text(
        json.dumps(profile, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return calibrated_profile


def main() -> None:
    args = parse_args()
    if args.frames < 300:
        raise SystemExit("formal acceptance requires at least 300 frames")
    if args.bigym_dir is None:
        raise SystemExit("set BIGYM_DIR or pass --bigym-dir")
    replay_dir = args.bigym_dir.expanduser().resolve() / "d" / "replay_generation"
    if not (replay_dir / "env_utils.py").is_file():
        raise SystemExit(f"patched BiGym replay helpers not found: {replay_dir}")
    sys.path.insert(0, str(replay_dir))
    from env_utils import CAMERAS, build_env, get_state  # noqa: PLC0415

    args.output.mkdir(parents=True, exist_ok=True)
    actions: list[np.ndarray] = []
    native_hashes: dict[int, dict[str, str]] = {}
    native_qpos_frames: list[np.ndarray] = []
    native_time_frames: list[float] = []
    native_contacts: list[int] = []
    native_terminations: list[bool] = []
    native_termination_diagnostic: dict[str, object] | None = None
    native_action_dim = 0
    initial_camera_poses: dict[str, dict[str, np.ndarray]] = {}
    native = build_env(args.task)
    try:
        observation, _ = native.reset(seed=args.seed)
        for name, _feature, _resolution, _fovy, *_pose in CAMERAS:
            camera_id = native._cameras_map[name][0]
            initial_camera_poses[name] = {
                "position": np.asarray(
                    native._mojo.data.cam_xpos[camera_id],
                    dtype=np.float64,
                ).copy(),
                "rotation_mujoco": np.asarray(
                    native._mojo.data.cam_xmat[camera_id],
                    dtype=np.float64,
                ).reshape(3, 3).copy(),
            }
        for frame_index in range(args.frames):
            action = get_state(
                native.robot,
                observation,
                native.action_mode._mojo,
            )
            # JointPositionActionMode uses absolute targets for the arms but always
            # interprets floating-base controls as deltas.  Replaying the measured
            # base qpos would therefore integrate a large displacement every step.
            # A stable hold command must use zero base delta while retaining the
            # measured absolute arm and gripper targets.
            base_dofs = native.robot.floating_base.dof_amount
            action[:base_dofs] = 0.0
            action = np.clip(
                action,
                native.action_space.low,
                native.action_space.high,
            ).astype(np.float32)
            native_action_dim = int(action.size)
            actions.append(action)
            if frame_index in {0, args.frames // 2, args.frames - 1}:
                native_hashes[frame_index] = {
                    name: digest(observation[f"rgb_{name}"])
                    for name, *_ in CAMERAS
                }
            observation, _, terminated, truncated, _ = native.step(action)
            qpos = np.asarray(native.action_mode._mojo.data.qpos).copy()
            if not np.isfinite(qpos).all():
                raise RuntimeError(
                    f"native state became non-finite at frame {frame_index}"
                )
            if truncated:
                raise RuntimeError(
                    "native simulation became unhealthy at "
                    f"frame {frame_index}; resets are forbidden"
                )
            native_terminations.append(bool(terminated))
            if terminated and native_termination_diagnostic is None:
                native_termination_diagnostic = {
                    "first_frame": frame_index,
                    **termination_diagnostics(native),
                }
                if native_termination_diagnostic["robot_distance_failure"]:
                    raise RuntimeError(
                        "native robot left the valid workspace at "
                        f"frame {frame_index}; continuing would hide a robot failure"
                    )
            native_qpos_frames.append(qpos)
            native_time_frames.append(
                float(native.action_mode._mojo.data.time)
            )
            native_contacts.append(int(native._mojo.data.ncon))
    finally:
        native.close()

    if set(initial_camera_poses) != {"head", "left_wrist", "right_wrist"}:
        raise RuntimeError("failed to capture the initial BiGym cameras")
    if args.profile_already_calibrated:
        calibrated_profile = validate_precalibrated_profile(
            args.profile,
            initial_camera_poses,
        )
    else:
        calibrated_profile = calibrated_profile_for_three_cameras(
            args.profile,
            args.output / "calibrated-shell",
            initial_camera_poses,
            args.source_camera_index,
        )
    calibrated_payload = json.loads(
        calibrated_profile.read_text(encoding="utf-8")
    )
    calibration_quality = calibrated_payload["alignment_quality"]
    composed = build_env(
        args.task,
        visual_shell_profile=str(calibrated_profile),
        visual_shell_strict=True,
    )
    video_path = args.output / "bigym_kitchen_visual_shell_three_camera.mp4"
    preview_path = args.output / "bigym_kitchen_visual_shell_preview.png"
    container = av.open(str(video_path), "w")
    stream = container.add_stream("libx264", rate=20)
    stream.width = 1280
    stream.height = 960
    stream.pix_fmt = "yuv420p"
    stream.options = {"crf": "18", "preset": "medium"}
    composed_hashes: dict[int, dict[str, str]] = {}
    composed_qpos_frames: list[np.ndarray] = []
    composed_time_frames: list[float] = []
    composed_contacts: list[int] = []
    composed_terminations: list[bool] = []
    composed_termination_diagnostic: dict[str, object] | None = None
    render_times_ms: list[float] = []
    started = time.perf_counter()
    last_mosaic: np.ndarray | None = None
    try:
        observation, _ = composed.reset(seed=args.seed)
        for frame_index, action in enumerate(actions):
            frame_started = time.perf_counter()
            for name, _feature, resolution, fovy, *_pose in CAMERAS:
                frame = observation[f"rgb_{name}"]
                if frame.shape != (3, *resolution) or frame.dtype != np.uint8:
                    raise RuntimeError(
                        f"{name} has invalid observation "
                        f"{frame.shape} {frame.dtype}"
                    )
                if not np.isfinite(frame).all():
                    raise RuntimeError(f"{name} contains non-finite pixels")
                camera_id = composed._cameras_map[name][0]
                actual_fovy = float(composed._mojo.model.cam_fovy[camera_id])
                if abs(actual_fovy - fovy) > 1e-6:
                    raise RuntimeError(f"{name} FOV changed")
            if frame_index in {0, args.frames // 2, args.frames - 1}:
                composed_hashes[frame_index] = {
                    name: digest(observation[f"rgb_{name}"])
                    for name, *_ in CAMERAS
                }
            last_mosaic = mosaic(observation)
            packet = av.VideoFrame.from_ndarray(last_mosaic, format="rgb24")
            for encoded in stream.encode(packet):
                container.mux(encoded)
            observation, _, terminated, truncated, _ = composed.step(action)
            composed_contacts.append(int(composed._mojo.data.ncon))
            render_times_ms.append(
                (time.perf_counter() - frame_started) * 1000.0
            )
            qpos = np.asarray(composed.action_mode._mojo.data.qpos).copy()
            if not np.isfinite(qpos).all():
                raise RuntimeError(
                    "composed state became non-finite at "
                    f"frame {frame_index}"
                )
            if truncated:
                raise RuntimeError(
                    "composed simulation became unhealthy at "
                    f"frame {frame_index}; resets are forbidden"
                )
            composed_terminations.append(bool(terminated))
            if terminated and composed_termination_diagnostic is None:
                composed_termination_diagnostic = {
                    "first_frame": frame_index,
                    **termination_diagnostics(composed),
                }
                if composed_termination_diagnostic["robot_distance_failure"]:
                    raise RuntimeError(
                        "composed robot left the valid workspace at "
                        f"frame {frame_index}; continuing would hide a robot failure"
                    )
            composed_qpos_frames.append(qpos)
            composed_time_frames.append(
                float(composed.action_mode._mojo.data.time)
            )
        for encoded in stream.encode():
            container.mux(encoded)
        container.close()
        container = None
        if last_mosaic is None:
            raise RuntimeError("no composed frames were produced")
        Image.fromarray(last_mosaic, "RGB").save(preview_path)
        shell_status = composed._visual_shell.status()
    finally:
        if container is not None:
            container.close()
        composed.close()

    changed = {
        name: all(
            native_hashes[index][name] != composed_hashes[index][name]
            for index in native_hashes
        )
        for name, *_ in CAMERAS
    }
    parity_error = float(
        np.max(
            np.abs(
                np.asarray(native_qpos_frames)
                - np.asarray(composed_qpos_frames)
            )
        )
    )
    time_error = max(
        abs(native_time - composed_time)
        for native_time, composed_time in zip(
            native_time_frames, composed_time_frames, strict=True
        )
    )
    contact_error = max(
        abs(native_contact - composed_contact)
        for native_contact, composed_contact in zip(
            native_contacts, composed_contacts, strict=True
        )
    )
    termination_parity = native_terminations == composed_terminations
    if (
        parity_error > 1e-9
        or time_error > 1e-12
        or contact_error != 0
        or not termination_parity
    ):
        raise RuntimeError(
            "visual background changed physics: "
            f"qpos error={parity_error}, time error={time_error}, "
            f"contact error={contact_error}, "
            f"termination parity={termination_parity}"
        )
    if not all(changed.values()):
        raise RuntimeError(f"background did not change every camera: {changed}")
    elapsed = time.perf_counter() - started
    report = {
        "schema_version": 1,
        "status": "awaiting_visual_approval",
        "technical_status": "passed",
        "visual_approval": "pending_user_confirmation",
        "task": args.task,
        "seed": args.seed,
        "frames": args.frames,
        "continuous_episode": True,
        "continuous_simulation_without_reset": True,
        "resets_during_acceptance": 0,
        "accumulated_simulation_seconds": args.frames / 20.0,
        "simulation_hz": 20,
        "action_dimension": native_action_dim,
        "state_dimension": native_action_dim,
        "acceptance_control": {
            "floating_base": "zero delta",
            "arms_and_grippers": "hold measured absolute position",
        },
        "wall_seconds": elapsed,
        "wall_steps_per_second": args.frames / elapsed,
        "camera_frames_per_second": 3.0 * args.frames / elapsed,
        "render_ms": {
            "median": float(np.median(render_times_ms)),
            "p95": float(np.percentile(render_times_ms, 95)),
        },
        "cameras": {
            name: {
                "feature_key": feature,
                "resolution": list(resolution),
                "fovy": fovy,
                "changed_from_native": changed[name],
            }
            for name, feature, resolution, fovy, *_pose in CAMERAS
        },
        "physics_parity": {
            "max_abs_qpos_error": parity_error,
            "max_abs_time_error": time_error,
            "max_abs_contact_count_error": contact_error,
            "final_time_native": native_time_frames[-1],
            "final_time_composed": composed_time_frames[-1],
            "contacts_min": min(composed_contacts),
            "contacts_max": max(composed_contacts),
            "termination_flags_equal": termination_parity,
            "native_termination_count": sum(native_terminations),
            "composed_termination_count": sum(composed_terminations),
        },
        "task_termination": {
            "observed": any(native_terminations),
            "native": native_termination_diagnostic,
            "composed": composed_termination_diagnostic,
            "interpretation": (
                "The native DishwasherLoadPlates prop reaches its task-failure "
                "condition when a loose plate contacts the floor. The same "
                "condition occurs on the same frame with and without the visual "
                "shell. Simulation continues in the same environment instance "
                "without reset; robot workspace and simulator health remain valid."
                if any(native_terminations)
                else "No Gym task termination was observed."
            ),
        },
        "visual_shell": shell_status,
        "camera_calibration": {
            "profile": str(calibrated_profile),
            "reused_existing_calibration": bool(
                args.profile_already_calibrated
            ),
            **calibrated_payload["camera_integration"],
            "quality": calibration_quality,
        },
        "video": {
            "path": str(video_path),
            "frames": args.frames,
            "width": 1280,
            "height": 960,
            "fps": 20,
            "codec": "H.264",
            "pixel_format": "yuv420p",
        },
        "preview": str(preview_path),
    }
    report_path = args.output / "bigym-visual-shell-report.json"
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
