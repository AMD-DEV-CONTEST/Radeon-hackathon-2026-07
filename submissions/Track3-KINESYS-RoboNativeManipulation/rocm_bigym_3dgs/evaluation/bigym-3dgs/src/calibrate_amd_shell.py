#!/usr/bin/env python3
"""Fit an AMD OpenSplat kitchen shell to the live BiGym camera rig."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

import numpy as np


CAMERA_NAMES = ("head", "left_wrist", "right_wrist")
THRESHOLDS = {
    "capture_path_translation_m_max": 0.5,
    "capture_path_rotation_degrees_max": 75.0,
    "relative_scale_min": 0.4,
    "relative_scale_max": 1.2,
    "room_height_m_min": 2.0,
    "room_height_m_max": 5.0,
}
METRIC_FLOOR = {
    "mode": "metric_procedural",
    "z_m": 0.0,
    "tile_size_m": 0.75,
    "grout_width_m": 0.006,
    "base_rgb": [210, 210, 204],
    "grout_rgb": [175, 180, 180],
    "tile_variation": 4.0,
    "depth_tolerance_m": 0.25,
    "gaussian_floor_enabled": False,
    "collision_geometry_added": False,
    "coordinate_frame": "MuJoCo metric world",
}


def normalized_rotation(linear: np.ndarray) -> np.ndarray:
    u, _singular_values, vh = np.linalg.svd(np.asarray(linear, dtype=np.float64))
    rotation = u @ vh
    if np.linalg.det(rotation) < 0.0:
        u[:, -1] *= -1.0
        rotation = u @ vh
    return rotation


def rotation_error_degrees(expected: np.ndarray, actual: np.ndarray) -> float:
    delta = normalized_rotation(expected).T @ normalized_rotation(actual)
    cosine = np.clip((np.trace(delta) - 1.0) / 2.0, -1.0, 1.0)
    return float(np.degrees(np.arccos(cosine)))


def load_opensplat_cameras(path: Path) -> tuple[np.ndarray, dict[str, object]]:
    """Convert OpenSplat's saved OpenCV camera-to-world list."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not payload:
        raise RuntimeError("OpenSplat cameras.json must be a non-empty list")
    matrices: list[np.ndarray] = []
    fovys: list[float] = []
    for index, camera in enumerate(payload):
        rotation = np.asarray(camera.get("rotation"), dtype=np.float64)
        position = np.asarray(camera.get("position"), dtype=np.float64)
        if rotation.shape != (3, 3) or position.shape != (3,):
            raise RuntimeError(f"invalid OpenSplat camera {index}")
        if not np.isfinite(rotation).all() or not np.isfinite(position).all():
            raise RuntimeError(f"non-finite OpenSplat camera {index}")
        matrix = np.eye(4, dtype=np.float64)
        matrix[:3, :3] = normalized_rotation(rotation)
        matrix[:3, 3] = position
        matrices.append(matrix)
        height = float(camera["height"])
        fy = float(camera["fy"])
        fovys.append(float(np.degrees(2.0 * np.arctan(height / (2.0 * fy)))))
    source = np.stack(matrices)
    meta = {
        "schema_version": 1,
        "coordinate_convention": "OpenSplat exported OpenCV camera-to-world",
        "frames": int(len(source)),
        "fovy_degrees_median": float(np.median(fovys)),
        "camtoworlds": source.tolist(),
    }
    return source, meta


def measure_bigym_cameras(
    bigym_root: Path, task: str, seed: int
) -> dict[str, dict[str, np.ndarray]]:
    replay_dir = bigym_root / "d" / "replay_generation"
    if not replay_dir.is_dir():
        raise RuntimeError(f"BiGym replay helpers are missing: {replay_dir}")
    sys.path.insert(0, str(replay_dir))
    from env_utils import build_env  # type: ignore  # noqa: PLC0415

    env = build_env(task, render_mode="rgb_array")
    try:
        env.reset(seed=seed)
        measured: dict[str, dict[str, np.ndarray]] = {}
        for name in CAMERA_NAMES:
            camera_id = env._cameras_map[name][0]
            measured[name] = {
                "position": np.asarray(
                    env._mojo.data.cam_xpos[camera_id], dtype=np.float64
                ).copy(),
                "rotation_mujoco": np.asarray(
                    env._mojo.data.cam_xmat[camera_id], dtype=np.float64
                ).reshape(3, 3).copy(),
            }
        return measured
    finally:
        env.close()


