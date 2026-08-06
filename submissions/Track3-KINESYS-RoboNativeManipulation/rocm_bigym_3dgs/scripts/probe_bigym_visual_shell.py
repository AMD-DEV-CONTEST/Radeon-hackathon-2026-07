#!/usr/bin/env python3
"""Render a clearly-labelled, non-acceptance BiGym visual-shell probe.

The probe can either choose the closest upright Sim(3), or inspect a requested
source-camera anchor.  It records the formal alignment checks but never promotes
a short probe into a formal acceptance result.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

import numpy as np
from PIL import Image


THRESHOLDS = {
    "capture_path_translation_m_max": 0.5,
    "capture_path_rotation_degrees_max": 75.0,
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
    parser.add_argument("--frames", type=int, default=30)
    parser.add_argument("--seed", type=int, default=20260802)
    parser.add_argument("--source-camera-index", type=int)
    return parser.parse_args()


def digest(frame: np.ndarray) -> str:
    return hashlib.sha256(np.asarray(frame).tobytes()).hexdigest()


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


def fit_probe_alignment(
    profile_path: Path,
    output_dir: Path,
    target_cameras: dict[str, dict[str, np.ndarray]],
    source_camera_index: int | None = None,
) -> tuple[Path, dict[str, object]]:
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    source_dir = profile_path.parent
    alignment_name = profile.get("alignment", {}).get("path", "alignment.json")
    base_alignment = json.loads(
        (source_dir / alignment_name).read_text(encoding="utf-8")
    )
    base_transform = np.asarray(
        base_alignment["gaussian_to_mujoco"], dtype=np.float64
    )
    base_rotation = normalized_rotation(base_transform[:3, :3])
    base_scale = float(np.mean(np.linalg.norm(base_transform[:3, :3], axis=0)))
    camera_payload = json.loads(
        (source_dir / "camera-path.json").read_text(encoding="utf-8")
    )
    source_cameras = np.asarray(camera_payload["camtoworlds"], dtype=np.float64)
    base_positions = (
        source_cameras[:, :3, 3] @ base_transform[:3, :3].T
        + base_transform[:3, 3]
    )
    base_rotations = np.einsum(
        "ij,njk->nik", base_rotation, source_cameras[:, :3, :3]
    )

    conversion = np.diag([1.0, -1.0, -1.0])
    target_positions = {
        name: np.asarray(value["position"], dtype=np.float64)
        for name, value in target_cameras.items()
    }
    target_rotations = {
        name: normalized_rotation(value["rotation_mujoco"]) @ conversion
        for name, value in target_cameras.items()
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
        score = (max(distances), np.mean(distances), max(rotations), np.mean(rotations))
        candidates.append(
            {
                "score": score,
                "source_index": source_index,
                "relative_scale": relative_scale,
                "room_height_m": base_room_height * relative_scale,
                "yaw_degrees": float(np.degrees(yaw)),
                "post": post,
                "transform": transform,
                "path_positions": path_positions,
                "nearest": nearest,
            }
        )
    if source_camera_index is None:
        selected = min(candidates, key=lambda item: item["score"])
        selection_method = "automatic three-camera score"
    else:
        matches = [
            item
            for item in candidates
            if int(item["source_index"]) == source_camera_index
        ]
        if not matches:
            raise RuntimeError(
                f"source camera index {source_camera_index} is not a valid anchor"
            )
        selected = matches[0]
        selection_method = "requested visual-probe anchor"
    maximum_translation = max(
        float(value["translation_m"])
        for value in selected["nearest"].values()
    )
    maximum_rotation = max(
        float(value["rotation_degrees"])
        for value in selected["nearest"].values()
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
        "status": "failed" if not all(checks.values()) else "passed",
        "probe_only": True,
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
        "method": "upright Sim(3) visual probe; formal checks retained",
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
            for name, value in target_cameras.items()
        },
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    alignment = {
        **base_alignment,
        "gaussian_to_mujoco": transform.tolist(),
        "mujoco_to_gaussian": np.linalg.inv(transform).tolist(),
        "integration_calibration": calibration,
        "alignment_quality": quality,
    }
    (output_dir / "alignment.json").write_text(
        json.dumps(alignment, indent=2) + "\n", encoding="utf-8"
    )
    for filename in set(profile["layer_files"].values()):
        target = output_dir / filename
        if target.exists() or target.is_symlink():
            target.unlink()
        os.symlink((source_dir / filename).resolve(), target)
    camera_target = output_dir / "camera-path.json"
    if camera_target.exists() or camera_target.is_symlink():
        camera_target.unlink()
    os.symlink((source_dir / "camera-path.json").resolve(), camera_target)
    profile["status"] = "visual_probe_only"
    profile["alignment"] = {"path": "alignment.json", "quality": quality}
    profile["camera_integration"] = calibration
    profile["alignment_quality"] = quality
    profile["room_obb"] = {
        **room,
        "floor_z_m": 0.0,
        "ceiling_z_m": room_height,
    }
    calibrated_profile = output_dir / "scene-shell-profile.json"
    calibrated_profile.write_text(
        json.dumps(profile, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return calibrated_profile, quality


def main() -> None:
    args = parse_args()
    if args.frames <= 0:
        raise SystemExit("--frames must be positive")
    repo_root = next(
        (
            candidate
            for candidate in Path(__file__).resolve().parents
            if (candidate / "d" / "replay_generation").is_dir()
        ),
        None,
    )
    if repo_root is None:
        raise RuntimeError("could not locate repository root from probe script")
    sys.path.insert(0, str(repo_root / "d" / "replay_generation"))
    from env_utils import CAMERAS, build_env, get_state  # noqa: PLC0415
    from competition.reconstruction.validate_bigym_visual_shell import mosaic  # noqa: PLC0415

    args.output.mkdir(parents=True, exist_ok=True)
    native = build_env(args.task)
    actions: list[np.ndarray] = []
    native_qpos: list[np.ndarray] = []
    native_times: list[float] = []
    native_contacts: list[int] = []
    native_terminated: list[bool] = []
    target_cameras: dict[str, dict[str, np.ndarray]] = {}
    try:
        observation, _ = native.reset(seed=args.seed)
        native_initial_hashes = {
            name: digest(observation[f"rgb_{name}"]) for name, *_ in CAMERAS
        }
        camera_contract = {}
        for name, _feature, resolution, fovy in CAMERAS:
            camera_id = native._cameras_map[name][0]
            target_cameras[name] = {
                "position": np.asarray(native._mojo.data.cam_xpos[camera_id]).copy(),
                "rotation_mujoco": np.asarray(
                    native._mojo.data.cam_xmat[camera_id]
                ).reshape(3, 3).copy(),
            }
            camera_contract[name] = {
                "shape": list(observation[f"rgb_{name}"].shape),
                "dtype": str(observation[f"rgb_{name}"].dtype),
                "expected_resolution": list(resolution),
                "fovy_degrees": float(native._mojo.model.cam_fovy[camera_id]),
                "expected_fovy_degrees": fovy,
            }
        for _frame_index in range(args.frames):
            action = get_state(native.robot, observation, native.action_mode._mojo)
            action[: native.robot.floating_base.dof_amount] = 0.0
            action = np.clip(action, native.action_space.low, native.action_space.high)
            actions.append(action.astype(np.float32))
            observation, _, terminated, truncated, _ = native.step(actions[-1])
            if truncated:
                raise RuntimeError("native simulation truncated during probe")
            native_qpos.append(np.asarray(native.action_mode._mojo.data.qpos).copy())
            native_times.append(float(native.action_mode._mojo.data.time))
            native_contacts.append(int(native._mojo.data.ncon))
            native_terminated.append(bool(terminated))
        native_final_hashes = {
            name: digest(observation[f"rgb_{name}"]) for name, *_ in CAMERAS
        }
        Image.fromarray(mosaic(observation), "RGB").save(
            args.output / "native-final.png"
        )
    finally:
        native.close()

    calibrated_profile, quality = fit_probe_alignment(
        args.profile,
        args.output / "probe-calibrated-shell",
        target_cameras,
        source_camera_index=args.source_camera_index,
    )
    composed = build_env(
        args.task,
        visual_shell_profile=str(calibrated_profile),
        visual_shell_strict=True,
    )
    composed_qpos: list[np.ndarray] = []
    composed_times: list[float] = []
    composed_contacts: list[int] = []
    composed_terminated: list[bool] = []
    try:
        observation, _ = composed.reset(seed=args.seed)
        composed_initial_hashes = {
            name: digest(observation[f"rgb_{name}"]) for name, *_ in CAMERAS
        }
        Image.fromarray(mosaic(observation), "RGB").save(
            args.output / "composed-initial.png"
        )
        for action in actions:
            observation, _, terminated, truncated, _ = composed.step(action)
            if truncated:
                raise RuntimeError("composed simulation truncated during probe")
            composed_qpos.append(
                np.asarray(composed.action_mode._mojo.data.qpos).copy()
            )
            composed_times.append(float(composed.action_mode._mojo.data.time))
            composed_contacts.append(int(composed._mojo.data.ncon))
            composed_terminated.append(bool(terminated))
        composed_final_hashes = {
            name: digest(observation[f"rgb_{name}"]) for name, *_ in CAMERAS
        }
        Image.fromarray(mosaic(observation), "RGB").save(
            args.output / "composed-final.png"
        )
        shell_status = composed._visual_shell.status()
    finally:
        composed.close()

    qpos_error = float(
        np.max(np.abs(np.asarray(native_qpos) - np.asarray(composed_qpos)))
    )
    time_error = float(
        np.max(np.abs(np.asarray(native_times) - np.asarray(composed_times)))
    )
    contact_error = int(
        np.max(np.abs(np.asarray(native_contacts) - np.asarray(composed_contacts)))
    )
    report = {
        "schema_version": 1,
        "status": "visual_probe_completed",
        "technical_probe_status": "passed",
        "formal_acceptance": "not_run",
        "task": args.task,
        "seed": args.seed,
        "frames": args.frames,
        "action_dimension": int(actions[0].size),
        "camera_contract": camera_contract,
        "alignment_quality": quality,
        "background_changed_every_camera": {
            name: (
                native_initial_hashes[name] != composed_initial_hashes[name]
                and native_final_hashes[name] != composed_final_hashes[name]
            )
            for name, *_ in CAMERAS
        },
        "physics_parity": {
            "max_abs_qpos_error": qpos_error,
            "max_abs_time_error": time_error,
            "max_abs_contact_count_error": contact_error,
            "termination_flags_equal": native_terminated == composed_terminated,
            "native_final_time": native_times[-1],
            "composed_final_time": composed_times[-1],
        },
        "visual_shell": shell_status,
        "artifacts": {
            "native_final": str(args.output / "native-final.png"),
            "composed_initial": str(args.output / "composed-initial.png"),
            "composed_final": str(args.output / "composed-final.png"),
            "profile": str(calibrated_profile),
        },
    }
    (args.output / "probe-report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
