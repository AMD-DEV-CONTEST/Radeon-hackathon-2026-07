#!/usr/bin/env python3
"""Validate and optionally sanitize a standard Graphdeco SH3 Gaussian PLY.

The sanitizer is intentionally conservative. It normalizes quaternions and
removes only non-finite records plus Gaussians that are both outside a robust
scene radius and invisible from every supplied camera. It never clamps scales,
edits spherical harmonics, or paints missing content.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from reconstruction.src.export_scene_shell import (
    VertexPly,
    read_ply,
)


GRAPHDECO_SH3_PROPERTIES = (
    ["x", "y", "z", "nx", "ny", "nz"]
    + [f"f_dc_{index}" for index in range(3)]
    + [f"f_rest_{index}" for index in range(45)]
    + ["opacity"]
    + [f"scale_{index}" for index in range(3)]
    + [f"rot_{index}" for index in range(4)]
)
QUANTILES = (0.5, 0.9, 0.99, 0.995, 0.999, 1.0)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--camera-path", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--clean-output", type=Path)
    parser.add_argument("--metrics", type=Path)
    parser.add_argument("--parity-metrics", type=Path)
    parser.add_argument("--viewer-review", type=Path)
    parser.add_argument("--experiment-config", type=Path)
    parser.add_argument("--export-report", type=Path)
    parser.add_argument("--scene-hash")
    parser.add_argument("--resolution", default="unknown")
    parser.add_argument("--canonical-cameras", type=int, default=12)
    parser.add_argument("--robust-radius-quantile", type=float, default=0.995)
    parser.add_argument("--frustum-margin", type=float, default=1.10)
    parser.add_argument("--spike-alpha", type=float, default=0.01)
    parser.add_argument("--spike-ratio", type=float, default=100.0)
    parser.add_argument("--spike-frame-fraction", type=float, default=0.05)
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(32 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sigmoid(values: np.ndarray) -> np.ndarray:
    values = np.asarray(values, dtype=np.float64)
    return 1.0 / (1.0 + np.exp(-np.clip(values, -50.0, 50.0)))


def quantiles(values: np.ndarray) -> dict[str, float]:
    finite = np.asarray(values, dtype=np.float64)
    finite = finite[np.isfinite(finite)]
    if not len(finite):
        return {}
    return {
        str(value): float(np.quantile(finite, value))
        for value in QUANTILES
    }


def load_camera_path(path: Path) -> tuple[np.ndarray, dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    matrix_values = payload.get("camtoworlds")
    raw_nerfstudio_frames = False
    if matrix_values is None and isinstance(payload.get("frames"), list):
        matrix_values = [frame.get("transform_matrix") for frame in payload["frames"]]
        raw_nerfstudio_frames = True
    matrices = np.asarray(matrix_values, dtype=np.float64)
    if matrices.ndim != 3 or matrices.shape[1:] != (4, 4):
        raise RuntimeError(f"invalid camera path shape: {matrices.shape}")
    if len(matrices) < 8 or not np.isfinite(matrices).all():
        raise RuntimeError("camera path is insufficient or non-finite")
    if raw_nerfstudio_frames:
        matrices = matrices.copy()
        matrices[:, :3, 1:3] *= -1.0
    if payload.get("fovy_degrees") is not None:
        fovy = float(payload["fovy_degrees"])
    elif payload.get("camera_angle_y") is not None:
        fovy = math.degrees(float(payload["camera_angle_y"]))
    else:
        height_value = float(payload.get("h") or 0)
        focal_y = float(payload.get("fl_y") or payload.get("fl_x") or 0)
        if min(height_value, focal_y) <= 0:
            raise RuntimeError("camera path lacks vertical FOV or focal length")
        fovy = math.degrees(2.0 * math.atan(height_value / (2.0 * focal_y)))
    if not math.isfinite(fovy) or not 1.0 < fovy < 179.0:
        raise RuntimeError(f"invalid vertical FOV: {fovy}")
    comparison = payload.get("comparison", {})
    width = int(comparison.get("source_width") or payload.get("w") or 960)
    height = int(comparison.get("source_height") or payload.get("h") or 540)
    if width <= 0 or height <= 0:
        raise RuntimeError("camera path contains an invalid image size")
    return matrices, {
        "fovy_degrees": fovy,
        "width": width,
        "height": height,
        "coordinate_convention": (
            "Nerfstudio OpenGL converted to OpenCV (+Z forward)"
            if raw_nerfstudio_frames
            else payload.get("coordinate_convention")
        ),
    }


def canonical_indices(length: int, count: int) -> np.ndarray:
    if count <= 0:
        raise ValueError("canonical camera count must be positive")
    count = min(count, length)
    return np.unique(np.rint(np.linspace(0, length - 1, count)).astype(int))


def camera_visibility(
    xyz: np.ndarray,
    cameras: np.ndarray,
    fovy_degrees: float,
    aspect: float,
    margin: float,
) -> np.ndarray:
    """Return whether each point center is visible from any camera."""

    if not len(xyz):
        return np.zeros(0, dtype=bool)
    tan_y = math.tan(math.radians(fovy_degrees) * 0.5) * margin
    tan_x = tan_y * aspect
    visible = np.zeros(len(xyz), dtype=bool)
    finite = np.isfinite(xyz).all(axis=1)
    for camera in cameras:
        pending = finite & ~visible
        if not pending.any():
            break
        local = (xyz[pending] - camera[:3, 3]) @ camera[:3, :3]
        z = local[:, 2]
        in_view = (
            (z > 1e-4)
            & (np.abs(local[:, 0]) <= z * tan_x)
            & (np.abs(local[:, 1]) <= z * tan_y)
        )
        visible[np.flatnonzero(pending)[in_view]] = True
    return visible


def gaussian_arrays(records: np.ndarray) -> dict[str, np.ndarray]:
    names = set(records.dtype.names or ())
    required = {
        "x",
        "y",
        "z",
        "opacity",
        "scale_0",
        "scale_1",
        "scale_2",
        "rot_0",
        "rot_1",
        "rot_2",
        "rot_3",
    }
    missing = sorted(required - names)
    if missing:
        raise RuntimeError(f"PLY lacks Gaussian properties: {missing}")
    xyz = np.column_stack(
        [records["x"], records["y"], records["z"]]
    ).astype(np.float64)
    log_scales = np.column_stack(
        [records[f"scale_{index}"] for index in range(3)]
    ).astype(np.float64)
    scales = np.exp(np.clip(log_scales, -80.0, 20.0))
    quaternions = np.column_stack(
        [records[f"rot_{index}"] for index in range(4)]
    ).astype(np.float64)
    quaternion_norms = np.linalg.norm(quaternions, axis=1)
    alpha = sigmoid(records["opacity"])
    scale_min = scales.min(axis=1)
    scale_max = scales.max(axis=1)
    scale_ratio = np.divide(
        scale_max,
        scale_min,
        out=np.full_like(scale_max, np.inf),
        where=scale_min > 0.0,
    )
    finite = (
        np.isfinite(xyz).all(axis=1)
        & np.isfinite(log_scales).all(axis=1)
        & np.isfinite(quaternions).all(axis=1)
        & np.isfinite(records["opacity"])
        & (quaternion_norms > 1e-12)
    )
    return {
        "xyz": xyz,
        "log_scales": log_scales,
        "scales": scales,
        "scale_max": scale_max,
        "scale_ratio": scale_ratio,
        "quaternions": quaternions,
        "quaternion_norms": quaternion_norms,
        "alpha": alpha,
        "finite": finite,
    }


def projected_spike_analysis(
    arrays: dict[str, np.ndarray],
    cameras: np.ndarray,
    camera_meta: dict[str, Any],
    alpha_threshold: float,
    ratio_threshold: float,
    frame_fraction: float,
) -> tuple[np.ndarray, dict[str, Any]]:
    xyz = arrays["xyz"]
    eligible = (
        arrays["finite"]
        & (arrays["alpha"] > alpha_threshold)
        & (arrays["scale_ratio"] > ratio_threshold)
    )
    eligible_indices = np.flatnonzero(eligible)
    flagged = np.zeros(len(xyz), dtype=bool)
    per_camera: list[dict[str, int]] = []
    height = int(camera_meta["height"])
    width = int(camera_meta["width"])
    focal_y = height / (
        2.0 * math.tan(math.radians(camera_meta["fovy_degrees"]) * 0.5)
    )
    tan_y = math.tan(
        math.radians(camera_meta["fovy_degrees"]) * 0.5
    )
    tan_x = tan_y * (width / height)
    threshold_pixels = frame_fraction * min(width, height)
    for index, camera in enumerate(cameras):
        local = (
            xyz[eligible_indices] - camera[:3, 3]
        ) @ camera[:3, :3]
        z = local[:, 2]
        radius_pixels = np.divide(
            3.0 * focal_y * arrays["scale_max"][eligible_indices],
            z,
            out=np.zeros_like(z),
            where=z > 1e-4,
        )
        in_front = z > 1e-4
        in_view = (
            in_front
            & (np.abs(local[:, 0]) <= z * tan_x)
            & (np.abs(local[:, 1]) <= z * tan_y)
        )
        camera_flagged = eligible_indices[
            in_view & (radius_pixels > threshold_pixels)
        ]
        flagged[camera_flagged] = True
        per_camera.append(
            {
                "camera_index": index,
                "projected_spikes": int(len(camera_flagged)),
            }
        )
    return flagged, {
        "eligible_high_alpha_high_ratio": int(eligible.sum()),
        "unique_projected_spikes": int(flagged.sum()),
        "threshold_pixels": float(threshold_pixels),
        "per_camera": per_camera,
    }


def projected_spike_counts(
    arrays: dict[str, np.ndarray],
    cameras: np.ndarray,
    camera_meta: dict[str, Any],
    alpha_threshold: float,
    ratio_threshold: float,
    frame_fraction: float,
) -> dict[str, Any]:
    return projected_spike_analysis(
        arrays,
        cameras,
        camera_meta,
        alpha_threshold,
        ratio_threshold,
        frame_fraction,
    )[1]


def write_records(
    source: VertexPly,
    records: np.ndarray,
    path: Path,
    comment: str,
) -> None:
    header = [
        "ply",
        "format binary_little_endian 1.0",
        *source.comments,
        f"comment {comment}",
        f"element vertex {len(records)}",
        *(f"property {kind} {name}" for kind, name in source.properties),
        "end_header",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        handle.write(("\n".join(header) + "\n").encode("ascii"))
        records.tofile(handle)


def sanitize(
    source: VertexPly,
    arrays: dict[str, np.ndarray],
    cameras: np.ndarray,
    camera_meta: dict[str, Any],
    robust_radius_quantile: float,
    frustum_margin: float,
    spike_alpha: float,
    spike_ratio: float,
    spike_frame_fraction: float,
) -> tuple[np.ndarray, dict[str, Any]]:
    finite = arrays["finite"]
    finite_xyz = arrays["xyz"][finite]
    if not len(finite_xyz):
        raise RuntimeError("PLY has no finite Gaussian records")
    center = np.median(finite_xyz, axis=0)
    radius = np.linalg.norm(finite_xyz - center, axis=1)
    robust_radius = float(np.quantile(radius, robust_radius_quantile))
    all_radius = np.linalg.norm(arrays["xyz"] - center, axis=1)
    outside = finite & (all_radius > robust_radius)
    outside_indices = np.flatnonzero(outside)
    outside_visible = camera_visibility(
        arrays["xyz"][outside_indices],
        cameras,
        float(camera_meta["fovy_degrees"]),
        float(camera_meta["width"]) / float(camera_meta["height"]),
        frustum_margin,
    )
    remove = ~finite
    remove[outside_indices[~outside_visible]] = True
    spike_mask, spike_report = projected_spike_analysis(
        arrays,
        cameras,
        camera_meta,
        spike_alpha,
        spike_ratio,
        spike_frame_fraction,
    )
    remove |= spike_mask
    kept = source.records[~remove].copy()
    quaternions = np.column_stack(
        [kept[f"rot_{index}"] for index in range(4)]
    ).astype(np.float64)
    norms = np.linalg.norm(quaternions, axis=1, keepdims=True)
    quaternions /= norms
    for index in range(4):
        kept[f"rot_{index}"] = quaternions[:, index].astype(np.float32)
    return kept, {
        "method": (
            "unit-quaternion normalization plus removal of non-finite records "
            "and robust-radius outliers invisible from all supplied cameras, "
            "plus high-alpha high-aspect projected streaks"
        ),
        "robust_radius_quantile": robust_radius_quantile,
        "robust_center": center.tolist(),
        "robust_radius": robust_radius,
        "frustum_margin": frustum_margin,
        "input": int(len(source.records)),
        "non_finite_removed": int((~finite).sum()),
        "outside_robust_radius": int(outside.sum()),
        "outside_but_visible_kept": int(outside_visible.sum()),
        "outside_and_invisible_removed": int((~outside_visible).sum()),
        "projected_streaks_removed": int(spike_mask.sum()),
        "projected_streak_definition": spike_report,
        "output": int(len(kept)),
        "scale_or_sh_values_modified": False,
    }


def load_optional(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def metric_values(payload: dict[str, Any] | None) -> dict[str, float] | None:
    if payload is None:
        return None
    source = payload.get("metrics", payload)
    result = {
        name: float(source[name])
        for name in ("psnr", "ssim", "lpips")
        if name in source and source[name] is not None
    }
    per_frame = source.get("per_frame") or payload.get("per_frame")
    if isinstance(per_frame, list) and per_frame:
        psnr = [
            float(item["psnr"])
            for item in per_frame
            if isinstance(item, dict) and "psnr" in item
        ]
        if psnr:
            result["psnr_p10"] = float(np.quantile(psnr, 0.10))
    return result


def gate(value: float | None, operation: str, threshold: float) -> bool:
    if value is None:
        return False
    if operation == "min":
        return value >= threshold
    return value <= threshold


def main() -> None:
    args = parse_args()
    if not 0.0 < args.robust_radius_quantile < 1.0:
        raise SystemExit("--robust-radius-quantile must be within (0, 1)")
    if args.frustum_margin < 1.0:
        raise SystemExit("--frustum-margin must be at least 1.0")
    source = read_ply(args.input)
    cameras, camera_meta = load_camera_path(args.camera_path)
    selected = canonical_indices(len(cameras), args.canonical_cameras)
    canonical = cameras[selected]
    arrays = gaussian_arrays(source.records)
    property_names = [name for _, name in source.properties]
    position_center = np.median(
        arrays["xyz"][arrays["finite"]],
        axis=0,
    )
    position_radius = np.linalg.norm(arrays["xyz"] - position_center, axis=1)
    spikes = projected_spike_counts(
        arrays,
        canonical,
        camera_meta,
        args.spike_alpha,
        args.spike_ratio,
        args.spike_frame_fraction,
    )
    health = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "input": {
            "path": str(args.input),
            "bytes": args.input.stat().st_size,
            "sha256": sha256(args.input),
        },
        "format": {
            "binary_little_endian": True,
            "properties": len(property_names),
            "graphdeco_sh3_exact_order": (
                property_names == GRAPHDECO_SH3_PROPERTIES
            ),
        },
        "gaussians": int(len(source.records)),
        "non_finite_records": int((~arrays["finite"]).sum()),
        "position_radius_quantiles": quantiles(position_radius),
        "alpha_quantiles": quantiles(arrays["alpha"]),
        "max_scale_quantiles": quantiles(arrays["scale_max"]),
        "scale_ratio_quantiles": quantiles(arrays["scale_ratio"]),
        "scale_ratio_counts": {
            "gt_100": int((arrays["scale_ratio"] > 100.0).sum()),
            "gt_1000": int((arrays["scale_ratio"] > 1_000.0).sum()),
            "gt_100000": int((arrays["scale_ratio"] > 100_000.0).sum()),
        },
        "quaternion_norm": {
            "quantiles": quantiles(arrays["quaternion_norms"]),
            "max_unit_deviation": float(
                np.max(np.abs(arrays["quaternion_norms"] - 1.0))
            ),
        },
        "projected_spikes": spikes,
    }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    camera_manifest = {
        "schema_version": 1,
        **camera_meta,
        "source_camera_count": int(len(cameras)),
        "canonical_indices": selected.tolist(),
        "camtoworlds": canonical.tolist(),
    }
    (args.output_dir / "camera-manifest.json").write_text(
        json.dumps(camera_manifest, indent=2) + "\n",
        encoding="utf-8",
    )
    (args.output_dir / "gaussian-health.json").write_text(
        json.dumps(health, indent=2) + "\n",
        encoding="utf-8",
    )

    clean_report = None
    if args.clean_output is not None:
        clean_records, clean_report = sanitize(
            source,
            arrays,
            cameras,
            camera_meta,
            args.robust_radius_quantile,
            args.frustum_margin,
            args.spike_alpha,
            args.spike_ratio,
            args.spike_frame_fraction,
        )
        write_records(
            source,
            clean_records,
            args.clean_output,
            "diagnostic preview cleanup; not a photo-grade training result",
        )
        clean_report["artifact"] = {
            "path": str(args.clean_output),
            "bytes": args.clean_output.stat().st_size,
            "sha256": sha256(args.clean_output),
        }
        (args.output_dir / "preview-clean-report.json").write_text(
            json.dumps(clean_report, indent=2) + "\n",
            encoding="utf-8",
        )

    metrics_payload = load_optional(args.metrics)
    parity_payload = load_optional(args.parity_metrics)
    viewer_payload = load_optional(args.viewer_review)
    experiment_config = load_optional(args.experiment_config)
    export_report = load_optional(args.export_report)
    metrics = metric_values(metrics_payload)
    parity = metric_values(parity_payload)
    viewer_passed = bool(
        viewer_payload
        and viewer_payload.get("status") == "passed"
        and viewer_payload.get("full_frame_streaks", 1) == 0
        and viewer_payload.get("floating_layers", 1) == 0
        and viewer_payload.get("transparent_holes", 1) == 0
        and viewer_payload.get("incorrect_autoframing", True) is False
    )
    gates = {
        "standard_graphdeco_sh3": health["format"]["graphdeco_sh3_exact_order"],
        "finite": health["non_finite_records"] == 0,
        "unit_quaternions": (
            health["quaternion_norm"]["max_unit_deviation"] <= 1e-4
        ),
        "no_projected_spikes": spikes["unique_projected_spikes"] == 0,
        "heldout_psnr": gate(
            metrics.get("psnr") if metrics else None,
            "min",
            32.0,
        ),
        "heldout_ssim": gate(
            metrics.get("ssim") if metrics else None,
            "min",
            0.965,
        ),
        "heldout_lpips": gate(
            metrics.get("lpips") if metrics else None,
            "max",
            0.060,
        ),
        "heldout_psnr_p10": gate(
            metrics.get("psnr_p10") if metrics else None,
            "min",
            28.0,
        ),
        "checkpoint_ply_psnr": gate(
            parity.get("psnr") if parity else None,
            "min",
            50.0,
        ),
        "checkpoint_ply_ssim": gate(
            parity.get("ssim") if parity else None,
            "min",
            0.999,
        ),
        "viewer_review": viewer_passed,
    }
    all_passed = all(gates.values())
    quality = {
        "schema_version": 1,
        "status": (
            "photo_grade_passed"
            if all_passed
            else "quality_target_not_met"
        ),
        "scene_hash": args.scene_hash,
        "resolution": args.resolution,
        "scope": (
            "captured cameras and bounded interpolated camera trajectory; "
            "not arbitrary unseen room viewpoints"
        ),
        "thresholds": {
            "heldout_psnr_min": 32.0,
            "heldout_ssim_min": 0.965,
            "heldout_lpips_max": 0.060,
            "heldout_psnr_p10_min": 28.0,
            "checkpoint_ply_psnr_min": 50.0,
            "checkpoint_ply_ssim_min": 0.999,
            "projected_spikes_max": 0,
            "quaternion_max_unit_deviation": 1e-4,
        },
        "gates": gates,
        "metrics": metrics,
        "checkpoint_ply_parity": parity,
        "viewer_review": viewer_payload,
        "experiment_config": experiment_config,
        "training_scale_ratio": {
            "checkpoint": (
                export_report.get("checkpoint_photo_quality")
                if export_report
                else None
            ),
            "final_ply_quantiles": health["scale_ratio_quantiles"],
            "final_ply_counts": health["scale_ratio_counts"],
        },
        "health_report": "gaussian-health.json",
        "camera_manifest": "camera-manifest.json",
        "preview_cleanup": clean_report,
        "human_visual_approval_required": True,
    }
    quality_path = args.output_dir / "quality-report.json"
    quality_path.write_text(
        json.dumps(quality, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    checksum_paths = [
        args.input,
        args.camera_path,
        args.output_dir / "camera-manifest.json",
        args.output_dir / "gaussian-health.json",
        quality_path,
    ]
    if args.clean_output is not None:
        checksum_paths.extend(
            [
                args.clean_output,
                args.output_dir / "preview-clean-report.json",
            ]
        )
    checksum_lines = [
        f"{sha256(path)}  {path.name}"
        for path in checksum_paths
        if path.is_file()
    ]
    (args.output_dir / "CHECKSUMS.sha256").write_text(
        "\n".join(checksum_lines) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(quality, ensure_ascii=False))


if __name__ == "__main__":
    main()
