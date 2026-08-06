"""Shared point-cloud prediction plumbing for the VGGT frontend.

`save_prediction` writes the deployment deliverable (``pointcloud.ply``), the
raw frontend prediction (``<model>_prediction.npz``), and ``metrics.json``
from a `PointCloudPrediction`; `create_pointcloud_stage` builds the VGGT
frontend. The exported PLY is what downstream measurements and meshes
consume.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from sparse_view_plant.config import PointCloudConfig
from sparse_view_plant.export import write_json, write_point_cloud_ply
from sparse_view_plant.foreground import grid_trim_mask
from sparse_view_plant.images import InputImage
from sparse_view_plant.plant_fusion import (
    conflict_aware_budget_indices,
    estimate_pointmap_intrinsics,
    front_conflict_counts,
)


def _import_torch() -> Any:
    try:
        import torch
    except ImportError as error:
        raise RuntimeError(
            "torch is required for point-cloud fusion; install it with "
            "`uv sync --extra gpu`"
        ) from error
    return torch


@dataclass(frozen=True, slots=True)
class PointCloudPrediction:
    """Fused per-view pointmaps in a shared world frame."""

    view_ids: tuple[str, ...]
    points: np.ndarray  # (M, 3) float32
    colors: np.ndarray  # (M, 3) float32 in [0, 1]
    confidence: np.ndarray  # (M,) float32 in [0, 1]
    camera_to_world: np.ndarray  # (V, 4, 4) float32
    metric_scale: float
    image_sizes: tuple[tuple[int, int], ...]  # original (H, W) per view
    local_points: np.ndarray | None = None  # (M, 3) per-view camera-space points
    patch_hw: tuple[int, int] | None = None  # model output grid (H, W)


def save_prediction(
    prediction: PointCloudPrediction,
    output_dir: str | Path,
    *,
    confidence_percentile: float = 20.0,
    foreground_center_radius: float | None = None,
    foreground_confidence_percentile: float = 40.0,
    foreground_provider: str = "maskfree",
    plant_fusion_budget_fraction: float = 1.0,
    foreground_images: Sequence[InputImage] | None = None,
    device: str = "cuda",
    model_name: str = "vggt",
) -> dict[str, Path]:
    """Write pointcloud.ply, raw .npz, and metrics.json.

    The exported PLY is the deployment deliverable: with the default
    ``foreground_provider="maskfree"`` a mask-free foreground extraction
    (per-view confidence quantile + central-region prior, enabled when
    ``foreground_center_radius`` is given) keeps the plant and drops
    background pixels (pots, tabletops, walls) so that downstream
    measurements and meshes describe the plant, not the scene; with
    ``foreground_provider="birefnet"`` the salient-foreground mask replaces
    the heuristic (no confidence cut; ``foreground_images`` required).  A
    ``plant_fusion_budget_fraction`` below one keeps a fixed fraction of that
    mask by fewest cross-view front conflicts, then highest confidence.
    The raw prediction (``<model_name>_prediction.npz``) is always written
    unfiltered so evaluation protocols that use GT masks keep working.
    """
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    points = prediction.points
    colors = prediction.colors
    confidence = prediction.confidence
    if not 0.0 < plant_fusion_budget_fraction <= 1.0:
        raise ValueError("plant fusion budget fraction must be in (0, 1]")
    if plant_fusion_budget_fraction < 1.0 and foreground_provider != "birefnet":
        raise ValueError("plant fusion fixed budgets require birefnet foreground")
    fusion_stats: dict[str, Any] | None = None
    if foreground_provider not in ("maskfree", "birefnet"):
        raise ValueError(
            f"unknown pointcloud foreground provider: {foreground_provider}"
        )
    keep_confidence_fraction = 1.0 - confidence_percentile / 100.0
    if foreground_provider == "birefnet":
        if foreground_images is None:
            raise ValueError("birefnet foreground provider needs foreground_images")
        if prediction.patch_hw is None:
            raise ValueError("birefnet foreground provider needs patch_hw")
        mask = grid_trim_mask(
            "birefnet",
            foreground_images,
            patch_hw=prediction.patch_hw,
            device=device,
        )
        if plant_fusion_budget_fraction < 1.0:
            points, colors, confidence, fusion_stats = (
                extract_conflict_budget_foreground(
                    prediction,
                    mask,
                    keep_fraction=plant_fusion_budget_fraction,
                    device=device,
                )
            )
        else:
            points, colors, confidence = extract_masked_foreground(prediction, mask)
        # BiRefNet is the foreground; the global confidence cut is part of
        # the maskfree heuristic and only removes genuine surface there.
        keep_confidence_fraction = None
    elif foreground_center_radius is not None:
        points, colors, confidence = extract_deployed_foreground(
            prediction,
            center_radius=foreground_center_radius,
            confidence_percentile=foreground_confidence_percentile,
        )
    stats = write_point_cloud_ply(
        root / "pointcloud.ply",
        points,
        colors=colors,
        confidence=confidence,
        keep_confidence_fraction=keep_confidence_fraction,
    )
    payload: dict[str, Any] = {
        "view_ids": np.asarray(prediction.view_ids),
        "points": prediction.points,
        "colors": prediction.colors,
        "confidence": prediction.confidence,
        "camera_to_world": prediction.camera_to_world,
        "metric_scale": np.asarray(prediction.metric_scale),
        "image_sizes": np.asarray(prediction.image_sizes),
    }
    if prediction.local_points is not None:
        payload["local_points"] = prediction.local_points
    if prediction.patch_hw is not None:
        payload["patch_hw"] = np.asarray(prediction.patch_hw)
    np.savez(root / f"{model_name}_prediction.npz", **payload)
    write_json(
        root / "metrics.json",
        {
            "model": model_name,
            "view_count": len(prediction.view_ids),
            "view_ids": list(prediction.view_ids),
            "metric_scale": prediction.metric_scale,
            "input_points": int(prediction.points.shape[0]),
            "kept_points": int(stats["points"]),
            "confidence_percentile": confidence_percentile,
            "foreground_center_radius": foreground_center_radius,
            "foreground_confidence_percentile": foreground_confidence_percentile,
            "foreground_provider": foreground_provider,
            "plant_fusion_budget_fraction": plant_fusion_budget_fraction,
            "plant_fusion": fusion_stats,
            "mean_confidence": float(prediction.confidence.mean()),
        },
    )
    return {
        "pointcloud": root / "pointcloud.ply",
        "raw": root / f"{model_name}_prediction.npz",
        "metrics": root / "metrics.json",
    }


def create_pointcloud_stage(config: PointCloudConfig):
    """Instantiate the VGGT feed-forward point-cloud frontend."""
    from sparse_view_plant.pointcloud_vggt import VGGTStage

    return VGGTStage(config)


def find_prediction_npz(directory: str | Path) -> Path | None:
    """Locate the raw frontend prediction npz in an output directory.

    The filename is derived from the frontend model name
    (``vggt_prediction.npz``, ...); the first match in sorted order wins.
    """
    root = Path(directory)
    candidates = sorted(root.glob("*_prediction.npz"))
    return candidates[0] if candidates else None


def extract_deployed_foreground(
    prediction: PointCloudPrediction,
    *,
    center_radius: float,
    confidence_percentile: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Mask-free foreground extraction for the deployed point cloud.

    Keeps pixels whose per-view confidence is at or above the
    ``confidence_percentile`` quantile AND that lie inside a central
    ellipse of ``center_radius`` (fraction of the half-image). This
    encodes the common phenotyping assumption that the plant is centered
    in the frame; frontend confidence already separates it from uniform
    backgrounds, and the ellipse drops peripheral clutter. A
    ``center_radius`` >= sqrt(2) keeps the whole image (confidence cut
    only). Returns (points, colors, confidence) subsets.
    """
    if not 0.0 <= confidence_percentile < 100.0:
        raise ValueError("confidence percentile must be in [0, 100)")
    if prediction.patch_hw is None:
        raise ValueError("patch_hw is required for deployed foreground extraction")
    grid_h, grid_w = prediction.patch_hw
    view_count = len(prediction.view_ids)
    total = prediction.points.shape[0]
    if total % view_count != 0:
        raise ValueError("flattened point count is not divisible by the view count")
    per_view = total // view_count
    if per_view != grid_h * grid_w:
        raise ValueError("patch_hw does not match the flattened point count")
    points = np.asarray(prediction.points, dtype=np.float64).reshape(
        view_count, grid_h, grid_w, 3
    )
    colors = np.asarray(prediction.colors, dtype=np.float64).reshape(
        view_count, grid_h, grid_w, 3
    )
    confidence = np.asarray(prediction.confidence, dtype=np.float64).reshape(
        view_count, grid_h, grid_w
    )
    yy, xx = np.mgrid[0:grid_h, 0:grid_w]
    centre = ((xx - grid_w / 2.0) / (grid_w / 2.0)) ** 2 + (
        (yy - grid_h / 2.0) / (grid_h / 2.0)
    ) ** 2
    keep = np.ones((view_count, grid_h, grid_w), dtype=bool)
    keep &= centre[None] <= center_radius**2
    thresholds = np.percentile(
        confidence, 100.0 - confidence_percentile, axis=(1, 2), keepdims=True
    )
    keep &= confidence >= thresholds
    keep &= np.isfinite(points).all(axis=-1)
    keep &= np.isfinite(confidence)
    return points[keep], colors[keep], confidence[keep]