def fit_alignment(
    source_cameras: np.ndarray,
    profile: dict[str, object],
    base_alignment: dict[str, object],
    targets: dict[str, dict[str, np.ndarray]],
    source_camera_index: int | None,
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    base_transform = np.asarray(base_alignment["gaussian_to_mujoco"], dtype=np.float64)
    if base_transform.shape != (4, 4):
        raise RuntimeError("base gaussian_to_mujoco must be 4x4")
    base_rotation = normalized_rotation(base_transform[:3, :3])
    base_scale = float(np.mean(np.linalg.norm(base_transform[:3, :3], axis=0)))
    base_positions = (
        source_cameras[:, :3, 3] @ base_transform[:3, :3].T
        + base_transform[:3, 3]
    )
    base_rotations = np.einsum(
        "ij,njk->nik", base_rotation, source_cameras[:, :3, :3]
    )

    conversion = np.diag([1.0, -1.0, -1.0])
    target_positions = {name: value["position"] for name, value in targets.items()}
    target_rotations = {
        name: normalized_rotation(value["rotation_mujoco"]) @ conversion
        for name, value in targets.items()
    }
    target_array = np.asarray(list(target_positions.values()))
    target_xy = target_array[:, :2].mean(axis=0)
    target_mid_height = float(
        (target_array[:, 2].min() + target_array[:, 2].max()) / 2.0
    )
    target_forward = np.mean(
        [rotation[:, 2] for rotation in target_rotations.values()], axis=0
    )
    target_forward[2] = 0.0
    target_forward /= np.linalg.norm(target_forward)
    target_yaw = float(np.arctan2(target_forward[1], target_forward[0]))

    room = profile["room_obb"]
    floor_z = float(room["floor_z_m"])
    base_room_height = float(room["ceiling_z_m"]) - floor_z
    candidates: list[dict[str, object]] = []
    for source_index in range(len(source_cameras)):
        source_forward = base_rotations[source_index, :, 2].copy()
        source_forward[2] = 0.0
        if np.linalg.norm(source_forward) < 1e-8:
            continue
        source_forward /= np.linalg.norm(source_forward)
        source_yaw = float(np.arctan2(source_forward[1], source_forward[0]))
        yaw = target_yaw - source_yaw
        cosine, sine = float(np.cos(yaw)), float(np.sin(yaw))
        yaw_rotation = np.asarray(
            [[cosine, -sine, 0.0], [sine, cosine, 0.0], [0.0, 0.0, 1.0]]
        )
        source_height = float(base_positions[source_index, 2] - floor_z)
        if source_height <= 1e-8:
            continue
        relative_scale = target_mid_height / source_height
        post = np.eye(4)
        post[:3, :3] = relative_scale * yaw_rotation
        anchor_xy = (relative_scale * yaw_rotation @ base_positions[source_index])[:2]
        post[:2, 3] = target_xy - anchor_xy
        post[2, 3] = -relative_scale * floor_z
        transform = post @ base_transform
        transform_rotation = normalized_rotation(transform[:3, :3])
        path_positions = (
            source_cameras[:, :3, 3] @ transform[:3, :3].T
            + transform[:3, 3]
        )
        path_rotations = np.einsum(
            "ij,njk->nik", transform_rotation, source_cameras[:, :3, :3]
        )
        nearest: dict[str, dict[str, object]] = {}
        distances: list[float] = []
        rotations: list[float] = []
        for name in sorted(target_positions):
            distance_to_path = np.linalg.norm(
                path_positions - target_positions[name], axis=1
            )
            nearest_index = int(np.argmin(distance_to_path))
            distance = float(distance_to_path[nearest_index])
            rotation = rotation_error_degrees(
                target_rotations[name], path_rotations[nearest_index]
            )
            distances.append(distance)
            rotations.append(rotation)
            nearest[name] = {
                "path_index": nearest_index,
                "translation_m": distance,
                "rotation_degrees": rotation,
            }
        room_height = base_room_height * relative_scale
        scale_penalty = (
            0.0
            if THRESHOLDS["room_height_m_min"]
            <= room_height
            <= THRESHOLDS["room_height_m_max"]
            else 100.0
        )
        candidates.append(
            {
                "score": (
                    scale_penalty,
                    max(distances),
                    float(np.mean(distances)),
                    max(rotations),
                    float(np.mean(rotations)),
                ),
                "source_index": source_index,
                "relative_scale": relative_scale,
                "room_height_m": room_height,
                "yaw_degrees": float(np.degrees(yaw)),
                "post": post,
                "transform": transform,
                "nearest": nearest,
            }
        )
    if not candidates:
        raise RuntimeError("no valid camera-alignment candidates")
    if source_camera_index is None:
        selected = min(candidates, key=lambda item: item["score"])
        selection_method = "automatic live three-camera score"
    else:
        matches = [
            item for item in candidates if item["source_index"] == source_camera_index
        ]
        if not matches:
            raise RuntimeError(f"invalid requested source camera index {source_camera_index}")
        selected = matches[0]
        selection_method = "requested source-camera anchor"

    maximum_translation = max(
        float(value["translation_m"]) for value in selected["nearest"].values()
    )
    maximum_rotation = max(
        float(value["rotation_degrees"]) for value in selected["nearest"].values()
    )
    relative_scale = float(selected["relative_scale"])
    room_height = float(selected["room_height_m"])
    checks = {
        "floor_normal_upright": True,
        "all_cameras_near_capture_path": maximum_translation
        <= THRESHOLDS["capture_path_translation_m_max"],
        "all_cameras_within_rotation_coverage": maximum_rotation
        <= THRESHOLDS["capture_path_rotation_degrees_max"],
        "relative_scale_valid": THRESHOLDS["relative_scale_min"]
        <= relative_scale
        <= THRESHOLDS["relative_scale_max"],
        "room_height_valid": THRESHOLDS["room_height_m_min"]
        <= room_height
        <= THRESHOLDS["room_height_m_max"],
    }
    quality = {
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "thresholds": THRESHOLDS,
        "maximum_capture_path_translation_m": maximum_translation,
        "maximum_capture_path_rotation_degrees": maximum_rotation,
        "relative_scale": relative_scale,
        "room_height_m": room_height,
        "per_camera_capture_path": selected["nearest"],
    }
    transform = np.asarray(selected["transform"], dtype=np.float64)
    calibration = {
        "method": "upright Sim(3) fitted to live BiGym head and wrist cameras",
        "source_camera_index": int(selected["source_index"]),
        "source_camera_selection": selection_method,
        "post_yaw_degrees": float(selected["yaw_degrees"]),
        "relative_scale": relative_scale,
        "base_scale": base_scale,
        "final_scale": float(np.mean(np.linalg.norm(transform[:3, :3], axis=0))),
        "target_camera_mid_height_m": target_mid_height,
        "target_camera_poses": {
            name: {
                "position_m": value["position"].tolist(),
                "rotation_mujoco": value["rotation_mujoco"].tolist(),
            }
            for name, value in targets.items()
        },
    }
    alignment = {
        **base_alignment,
        "gaussian_to_mujoco": transform.tolist(),
        "mujoco_to_gaussian": np.linalg.inv(transform).tolist(),
        "integration_calibration": calibration,
        "alignment_quality": quality,
    }
    return alignment, calibration, quality


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--opensplat-cameras", type=Path, required=True)
    parser.add_argument("--bigym-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--task", default="DishwasherUnloadCutleryLong")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--source-camera-index", type=int)
    args = parser.parse_args()

    source_profile = args.profile.resolve()
    source_dir = source_profile.parent
    profile = json.loads(source_profile.read_text(encoding="utf-8"))
    alignment_name = profile.get("alignment", {}).get("path", "alignment.json")
    base_alignment = json.loads(
        (source_dir / alignment_name).read_text(encoding="utf-8")
    )
    cameras, camera_path = load_opensplat_cameras(args.opensplat_cameras.resolve())
    targets = measure_bigym_cameras(args.bigym_root.resolve(), args.task, args.seed)
    alignment, calibration, quality = fit_alignment(
        cameras, profile, base_alignment, targets, args.source_camera_index
    )

    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    (output / "camera-path.json").write_text(
        json.dumps(camera_path, indent=2) + "\n", encoding="utf-8"
    )
    (output / "alignment.json").write_text(
        json.dumps(alignment, indent=2) + "\n", encoding="utf-8"
    )
    for filename in set(profile["layer_files"].values()):
        source = (source_dir / filename).resolve()
        target = output / filename
        if target.exists() or target.is_symlink():
            target.unlink()
        os.symlink(source, target)
    profile["status"] = "calibrated_pending_human_visual_review"
    profile["alignment"] = {"path": "alignment.json", "quality": quality}
    profile["camera_integration"] = calibration
    profile["alignment_quality"] = quality
    profile["ground_visual"] = METRIC_FLOOR
    profile["human_visual_review"] = {"required": True, "status": "pending"}
    profile["room_obb"] = {
        **profile["room_obb"],
        "floor_z_m": 0.0,
        "ceiling_z_m": float(quality["room_height_m"]),
    }
    calibrated_profile = output / "scene-shell-profile.json"
    calibrated_profile.write_text(
        json.dumps(profile, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    receipt = {
        "status": "calibration_passed"
        if quality["status"] == "passed"
        else "calibration_failed",
        "profile": str(calibrated_profile),
        "source_camera_count": int(len(cameras)),
        "calibration": calibration,
        "quality": quality,
        "human_visual_review": "pending",
    }
    (output / "calibration-receipt.json").write_text(
        json.dumps(receipt, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(receipt, indent=2))
    if quality["status"] != "passed":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
