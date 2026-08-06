"""Plant-specific visibility evidence for fixed-budget frontend point clouds.

The frozen frontend's point maps are correlated predictions, so their
coordinates must not be averaged as if they were independent MVS samples.
What transfers reliably is negative evidence: a point that repeatedly floats
in front of another view's predicted plant surface is a poor use of a limited
point budget.  This module computes that evidence and ranks points without
changing their coordinates.
"""

from __future__ import annotations

import numpy as np
import torch
from torch.nn import functional as F


def estimate_pointmap_intrinsics(
    local_points: np.ndarray, patch_hw: tuple[int, int]
) -> np.ndarray:
    """Recover pinhole intrinsics from local point-map pixel correspondences."""
    points = np.asarray(local_points, dtype=np.float64).reshape(
        -1, patch_hw[0], patch_hw[1], 3
    )
    yy, xx = np.meshgrid(
        np.arange(patch_hw[0], dtype=np.float64),
        np.arange(patch_hw[1], dtype=np.float64),
        indexing="ij",
    )
    matrices: list[np.ndarray] = []
    for view in points:
        z = view[..., 2]
        valid = np.isfinite(view).all(axis=-1) & (np.abs(z) > 1e-6)
        if valid.sum() < 4:
            raise ValueError("local point map has too few valid points")
        fx, cx = np.linalg.lstsq(
            np.stack([view[..., 0][valid] / z[valid], np.ones(valid.sum())], axis=1),
            xx[valid],
            rcond=None,
        )[0]
        fy, cy = np.linalg.lstsq(
            np.stack([view[..., 1][valid] / z[valid], np.ones(valid.sum())], axis=1),
            yy[valid],
            rcond=None,
        )[0]
        matrices.append(np.asarray([[fx, 0.0, cx], [0.0, fy, cy], [0.0, 0.0, 1.0]]))
    return np.stack(matrices).astype(np.float32)


def front_conflict_counts(
    points: torch.Tensor,
    source_view: torch.Tensor,
    camera_to_world: torch.Tensor,
    intrinsics: torch.Tensor,
    masks: torch.Tensor,
    observed_depth: torch.Tensor,
    *,
    depth_tolerance: float,
    chunk_size: int = 100_000,
) -> torch.Tensor:
    """Count non-source views in which each point floats before the surface.

    All coordinates and ``depth_tolerance`` use the frontend's world scale.
    Points behind the sampled surface are treated as ordinary occlusions and
    are not penalized.  The returned tensor is int16 on the input device.
    """
    if points.ndim != 2 or points.shape[1] != 3:
        raise ValueError("points must have shape [N, 3]")
    if source_view.shape != (len(points),):
        raise ValueError("source_view must have shape [N]")
    if not depth_tolerance > 0.0:
        raise ValueError("depth_tolerance must be positive")
    view_count, height, width = masks.shape
    output = torch.empty(len(points), dtype=torch.int16, device=points.device)
    for start in range(0, len(points), chunk_size):
        stop = min(start + chunk_size, len(points))
        chunk = points[start:stop]
        sources = source_view[start:stop]
        conflicts = torch.zeros(len(chunk), dtype=torch.int16, device=points.device)
        for view_index in range(view_count):
            rotation = camera_to_world[view_index, :3, :3]
            translation = camera_to_world[view_index, :3, 3]
            camera = (chunk - translation) @ rotation
            z = camera[:, 2]
            safe_z = z.clamp_min(1e-6)
            matrix = intrinsics[view_index]
            u = matrix[0, 0] * camera[:, 0] / safe_z + matrix[0, 2]
            v = matrix[1, 1] * camera[:, 1] / safe_z + matrix[1, 2]
            inside = (z > 0) & (u >= 0) & (u < width) & (v >= 0) & (v < height)
            grid = torch.stack(
                [
                    2.0 * (u + 0.5) / width - 1.0,
                    2.0 * (v + 0.5) / height - 1.0,
                ],
                dim=1,
            )[None, :, None]
            sampled_mask = F.grid_sample(
                masks[view_index][None, None],
                grid,
                mode="bilinear",
                padding_mode="zeros",
                align_corners=False,
            )[0, 0, :, 0]
            sampled_depth = F.grid_sample(
                observed_depth[view_index][None, None],
                grid,
                mode="bilinear",
                padding_mode="border",
                align_corners=False,
            )[0, 0, :, 0]
            conflict = (
                (sources != view_index)
                & inside
                & (sampled_mask >= 0.5)
                & (sampled_depth > 0)
                & ((sampled_depth - z) > depth_tolerance)
            )
            conflicts += conflict.to(torch.int16)
        output[start:stop] = conflicts
    return output


def conflict_aware_budget_indices(
    confidence: np.ndarray,
    conflict_count: np.ndarray,
    keep_fraction: float,
) -> np.ndarray:
    """Select a fixed budget by fewest conflicts, then highest confidence."""
    scores = np.asarray(confidence).reshape(-1)
    conflicts = np.asarray(conflict_count).reshape(-1)
    if len(scores) != len(conflicts):
        raise ValueError("confidence and conflict_count must have equal length")
    if not 0.0 < keep_fraction <= 1.0:
        raise ValueError("keep_fraction must be in (0, 1]")
    count = max(1, round(len(scores) * keep_fraction))
    # np.lexsort uses the last key as primary: fewer conflicts first, with
    # confidence descending inside each evidence tier.
    order = np.lexsort((-scores, conflicts))
    return np.sort(order[:count])