def extract_masked_foreground(
    prediction: PointCloudPrediction,
    grid_mask: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Keep the per-view grid cells selected by a binary mask (e.g. BiRefNet
    salient foreground), mirroring `extract_deployed_foreground`'s contract.

    `grid_mask` has shape ``(view_count, grid_h, grid_w)``; unlike the
    center-ellipse heuristic it is not combined with a confidence quantile
    (BiRefNet already separates foreground from background). Returns
    (points, colors, confidence) subsets.
    """
    if prediction.patch_hw is None:
        raise ValueError("patch_hw is required for masked foreground extraction")
    grid_h, grid_w = prediction.patch_hw
    view_count = len(prediction.view_ids)
    total = prediction.points.shape[0]
    if total % view_count != 0:
        raise ValueError("flattened point count is not divisible by the view count")
    per_view = total // view_count
    if per_view != grid_h * grid_w:
        raise ValueError("patch_hw does not match the flattened point count")
    mask = np.asarray(grid_mask, dtype=bool)
    if mask.shape != (view_count, grid_h, grid_w):
        raise ValueError(
            f"grid_mask must have shape {(view_count, grid_h, grid_w)}, "
            f"got {mask.shape}"
        )
    points = np.asarray(prediction.points, dtype=np.float64).reshape(
        view_count, grid_h, grid_w, 3
    )
    colors = np.asarray(prediction.colors, dtype=np.float64).reshape(
        view_count, grid_h, grid_w, 3
    )
    confidence = np.asarray(prediction.confidence, dtype=np.float64).reshape(
        view_count, grid_h, grid_w
    )
    keep = mask.copy()
    keep &= np.isfinite(points).all(axis=-1)
    keep &= np.isfinite(confidence)
    return points[keep], colors[keep], confidence[keep]


def extract_conflict_budget_foreground(
    prediction: PointCloudPrediction,
    grid_mask: np.ndarray,
    *,
    keep_fraction: float,
    device: str,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict[str, Any]]:
    """Select a BiRefNet foreground budget using cross-view front conflicts."""
    if prediction.patch_hw is None or prediction.local_points is None:
        raise ValueError("plant fusion needs patch_hw and local_points")
    grid_h, grid_w = prediction.patch_hw
    view_count = len(prediction.view_ids)
    per_view = grid_h * grid_w
    if len(prediction.points) != view_count * per_view:
        raise ValueError("patch_hw does not match the flattened point count")
    mask = np.asarray(grid_mask, dtype=bool)
    if mask.shape != (view_count, grid_h, grid_w):
        raise ValueError(
            f"grid_mask must have shape {(view_count, grid_h, grid_w)}, got {mask.shape}"
        )
    finite = np.isfinite(prediction.points).all(axis=1) & np.isfinite(
        prediction.confidence
    )
    candidate_indices = np.flatnonzero(mask.reshape(-1) & finite)
    if len(candidate_indices) == 0:
        raise ValueError("plant fusion foreground is empty")
    candidates = prediction.points[candidate_indices]
    diagonal = float(np.linalg.norm(np.ptp(candidates, axis=0)))
    if not np.isfinite(diagonal) or diagonal <= 0.0:
        raise ValueError("plant fusion foreground has invalid scale")
    torch = _import_torch()
    target_device = torch.device(device)
    local = prediction.local_points.reshape(view_count, grid_h, grid_w, 3)
    intrinsics = estimate_pointmap_intrinsics(
        prediction.local_points, prediction.patch_hw
    )
    conflicts = (
        front_conflict_counts(
            torch.from_numpy(candidates.astype(np.float32)).to(target_device),
            torch.from_numpy((candidate_indices // per_view).astype(np.int64)).to(
                target_device
            ),
            torch.from_numpy(prediction.camera_to_world.astype(np.float32)).to(
                target_device
            ),
            torch.from_numpy(intrinsics).to(target_device),
            torch.from_numpy(mask.astype(np.float32)).to(target_device),
            torch.from_numpy(local[..., 2].astype(np.float32)).to(target_device),
            depth_tolerance=0.01 * diagonal,
        )
        .cpu()
        .numpy()
    )
    selected_local = conflict_aware_budget_indices(
        prediction.confidence[candidate_indices], conflicts, keep_fraction
    )
    selected = candidate_indices[selected_local]
    stats: dict[str, Any] = {
        "candidates": len(candidate_indices),
        "selected": len(selected),
        "depth_tolerance": 0.01 * diagonal,
        "conflict_histogram": {
            str(value): int((conflicts == value).sum())
            for value in np.unique(conflicts)
        },
    }
    return (
        prediction.points[selected],
        prediction.colors[selected],
        prediction.confidence[selected],
        stats,
    )
