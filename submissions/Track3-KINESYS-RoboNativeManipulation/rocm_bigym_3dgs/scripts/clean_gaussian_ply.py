#!/usr/bin/env python3
"""Create a non-destructive, auditable cleaned copy of a Gaussian PLY."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
from plyfile import PlyData, PlyElement


def vector3(value: str) -> np.ndarray:
    parts = [float(part) for part in value.split(",")]
    if len(parts) != 3 or not all(math.isfinite(part) for part in parts):
        raise argparse.ArgumentTypeError("expected three finite comma-separated values")
    return np.asarray(parts, dtype=np.float32)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--bbox-min", type=vector3, required=True)
    parser.add_argument("--bbox-max", type=vector3, required=True)
    parser.add_argument("--max-radius", type=float)
    parser.add_argument("--max-world-scale", type=float, default=1.5)
    parser.add_argument("--min-alpha", type=float, default=0.0)
    parser.add_argument("--selection-note", required=True)
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    args = parse_args()
    if np.any(args.bbox_min >= args.bbox_max):
        raise ValueError("every bbox minimum must be smaller than its maximum")
    if args.max_world_scale <= 0:
        raise ValueError("--max-world-scale must be positive")
    if args.max_radius is not None and args.max_radius <= 0:
        raise ValueError("--max-radius must be positive")
    if not 0.0 <= args.min_alpha < 1.0:
        raise ValueError("--min-alpha must be in [0, 1)")
    if args.output.resolve() == args.input.resolve():
        raise ValueError("cleaned output must not overwrite the original PLY")

    source = PlyData.read(args.input, mmap=True)
    vertices = source["vertex"].data
    names = set(vertices.dtype.names or ())
    required = {
        "x",
        "y",
        "z",
        "opacity",
        "scale_0",
        "scale_1",
        "scale_2",
    }
    missing = sorted(required - names)
    if missing:
        raise RuntimeError(f"input lacks required Gaussian properties: {missing}")

    xyz = np.column_stack([vertices[name] for name in ("x", "y", "z")])
    log_scales = np.column_stack([vertices[f"scale_{index}"] for index in range(3)])
    world_scale = np.exp(np.max(log_scales, axis=1))
    alpha = 1.0 / (1.0 + np.exp(-np.clip(vertices["opacity"], -50.0, 50.0)))

    finite = np.isfinite(xyz).all(axis=1) & np.isfinite(world_scale) & np.isfinite(alpha)
    in_bounds = ((xyz >= args.bbox_min) & (xyz <= args.bbox_max)).all(axis=1)
    in_radius = np.ones(len(vertices), dtype=bool)
    if args.max_radius is not None:
        in_radius = np.linalg.norm(xyz, axis=1) <= args.max_radius
    not_oversized = world_scale <= args.max_world_scale
    visible = alpha >= args.min_alpha
    keep = finite & in_bounds & in_radius & not_oversized & visible

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    cleaned = np.asarray(vertices[keep]).copy()
    PlyData(
        [PlyElement.describe(cleaned, "vertex")],
        text=False,
        byte_order="<",
        comments=list(source.comments),
        obj_info=list(source.obj_info),
    ).write(args.output)

    outside = finite & ~in_bounds
    outside_radius = finite & in_bounds & ~in_radius
    retained_region = finite & in_bounds & in_radius
    oversized = retained_region & ~not_oversized
    low_alpha = retained_region & not_oversized & ~visible
    nonfinite = ~finite
    manifest = {
        "status": "cleaned_copy_created",
        "method": "manual_bbox_plus_obvious_outlier_filters",
        "selection_note": args.selection_note,
        "input": {
            "path": str(args.input),
            "bytes": args.input.stat().st_size,
            "sha256": sha256(args.input),
            "gaussians": int(len(vertices)),
        },
        "selection": {
            "bbox_min": args.bbox_min.tolist(),
            "bbox_max": args.bbox_max.tolist(),
            "max_radius": args.max_radius,
            "max_world_scale": args.max_world_scale,
            "min_alpha": args.min_alpha,
        },
        "removed": {
            "outside_manual_bbox": int(outside.sum()),
            "outside_max_radius_inside_bbox": int(outside_radius.sum()),
            "oversized_inside_bbox": int(oversized.sum()),
            "below_min_alpha_inside_bbox": int(low_alpha.sum()),
            "nonfinite": int(nonfinite.sum()),
            "total": int((~keep).sum()),
        },
        "output": {
            "path": str(args.output),
            "bytes": args.output.stat().st_size,
            "sha256": sha256(args.output),
            "gaussians": int(keep.sum()),
        },
    }
    args.manifest.write_text(json.dumps(manifest, indent=2))
    print(json.dumps(manifest))


if __name__ == "__main__":
    main()
