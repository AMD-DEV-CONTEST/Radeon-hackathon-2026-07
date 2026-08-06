#!/usr/bin/env python3
"""Split a standard Graphdeco PLY into collision-free room-shell layers.

The PLY records are copied byte-for-byte.  Spatial classification happens in
the metric MuJoCo frame described by ``gaussian_to_mujoco``; the stored means,
SH coefficients, rotations, and scales remain in the trained Gaussian frame.
This avoids degrading view-dependent appearance.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

PLY_TYPES = {
    "char": "i1",
    "uchar": "u1",
    "int8": "i1",
    "uint8": "u1",
    "short": "<i2",
    "ushort": "<u2",
    "int16": "<i2",
    "uint16": "<u2",
    "int": "<i4",
    "uint": "<u4",
    "int32": "<i4",
    "uint32": "<u4",
    "float": "<f4",
    "float32": "<f4",
    "double": "<f8",
    "float64": "<f8",
}


@dataclass
class VertexPly:
    comments: list[str]
    properties: list[tuple[str, str]]
    records: np.ndarray


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--camera-path", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--alignment", type=Path)
    parser.add_argument("--source-report", type=Path)
    parser.add_argument(
        "--source-screening-report",
        type=Path,
        help=(
            "A passed 36-view source-material gate. When supplied, the input "
            "must already have a genuinely empty center and the exporter "
            "preserves the full photographed floor instead of deleting a "
            "post-training volume."
        ),
    )
    parser.add_argument("--workspace-obb", type=Path)
    parser.add_argument("--semantic-remove-mask", type=Path)
    parser.add_argument("--semantic-report", type=Path)
    parser.add_argument("--semantic-registration-margin", type=float, default=0.25)
    parser.add_argument("--workspace-margin", type=float, default=0.30)
    parser.add_argument("--camera-height", type=float, default=1.55)
    parser.add_argument("--wall-band", type=float, default=0.65)
    parser.add_argument("--center-width", type=float, default=3.0)
    parser.add_argument("--center-depth", type=float, default=3.0)
    parser.add_argument("--clear-height", type=float, default=2.4)
    parser.add_argument("--ground-clearance", type=float, default=0.05)
    parser.add_argument("--floor-thickness", type=float, default=0.10)
    parser.add_argument("--ceiling-thickness", type=float, default=0.18)
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(32 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_ply(path: Path) -> VertexPly:
    with path.open("rb") as handle:
        first = handle.readline()
        if first != b"ply\n":
            raise RuntimeError("input is not a PLY file")
        header_lines: list[str] = []
        while True:
            line = handle.readline()
            if not line:
                raise RuntimeError("truncated PLY header")
            decoded = line.decode("ascii").rstrip("\r\n")
            if decoded == "end_header":
                break
            header_lines.append(decoded)
        if "format binary_little_endian 1.0" not in header_lines:
            raise RuntimeError("only binary_little_endian PLY is supported")
        vertex_matches = [
            re.fullmatch(r"element vertex ([0-9]+)", line)
            for line in header_lines
        ]
        counts = [int(match.group(1)) for match in vertex_matches if match]
        if len(counts) != 1:
            raise RuntimeError("expected exactly one vertex element")
        if any(
            line.startswith("element ") and not line.startswith("element vertex ")
            for line in header_lines
        ):
            raise RuntimeError("PLY contains non-vertex elements")
        properties: list[tuple[str, str]] = []
        for line in header_lines:
            match = re.fullmatch(r"property ([A-Za-z0-9_]+) ([A-Za-z0-9_]+)", line)
            if not match:
                continue
            kind, name = match.groups()
            if kind not in PLY_TYPES:
                raise RuntimeError(f"unsupported PLY property type: {kind}")
            properties.append((kind, name))
        if not properties:
            raise RuntimeError("PLY has no scalar vertex properties")
        dtype = np.dtype([(name, PLY_TYPES[kind]) for kind, name in properties])
        records = np.fromfile(handle, dtype=dtype, count=counts[0])
        if len(records) != counts[0]:
            raise RuntimeError("truncated PLY vertex data")
        if handle.read(1):
            raise RuntimeError("unexpected bytes after vertex element")
    required = {"x", "y", "z", "opacity"}
    if not required.issubset(records.dtype.names or ()):
        raise RuntimeError(f"PLY lacks required properties: {sorted(required)}")
    comments = [line for line in header_lines if line.startswith("comment ")]
    return VertexPly(comments=comments, properties=properties, records=records)


def write_ply(source: VertexPly, mask: np.ndarray, path: Path, label: str) -> None:
    selected = source.records[mask]
    header = [
        "ply",
        "format binary_little_endian 1.0",
        *source.comments,
        f"comment DL3DV room-shell layer: {label}",
        f"element vertex {len(selected)}",
        *(f"property {kind} {name}" for kind, name in source.properties),
        "end_header",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        handle.write(("\n".join(header) + "\n").encode("ascii"))
        selected.tofile(handle)


def align_vector(left: np.ndarray, right: np.ndarray) -> np.ndarray:
    left = left / np.linalg.norm(left)
    right = right / np.linalg.norm(right)
    cross = np.cross(left, right)
    dot = float(np.clip(np.dot(left, right), -1.0, 1.0))
    if np.linalg.norm(cross) < 1e-9:
        return np.eye(3) if dot > 0 else np.diag([1.0, -1.0, -1.0])
    skew = np.array(
        [[0.0, -cross[2], cross[1]], [cross[2], 0.0, -cross[0]], [-cross[1], cross[0], 0.0]]
    )
    return np.eye(3) + skew + skew @ skew * ((1.0 - dot) / np.dot(cross, cross))


def load_cameras(path: Path) -> np.ndarray:
    payload = json.loads(path.read_text(encoding="utf-8"))
    matrices = payload.get("camtoworlds")
    raw_nerfstudio_frames = False
    if matrices is None and "frames" in payload and isinstance(payload["frames"], list):
        matrices = [
            frame.get("transform_matrix") or frame.get("camtoworld")
            for frame in payload["frames"]
        ]
        raw_nerfstudio_frames = True
    cameras = np.asarray(matrices, dtype=np.float64)
    if cameras.ndim != 3 or cameras.shape[1:] != (4, 4):
        raise RuntimeError(f"invalid camera path shape: {cameras.shape}")
    if len(cameras) < 8 or not np.isfinite(cameras).all():
        raise RuntimeError("camera path is insufficient or non-finite")
    if raw_nerfstudio_frames:
        cameras = cameras.copy()
        cameras[:, :3, 1:3] *= -1.0
    return cameras


def estimate_alignment(
    xyz: np.ndarray,
    cameras: np.ndarray,
    camera_height: float,
) -> tuple[np.ndarray, dict[str, object]]:
    camera_up = -cameras[:, :3, 1].mean(axis=0)
    rotation_up = align_vector(camera_up, np.array([0.0, 0.0, 1.0]))
    aligned_xyz = xyz @ rotation_up.T
    aligned_cameras = cameras[:, :3, 3] @ rotation_up.T
    center_xy = np.median(aligned_cameras[:, :2], axis=0)
    radial = np.linalg.norm(aligned_xyz[:, :2] - center_xy, axis=1)
    central = aligned_xyz[radial <= np.quantile(radial, 0.65)]
    floor_raw = float(np.quantile(central[:, 2], 0.01))
    median_camera_z = float(np.median(aligned_cameras[:, 2]))
    raw_height = median_camera_z - floor_raw
    if not math.isfinite(raw_height) or raw_height <= 1e-4:
        raise RuntimeError(f"cannot infer positive camera height: {raw_height}")
    scale = camera_height / raw_height
    centered_xy = aligned_xyz[:, :2] - np.median(aligned_xyz[:, :2], axis=0)
    covariance = np.cov(centered_xy, rowvar=False)
    eigenvalues, eigenvectors = np.linalg.eigh(covariance)
    major = eigenvectors[:, int(np.argmax(eigenvalues))]
    yaw = math.atan2(major[1], major[0])
    c, s = math.cos(-yaw), math.sin(-yaw)
    rotation_yaw = np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])
    rotation = rotation_yaw @ rotation_up
    rotated_xyz = xyz @ rotation.T
    rotated_cameras = cameras[:, :3, 3] @ rotation.T
    floor_rotated = float(np.quantile(rotated_xyz[:, 2], 0.01))
    translation = np.array(
        [
            -float(np.median(rotated_cameras[:, 0])) * scale,
            -float(np.median(rotated_cameras[:, 1])) * scale,
            -floor_rotated * scale,
        ]
    )
    transform = np.eye(4)
    transform[:3, :3] = scale * rotation
    transform[:3, 3] = translation
    return transform, {
        "method": "camera-up plus XY-PCA, floor quantile, median camera-height scale",
        "camera_height_assumption_m": camera_height,
        "raw_camera_height": raw_height,
        "scale": scale,
        "floor_quantile": 0.01,
        "estimated_yaw_degrees": math.degrees(yaw),
        "warning": "scale is estimated, not surveyed",
    }


def transform_points(points: np.ndarray, transform: np.ndarray) -> np.ndarray:
    return points @ transform[:3, :3].T + transform[:3, 3]


def main() -> None:
    args = parse_args()
    if min(
        args.camera_height,
        args.wall_band,
        args.center_width,
        args.center_depth,
        args.clear_height,
        args.ground_clearance,
        args.floor_thickness,
        args.ceiling_thickness,
        args.workspace_margin,
        args.semantic_registration_margin,
    ) <= 0:
        raise SystemExit("all spatial dimensions must be positive")
    source = read_ply(args.input)
    xyz = np.column_stack(
        [source.records["x"], source.records["y"], source.records["z"]]
    ).astype(np.float64, copy=False)
    if not np.isfinite(xyz).all():
        raise RuntimeError("non-finite Gaussian means")
    cameras = load_cameras(args.camera_path)
    if args.alignment:
        alignment_payload = json.loads(args.alignment.read_text(encoding="utf-8"))
        transform = np.asarray(
            alignment_payload.get("gaussian_to_mujoco")
            or alignment_payload.get("source_gaussian_to_mujoco_sim3"),
            dtype=np.float64,
        )
        if transform.shape != (4, 4):
            raise RuntimeError("alignment lacks a 4x4 gaussian_to_mujoco transform")
        scale_source = alignment_payload.get("scale_estimation", {"method": "provided"})
    else:
        transform, scale_source = estimate_alignment(xyz, cameras, args.camera_height)
    workspace_source: dict[str, object] = {
        "method": "explicit shell exporter arguments",
        "margin_xy_m": 0.0,
    }
    center_xy = np.zeros(2, dtype=np.float64)
    center_width = args.center_width
    center_depth = args.center_depth
    clear_height = args.clear_height
    if args.workspace_obb:
        workspace_payload = json.loads(
            args.workspace_obb.read_text(encoding="utf-8")
        )
        center_xy = np.asarray(
            workspace_payload["center_xy_m"], dtype=np.float64
        )
        if center_xy.shape != (2,) or not np.isfinite(center_xy).all():
            raise RuntimeError("workspace OBB center_xy_m must contain two numbers")
        center_width = float(workspace_payload["width_m"]) + 2.0 * args.workspace_margin
        center_depth = float(workspace_payload["depth_m"]) + 2.0 * args.workspace_margin
        clear_height = (
            float(workspace_payload.get("clear_height_m", args.clear_height))
            + args.workspace_margin
        )
        workspace_source = {
            "method": "MuJoCo geom OBB with explicit safety margin",
            "path": str(args.workspace_obb),
            "margin_xy_m": args.workspace_margin,
            "raw": workspace_payload,
        }

    metric = transform_points(xyz, transform)
    camera_metric = transform_points(cameras[:, :3, 3], transform)
    if not np.isfinite(metric).all():
        raise RuntimeError("non-finite aligned Gaussian means")

    semantic_remove = np.zeros(len(source.records), dtype=bool)
    source_screening: dict[str, object] = {
        "status": "not_supplied",
        "source_center_clean": False,
    }
    source_center_clean = False
    if args.source_screening_report:
        source_screening = json.loads(
            args.source_screening_report.read_text(encoding="utf-8")
        )
        if source_screening.get("status") != "passed":
            raise RuntimeError("source screening report did not pass")
        if int(source_screening.get("checked_frames", 0)) < 36:
            raise RuntimeError("source screening used fewer than 36 frames")
        if float(source_screening.get("central_clear_fraction", 0.0)) < 0.95:
            raise RuntimeError("source screening central-clear fraction is below 95%")
        source_center_clean = True
    semantic_cleanup: dict[str, object] = {
        "status": "not_requested",
        "removed_gaussians": 0,
    }
    semantic_registration: dict[str, object] = {
        "status": "not_requested",
    }
    if args.semantic_remove_mask:
        semantic_remove = np.load(args.semantic_remove_mask)
        if semantic_remove.shape != (len(source.records),):
            raise RuntimeError(
                "semantic removal mask shape mismatch: "
                f"{semantic_remove.shape} != {(len(source.records),)}"
            )
        if semantic_remove.dtype != np.bool_:
            semantic_remove = semantic_remove.astype(bool)
        if int(semantic_remove.sum()) < 100:
            raise RuntimeError("semantic removal mask contains too few Gaussians")
        semantic_cleanup = {
            "status": "passed",
            "mask_path": str(args.semantic_remove_mask),
            "removed_gaussians": int(semantic_remove.sum()),
        }
        if args.semantic_report:
            semantic_report = json.loads(
                args.semantic_report.read_text(encoding="utf-8")
            )
            if semantic_report.get("status") != "passed":
                raise RuntimeError("semantic cleanup report did not pass")
            semantic_cleanup["report"] = semantic_report

        # The camera-derived Sim(3) establishes metric scale and orientation,
        # but its XY origin is arbitrary. Register the actual photographed
        # island/table cluster to the target MJCF workspace before applying the
        # deterministic exclusion OBB. This removes missed/translucent splats
        # around the subject while keeping the fixed perimeter unchanged.
        semantic_metric_before = metric[semantic_remove]
        detected_center_xy = np.median(semantic_metric_before[:, :2], axis=0)
        translation_xy = center_xy - detected_center_xy
        transform = transform.copy()
        transform[:2, 3] += translation_xy
        metric = transform_points(xyz, transform)
        camera_metric = transform_points(cameras[:, :3, 3], transform)
        semantic_metric = metric[semantic_remove]
        semantic_q05 = np.quantile(semantic_metric[:, :2], 0.05, axis=0)
        semantic_q95 = np.quantile(semantic_metric[:, :2], 0.95, axis=0)
        semantic_extent = semantic_q95 - semantic_q05
        requested_width = float(
            semantic_extent[0] + 2.0 * args.semantic_registration_margin
        )
        requested_depth = float(
            semantic_extent[1] + 2.0 * args.semantic_registration_margin
        )
        center_width = max(center_width, requested_width)
        center_depth = max(center_depth, requested_depth)
        semantic_registration = {
            "status": "passed",
            "method": (
                "robust semantic subject center to target MuJoCo workspace "
                "center, followed by 5-95% extent expansion"
            ),
            "detected_center_before_m": detected_center_xy.tolist(),
            "target_workspace_center_m": center_xy.tolist(),
            "translation_xy_m": translation_xy.tolist(),
            "semantic_extent_q05_q95_m": semantic_extent.tolist(),
            "extent_margin_m": args.semantic_registration_margin,
            "final_exclusion_width_m": center_width,
            "final_exclusion_depth_m": center_depth,
        }

    lower = np.quantile(metric[:, :2], 0.005, axis=0)
    upper = np.quantile(metric[:, :2], 0.995, axis=0)
    floor_z = float(np.quantile(metric[:, 2], 0.01))
    ceiling_z = float(np.quantile(metric[:, 2], 0.99))
    room_height = ceiling_z - floor_z
    if room_height < 2.0 or room_height > 12.0:
        raise RuntimeError(f"implausible aligned room height: {room_height:.3f} m")

    floor = metric[:, 2] <= floor_z + args.floor_thickness
    ceiling = metric[:, 2] >= ceiling_z - args.ceiling_thickness
    inside_workspace_xy = (
        (np.abs(metric[:, 0] - center_xy[0]) < center_width / 2.0)
        & (np.abs(metric[:, 1] - center_xy[1]) < center_depth / 2.0)
    )
    inside_center_spatial = (
        inside_workspace_xy
        & (metric[:, 2] > floor_z + args.ground_clearance)
        & (metric[:, 2] < floor_z + clear_height)
    )
    inside_center = semantic_remove if source_center_clean else (
        inside_center_spatial | semantic_remove
    )
    # A Gaussian cloud is an appearance representation, not a watertight room
    # surface.  Classifying "walls" from the extreme XYZ bounds discarded most
    # of the view-supporting splats whenever a few outliers expanded the room
    # bounds.  The requested asset is the peripheral room ring: retain every
    # non-horizontal Gaussian outside the deterministic center exclusion and
    # remove only the space reserved for the user's table and robot.
    walls_decor = ~floor & ~ceiling & ~inside_center
    floor_perimeter = floor & ~semantic_remove
    if not source_center_clean:
        floor_perimeter &= ~inside_workspace_xy
    # A few low ceiling-classified splats can overlap the task clearance when
    # the inferred room height is compact. Keep the central robot volume
    # strictly empty instead of allowing those ambiguous records through.
    ceiling_lights = ceiling & ~semantic_remove & ~inside_center
    shell = floor_perimeter | ceiling_lights | walls_decor

    args.output.mkdir(parents=True, exist_ok=True)
    masks = {
        "walls_fixed_kitchen.ply": walls_decor,
        "floor_perimeter.ply": floor_perimeter,
        "ceiling_lights.ply": ceiling_lights,
        "gaussians_shell.ply": shell,
    }
    artifacts: dict[str, object] = {}
    for filename, mask in masks.items():
        path = args.output / filename
        write_ply(source, mask, path, filename.removesuffix(".ply"))
        artifacts[filename] = {
            "gaussians": int(mask.sum()),
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
        }

    center_violation = shell & inside_center & ~floor
    if center_violation.any():
        raise RuntimeError(
            f"center exclusion contains {int(center_violation.sum())} shell Gaussians"
        )
    alignment = {
        "schema_version": 1,
        "gaussian_to_mujoco": transform.tolist(),
        "mujoco_to_gaussian": np.linalg.inv(transform).tolist(),
        "coordinate_convention": {
            "mujoco": "+Z up, meters",
            "gaussian": "trained COLMAP/gsplat frame; PLY records are not transformed",
            "renderer_camera_adapter": "MuJoCo camera is mapped through mujoco_to_gaussian before rasterization",
        },
        "scale_estimation": scale_source,
    }
    alignment_path = args.output / "alignment.json"
    alignment_path.write_text(
        json.dumps(alignment, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    source_metadata: dict[str, object] = {
        "dataset": "unspecified",
        "license": "not supplied; provenance review required",
    }
    if args.source_report:
        report = json.loads(args.source_report.read_text(encoding="utf-8"))
        archive_report = report.get("archive")
        if isinstance(archive_report, dict):
            archive_report = {
                key: archive_report.get(key)
                for key in (
                    "bytes",
                    "sha256",
                    "expected_bytes",
                    "expected_sha256",
                    "zip_crc_passed",
                )
                if archive_report.get(key) is not None
            }
        source_metadata = {
            "dataset": report.get("dataset") or report.get("repo_id") or "unspecified",
            "scene": report.get("scene"),
            "scene_hash": report.get("scene_hash"),
            "category": report.get("category"),
            "revision": report.get("revision"),
            "url": report.get("source"),
            "license": report.get("license"),
            "archive": archive_report,
        }
    profile = {
        "schema_version": 1,
        "status": (
            "awaiting_visual_approval"
            if source_center_clean
            else "passed"
        ),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": source_metadata,
        "input": {
            "path": str(args.input),
            "bytes": args.input.stat().st_size,
            "sha256": sha256(args.input),
            "gaussians": len(source.records),
        },
        "room_obb": {
            "center_xy_m": [0.0, 0.0],
            "min_m": [float(lower[0]), float(lower[1]), floor_z],
            "max_m": [float(upper[0]), float(upper[1]), ceiling_z],
            "floor_z_m": floor_z,
            "ceiling_z_m": ceiling_z,
        },
        "central_exclusion": {
            "center_xy_m": center_xy.tolist(),
            "width_m": center_width,
            "depth_m": center_depth,
            "ground_clearance_m": args.ground_clearance,
            "clear_height_m": clear_height,
            "visible_gaussian_violations": int(center_violation.sum()),
            "floor_preserved": source_center_clean,
            "floor_policy": (
                "full photographed floor preserved; center emptiness passed "
                "the pre-training 36-view source gate"
                if source_center_clean
                else "perimeter only; target MJCF owns the workspace floor"
            ),
            "workspace_source": workspace_source,
            "interactive_adjustment_allowed": not source_center_clean,
        },
        "source_center_gate": source_screening,
        "human_visual_review": {
            "required": True,
            "status": "pending",
        },
        "semantic_cleanup": semantic_cleanup,
        "semantic_registration": semantic_registration,
        "wall_band_m": args.wall_band,
        "peripheral_selection": {
            "method": "all Gaussians outside the central exclusion volume",
            "reason": (
                "3DGS view support is not a watertight surface; room-boundary "
                "filtering would remove wall appearance Gaussians"
            ),
            "retained_fraction": float(shell.mean()),
        },
        "camera_envelope_m": {
            "min": camera_metric.min(axis=0).tolist(),
            "max": camera_metric.max(axis=0).tolist(),
            "center": camera_metric.mean(axis=0).tolist(),
            "cameras": len(camera_metric),
        },
        "integration_contract": {
            "camera_names": ["head", "left_wrist", "right_wrist"],
            "formal_collection_failure_policy": "abort",
            "interactive_viewer_failure_policy": "native_mujoco_with_warning",
            "native_background_geom_names": ["floor"],
            "foreground_compositing": (
                "MuJoCo segmentation preserves robot, table, props, and other "
                "task geoms in front of the Gaussian shell"
            ),
            "observations": {
                "rgb_head": {"shape_chw": [3, 480, 848], "fovy_degrees": 58.0},
                "rgb_left_wrist": {
                    "shape_chw": [3, 480, 640],
                    "fovy_degrees": 58.0,
                },
                "rgb_right_wrist": {
                    "shape_chw": [3, 480, 640],
                    "fovy_degrees": 58.0,
                },
            },
        },
        "background_physics": {
            "mujoco_body_count": 0,
            "mujoco_geom_count": 0,
            "collision_count": 0,
            "mesh_or_obj_generated": False,
        },
        "layers": artifacts,
        "layer_files": {
            "walls_decor": "walls_fixed_kitchen.ply",
            "floor": "floor_perimeter.ply",
            "ceiling": "ceiling_lights.ply",
            "combined": "gaussians_shell.ply",
        },
        "alignment": {
            "path": alignment_path.name,
            "sha256": sha256(alignment_path),
        },
    }
    profile_path = args.output / "scene-shell-profile.json"
    profile_path.write_text(
        json.dumps(profile, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(profile, ensure_ascii=False))


if __name__ == "__main__":
    main()
