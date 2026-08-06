#!/usr/bin/env python3
"""Export a gsplat checkpoint as a standard DISCOVERSE background PLY."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import numpy as np
import torch
from PIL import Image
from scipy.spatial.transform import Rotation, Slerp


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--gsplat", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--metrics", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--steps", type=int, required=True)
    parser.add_argument("--data-factor", type=int, default=2)
    parser.add_argument("--test-every", type=int, default=8)
    parser.add_argument("--trajectory-frames", type=int, default=540)
    parser.add_argument(
        "--source-name",
        default="DL3DV-10K COLMAP/NeRFStudio scene",
    )
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(16 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def as_numpy(tensor: torch.Tensor) -> np.ndarray:
    return tensor.detach().cpu().numpy().astype(np.float32, copy=False)


def write_standard_ply(splats: dict[str, torch.Tensor], output: Path) -> int:
    required = {"means", "sh0", "shN", "opacities", "scales", "quats"}
    missing = sorted(required - set(splats))
    if missing:
        raise RuntimeError(f"checkpoint missing splat tensors: {missing}")

    xyz = as_numpy(splats["means"])
    sh0 = as_numpy(splats["sh0"]).reshape(len(xyz), 3)
    shn = as_numpy(splats["shN"])
    opacity = as_numpy(splats["opacities"]).reshape(len(xyz))
    scales = as_numpy(splats["scales"])
    rotations = as_numpy(splats["quats"])

    expected_shapes = {
        "xyz": (len(xyz), 3),
        "sh0": (len(xyz), 3),
        "shN": (len(xyz), 15, 3),
        "scales": (len(xyz), 3),
        "rotations": (len(xyz), 4),
    }
    actual_shapes = {
        "xyz": xyz.shape,
        "sh0": sh0.shape,
        "shN": shn.shape,
        "scales": scales.shape,
        "rotations": rotations.shape,
    }
    if actual_shapes != expected_shapes:
        raise RuntimeError(
            f"unexpected SH3 checkpoint shapes: {actual_shapes} != {expected_shapes}"
        )
    for name, values in (
        ("xyz", xyz),
        ("sh0", sh0),
        ("shN", shn),
        ("opacity", opacity),
        ("scales", scales),
        ("rotations", rotations),
    ):
        if not np.isfinite(values).all():
            raise RuntimeError(f"non-finite values in {name}")
    rotation_norms = np.linalg.norm(rotations, axis=1, keepdims=True)
    if np.any(rotation_norms <= 1e-12):
        raise RuntimeError("checkpoint contains zero-length Gaussian quaternion")
    rotations = rotations / rotation_norms

    # Graphdeco PLY stores f_rest color-major. gaussian_renderer reverses this
    # layout back to [coefficient, RGB] when loading.
    sh_rest = shn.transpose(0, 2, 1).reshape(len(xyz), 45)
    names = (
        ["x", "y", "z", "nx", "ny", "nz"]
        + [f"f_dc_{index}" for index in range(3)]
        + [f"f_rest_{index}" for index in range(45)]
        + ["opacity"]
        + [f"scale_{index}" for index in range(3)]
        + [f"rot_{index}" for index in range(4)]
    )
    dtype = np.dtype([(name, "<f4") for name in names])
    records = np.empty(len(xyz), dtype=dtype)
    for axis, name in enumerate(("x", "y", "z")):
        records[name] = xyz[:, axis]
    for name in ("nx", "ny", "nz"):
        records[name] = 0.0
    for index in range(3):
        records[f"f_dc_{index}"] = sh0[:, index]
    for index in range(45):
        records[f"f_rest_{index}"] = sh_rest[:, index]
    records["opacity"] = opacity
    for index in range(3):
        records[f"scale_{index}"] = scales[:, index]
    for index in range(4):
        records[f"rot_{index}"] = rotations[:, index]

    header = (
        "ply\n"
        "format binary_little_endian 1.0\n"
        "comment standard Graphdeco 3D Gaussian Splatting SH3 background\n"
        f"element vertex {len(records)}\n"
        + "".join(f"property float {name}\n" for name in names)
        + "end_header\n"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("wb") as handle:
        handle.write(header.encode("ascii"))
        records.tofile(handle)
    return len(records)


def rotation_angle_degrees(left: np.ndarray, right: np.ndarray) -> float:
    delta = left.T @ right
    cosine = np.clip((np.trace(delta) - 1.0) * 0.5, -1.0, 1.0)
    return float(np.degrees(np.arccos(cosine)))


def interpolate_camera_path(
    c2ws: np.ndarray,
    frame_count: int,
) -> tuple[np.ndarray, dict]:
    if len(c2ws) < 8:
        raise RuntimeError(f"too few training cameras: {len(c2ws)}")
    max_step_translation = 0.20
    max_step_rotation_degrees = 20.0
    adjacent_translations = np.linalg.norm(
        np.diff(c2ws[:, :3, 3], axis=0),
        axis=1,
    )
    adjacent_rotations = np.asarray(
        [
            rotation_angle_degrees(c2ws[i, :3, :3], c2ws[i + 1, :3, :3])
            for i in range(len(c2ws) - 1)
        ]
    )
    discontinuities = np.flatnonzero(
        (adjacent_translations > max_step_translation)
        | (adjacent_rotations > max_step_rotation_degrees)
    )
    segment_starts = np.concatenate(([0], discontinuities + 1))
    segment_ends = np.concatenate((discontinuities + 1, [len(c2ws)]))
    candidates: list[tuple[tuple[float, ...], int, int]] = []
    for segment_start, segment_end in zip(segment_starts, segment_ends):
        segment_length = int(segment_end - segment_start)
        if segment_length < 8:
            continue
        window_size = min(64, segment_length)
        for start in range(
            int(segment_start),
            int(segment_end) - window_size + 1,
        ):
            end = start + window_size
            window = c2ws[start:end]
            translations = adjacent_translations[start : end - 1]
            rotations = adjacent_rotations[start : end - 1]
            span = np.linalg.norm(
                window[:, :3, 3].max(axis=0)
                - window[:, :3, 3].min(axis=0)
            )
            score = (
                -float(window_size),
                float(translations.max()),
                float(rotations.max()),
                -float(span),
            )
            candidates.append((score, start, end))
    if not candidates:
        # Sparse captures can be fully registered while still moving farther
        # than the interpolation limit between every few selected frames.  In
        # that case, never synthesize views across those gaps.  A deterministic
        # forward/reverse sequence of the captured poses gives downstream
        # camera-coverage checks the complete evidence set while ensuring every
        # emitted pose is an actual training view.
        half = frame_count // 2
        forward = np.linspace(0, len(c2ws) - 1, half, endpoint=True)
        backward = np.linspace(
            len(c2ws) - 1,
            0,
            frame_count - half,
            endpoint=True,
        )
        indices = np.rint(np.concatenate([forward, backward])).astype(int)
        result = c2ws[indices].copy()
        return result.astype(np.float32), {
            "selection": {
                "training_camera_start": 0,
                "training_camera_count": len(c2ws),
                "training_camera_end_exclusive": len(c2ws),
                "path": "forward-and-reverse-captured-pose-holds",
                "discontinuities_excluded": int(len(discontinuities)),
                "discontinuities_preserved_as_frame_jumps": int(
                    len(discontinuities)
                ),
                "max_allowed_adjacent_translation": max_step_translation,
                "max_allowed_adjacent_rotation_degrees": (
                    max_step_rotation_degrees
                ),
                "interpolated_across_discontinuities": False,
            },
            "coverage": {
                "max_nearest_training_translation": 0.0,
                "median_nearest_training_translation": 0.0,
                "max_nearest_training_rotation_degrees": 0.0,
                "median_nearest_training_rotation_degrees": 0.0,
            },
        }
    _, best_start, best_end = min(candidates, key=lambda item: item[0])
    keyframes = c2ws[best_start:best_end]
    window_size = len(keyframes)
    selected_translations = adjacent_translations[best_start : best_end - 1]
    selected_rotations = adjacent_rotations[best_start : best_end - 1]

    half = frame_count // 2
    forward = np.linspace(0.0, len(keyframes) - 1.0, half, endpoint=True)
    backward = np.linspace(
        len(keyframes) - 1.0,
        0.0,
        frame_count - half,
        endpoint=True,
    )
    positions = np.concatenate([forward, backward])
    result = np.repeat(np.eye(4, dtype=np.float64)[None], frame_count, axis=0)
    key_times = np.arange(len(keyframes), dtype=np.float64)
    slerp = Slerp(key_times, Rotation.from_matrix(keyframes[:, :3, :3]))
    result[:, :3, :3] = slerp(positions).as_matrix()
    for axis in range(3):
        result[:, axis, 3] = np.interp(
            positions,
            key_times,
            keyframes[:, axis, 3],
        )

    train_centers = c2ws[:, :3, 3]
    nearest_distances: list[float] = []
    nearest_angles: list[float] = []
    for camera in result:
        distances = np.linalg.norm(train_centers - camera[:3, 3], axis=1)
        angles = np.asarray(
            [
                rotation_angle_degrees(
                    training_camera[:3, :3],
                    camera[:3, :3],
                )
                for training_camera in c2ws
            ]
        )
        joint_pose_distance = (
            distances / max_step_translation
            + angles / max_step_rotation_degrees
        )
        nearest = int(np.argmin(joint_pose_distance))
        nearest_distances.append(float(distances[nearest]))
        nearest_angles.append(float(angles[nearest]))
    metadata = {
        "selection": {
            "training_camera_start": best_start,
            "training_camera_count": window_size,
            "training_camera_end_exclusive": best_end,
            "path": "forward-and-reverse-piecewise-slerp",
            "discontinuities_excluded": int(len(discontinuities)),
            "max_allowed_adjacent_translation": max_step_translation,
            "max_allowed_adjacent_rotation_degrees": max_step_rotation_degrees,
            "selected_max_adjacent_translation": float(
                selected_translations.max()
            ),
            "selected_max_adjacent_rotation_degrees": float(
                selected_rotations.max()
            ),
        },
        "coverage": {
            "max_nearest_training_translation": max(nearest_distances),
            "median_nearest_training_translation": float(
                np.median(nearest_distances)
            ),
            "max_nearest_training_rotation_degrees": max(nearest_angles),
            "median_nearest_training_rotation_degrees": float(
                np.median(nearest_angles)
            ),
        },
    }
    return result.astype(np.float32), metadata


def render_reference(
    splats: dict[str, torch.Tensor],
    sample: dict,
    output: Path,
) -> tuple[int, int]:
    from gsplat.rendering import rasterization

    pixels = sample["image"].cpu().numpy().astype(np.uint8)
    height, width = pixels.shape[:2]
    device = splats["means"].device
    camtoworld = sample["camtoworld"].to(device)
    intrinsic = sample["K"].to(device)
    renders, _, _ = rasterization(
        means=splats["means"],
        quats=splats["quats"],
        scales=torch.exp(splats["scales"]),
        opacities=torch.sigmoid(splats["opacities"]),
        colors=torch.cat([splats["sh0"], splats["shN"]], dim=1),
        viewmats=torch.linalg.inv(camtoworld)[None],
        Ks=intrinsic[None],
        width=width,
        height=height,
        packed=False,
        near_plane=0.01,
        far_plane=1e10,
        render_mode="RGB",
        sh_degree=3,
        rasterize_mode="antialiased",
    )
    rgb = (
        renders[0, ..., :3].clamp(0.0, 1.0).mul(255).byte().cpu().numpy()
    )
    if sample.get("mask") is not None:
        mask = sample["mask"].cpu().numpy().astype(bool)
        pixels = pixels * mask[..., None]
        rgb = rgb * mask[..., None]
    Image.fromarray(pixels).save(output / "reference_source.png")
    Image.fromarray(rgb).save(output / "reference_gsplat.png")
    return width, height


def main() -> None:
    args = parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(args.gsplat / "examples"))
    from datasets.colmap import Dataset, Parser

    # This checkpoint is produced inside the same isolated job and may contain
    # optimizer metadata with NumPy scalar values. PyTorch 2.2 cannot decode
    # those values through the restricted weights-only unpickler.
    checkpoint = torch.load(
        args.checkpoint,
        map_location="cuda",
        weights_only=False,
    )
    recorded_step = int(checkpoint["step"]) + 1
    if recorded_step != args.steps:
        raise RuntimeError(
            f"checkpoint step mismatch: {recorded_step} != {args.steps}"
        )
    splats = {name: value.cuda() for name, value in checkpoint["splats"].items()}
    ply_path = args.output / "gaussians.ply"
    gaussian_count = write_standard_ply(splats, ply_path)

    parser = Parser(
        str(args.dataset),
        factor=args.data_factor,
        normalize=True,
        test_every=args.test_every,
    )
    if getattr(parser, "split_indices", None) is not None:
        train_indices = parser.split_indices["train"]
    else:
        train_indices = np.arange(len(parser.image_names))
        train_indices = train_indices[train_indices % args.test_every != 0]
    valset = Dataset(parser, split="val")
    if len(valset) == 0:
        raise RuntimeError("held-out dataset is empty")
    comparison_sample = valset[0]
    comparison_width, comparison_height = render_reference(
        splats,
        comparison_sample,
        args.output,
    )

    trajectory, trajectory_metadata = interpolate_camera_path(
        parser.camtoworlds[train_indices],
        args.trajectory_frames,
    )
    comparison_camera_id = parser.camera_ids[int(valset.indices[0])]
    comparison_k = parser.Ks_dict[comparison_camera_id]
    comparison_fovy = math.degrees(
        2.0
        * math.atan(
            parser.imsize_dict[comparison_camera_id][1]
            / (2.0 * float(comparison_k[1, 1]))
        )
    )
    path_camera_id = parser.camera_ids[int(train_indices[0])]
    path_k = parser.Ks_dict[path_camera_id]
    path_height = parser.imsize_dict[path_camera_id][1]
    path_fovy = math.degrees(
        2.0 * math.atan(path_height / (2.0 * float(path_k[1, 1])))
    )

    camera_path = {
        "schema_version": 1,
        "coordinate_convention": "normalized COLMAP/OpenCV camera-to-world",
        "frames": args.trajectory_frames,
        "fovy_degrees": path_fovy,
        "camtoworlds": trajectory.tolist(),
        "comparison": {
            "image_name": parser.image_names[int(valset.indices[0])],
            "source_width": comparison_width,
            "source_height": comparison_height,
            "fovy_degrees": comparison_fovy,
            "camtoworld": comparison_sample["camtoworld"].numpy().tolist(),
        },
        **trajectory_metadata,
    }
    (args.output / "camera-path.json").write_text(
        json.dumps(camera_path, indent=2) + "\n",
        encoding="utf-8",
    )

    camera_centers = parser.camtoworlds[:, :3, 3]
    sim3 = np.asarray(parser.transform, dtype=np.float64)
    sim3_scale = float(np.mean(np.linalg.norm(sim3[:3, :3], axis=1)))
    alignment = {
        "schema_version": 1,
        "source": args.source_name,
        "source_camera_convention": {
            "matrix": "camera-to-world",
            "axes": "+X right, +Y down, +Z forward",
        },
        "mujoco_camera_adapter": {
            "matrix": "R_mujoco = R_opencv @ diag(1,-1,-1)",
            "reason": "gaussian_renderer converts MuJoCo Y-up camera axes back to OpenCV",
        },
        "source_colmap_to_mujoco_sim3": sim3.tolist(),
        "sim3_scale": sim3_scale,
        "mujoco_units": "normalized capture units; background is non-physical",
        "camera_envelope": {
            "min": camera_centers.min(axis=0).tolist(),
            "max": camera_centers.max(axis=0).tolist(),
            "center": camera_centers.mean(axis=0).tolist(),
            "radius": float(
                np.linalg.norm(
                    camera_centers - camera_centers.mean(axis=0),
                    axis=1,
                ).max()
            ),
            "all_cameras": len(camera_centers),
            "training_cameras": len(train_indices),
            "held_out_cameras": len(valset),
            **trajectory_metadata["coverage"],
        },
    }
    (args.output / "alignment.json").write_text(
        json.dumps(alignment, indent=2) + "\n",
        encoding="utf-8",
    )

    metrics = json.loads(args.metrics.read_text(encoding="utf-8"))
    report = {
        "schema_version": 1,
        "status": "passed",
        "candidate": args.candidate,
        "steps": args.steps,
        "data_factor": args.data_factor,
        "test_every": (
            None
            if getattr(parser, "split_indices", None) is not None
            else args.test_every
        ),
        "split_mode": (
            "scannetpp-official"
            if getattr(parser, "split_indices", None) is not None
            else f"every-{args.test_every}"
        ),
        "gaussians": gaussian_count,
        "checkpoint_step": int(checkpoint["step"]),
        "checkpoint_photo_quality": checkpoint.get("photo_quality"),
        "metrics": metrics,
        "ply": {
            "path": ply_path.name,
            "format": "Graphdeco standard binary little-endian SH3",
            "bytes": ply_path.stat().st_size,
            "sha256": sha256(ply_path),
            "contains_mesh": False,
        },
        "camera_path": trajectory_metadata,
    }
    (args.output / "gaussian-export-report.json").write_text(
        json.dumps(report, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
