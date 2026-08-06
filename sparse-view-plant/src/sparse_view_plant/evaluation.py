"""Geometry metrics and Sim3 alignment for pipeline output evaluation.

The metric semantics mirror `few-view-plant`'s evaluation protocol (so results
are comparable with the numbers in the design doc): the reference point cloud
is voxel-downsampled and capped at 100k points, Chamfer-L1 is the mean of the
two nearest-neighbour distance summaries, and all distances are normalized by
the reference diagonal. Only numpy / scipy / plyfile are used.

Alignment:
- Predictions with per-view cameras are aligned to the GT cameras with
  a camera-center Sim3 fit, exactly like the upstream protocol.
- Gaussian means have no shared camera frame, so they are aligned with a
  coarse-to-fine ICP: centroid + diagonal scaling initialization, then
  nearest-neighbour correspondence + Sim3 refits. This is optimistic for
  geometry quality and is reported as such in the output.
"""

from __future__ import annotations

import itertools
import json
import math
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image
from plyfile import PlyData
from scipy.spatial import KDTree

METRIC_POINT_CAP = 100_000
VOXEL_FRACTION = 0.0025
METRIC_SEED = 0


def load_ply_points(path: str | Path) -> np.ndarray:
    """Load a PLY point cloud as float64 (N, 3) positions."""
    ply = PlyData.read(str(path))
    vertices = ply["vertex"]
    points = np.stack(
        [
            np.asarray(vertices["x"]),
            np.asarray(vertices["y"]),
            np.asarray(vertices["z"]),
        ],
        axis=1,
    )
    return _finite_points(points, name=str(path))


def _finite_points(points: np.ndarray, *, name: str) -> np.ndarray:
    values = np.asarray(points)
    if values.ndim != 2 or values.shape[1] != 3:
        raise ValueError(f"{name} point cloud must have shape [N, 3]")
    finite = values[np.isfinite(values).all(axis=1)].astype(np.float64, copy=False)
    if len(finite) == 0:
        raise ValueError(f"{name} point cloud is empty")
    return finite


def voxel_downsample(points: np.ndarray, voxel_size: float) -> np.ndarray:
    """Grid-based downsample: keep the first point of every voxel cell."""
    finite = _finite_points(points, name="input")
    if voxel_size <= 0.0:
        return finite
    order = np.lexsort((finite[:, 2], finite[:, 1], finite[:, 0]))
    ordered = finite[order]
    cells = np.floor(ordered / voxel_size).astype(np.int64)
    keep = np.ones(len(ordered), dtype=bool)
    keep[1:] = np.any(cells[1:] != cells[:-1], axis=1)
    return ordered[keep]


def sample_points(points: np.ndarray, *, maximum: int, seed: int) -> np.ndarray:
    finite = _finite_points(points, name="input")
    if len(finite) <= maximum:
        return finite
    generator = np.random.Generator(np.random.PCG64(seed))
    indices = generator.choice(len(finite), maximum, replace=False)
    return finite[np.sort(indices)]


@dataclass(frozen=True, slots=True)
class ReferenceGeometry:
    points: np.ndarray
    tree: KDTree
    diagonal: float
    voxel_size: float
    center: np.ndarray


def build_reference(
    points: np.ndarray,
    *,
    seed: int = METRIC_SEED,
    voxel_fraction: float = VOXEL_FRACTION,
    maximum: int = METRIC_POINT_CAP,
) -> ReferenceGeometry:
    finite = _finite_points(points, name="reference")
    diagonal = float(np.linalg.norm(finite.max(axis=0) - finite.min(axis=0)))
    if not math.isfinite(diagonal) or diagonal <= 0.0:
        raise ValueError("reference point cloud has zero diagonal")
    voxel_size = diagonal * voxel_fraction
    sampled = sample_points(
        voxel_downsample(finite, voxel_size), maximum=maximum, seed=seed
    )
    if len(sampled) == 0:
        raise ValueError("reference point cloud is empty after sampling")
    return ReferenceGeometry(
        points=sampled,
        tree=KDTree(sampled),
        diagonal=diagonal,
        voxel_size=voxel_size,
        center=np.median(sampled, axis=0),
    )


def _distance_summaries(
    prefix: str, distances: np.ndarray, diagonal: float
) -> dict[str, float]:
    result: dict[str, float] = {}
    for name, value in {
        "mean": float(np.mean(distances)),
        "median": float(np.median(distances)),
        "p90": float(np.percentile(distances, 90)),
        "p95": float(np.percentile(distances, 95)),
    }.items():
        result[f"{prefix}_{name}"] = value
        result[f"{prefix}_{name}_normalized"] = value / diagonal
    return result


def geometry_metrics(
    prediction: np.ndarray,
    reference: ReferenceGeometry,
    *,
    seed: int = METRIC_SEED,
    maximum: int = METRIC_POINT_CAP,
) -> dict[str, float | int]:
    """Chamfer-L1 / F-score summaries, normalized by the reference diagonal."""
    predicted = sample_points(
        voxel_downsample(prediction, reference.voxel_size),
        maximum=maximum,
        seed=seed,
    )
    if len(predicted) == 0:
        raise ValueError("prediction point cloud is empty")

    accuracy = reference.tree.query(predicted, workers=-1)[0]
    completeness = KDTree(predicted).query(reference.points, workers=-1)[0]
    result: dict[str, float | int] = {
        **_distance_summaries("accuracy", accuracy, reference.diagonal),
        **_distance_summaries("completeness", completeness, reference.diagonal),
    }
    chamfer = float((np.mean(accuracy) + np.mean(completeness)) / 2.0)
    result["chamfer_l1"] = chamfer
    result["chamfer_l1_normalized"] = chamfer / reference.diagonal

    for percent, label in ((0.5, "0p5pct"), (1.0, "1pct"), (2.0, "2pct")):
        threshold = percent / 100.0 * reference.diagonal
        precision = float(np.mean(accuracy <= threshold))
        recall = float(np.mean(completeness <= threshold))
        denominator = precision + recall
        result[f"precision_{label}"] = precision
        result[f"recall_{label}"] = recall
        result[f"fscore_{label}"] = (
            2.0 * precision * recall / denominator if denominator > 0.0 else 0.0
        )
    result["center_offset"] = float(
        np.linalg.norm(np.median(predicted, axis=0) - reference.center)
    )
    result["center_offset_normalized"] = result["center_offset"] / reference.diagonal
    result["prediction_metric_points"] = len(predicted)
    result["reference_metric_points"] = len(reference.points)
    return result


def estimate_sim3(source: np.ndarray, destination: np.ndarray) -> np.ndarray:
    """Sim3 (scale * rotation + translation) fitting source centers onto
    destinations (corresponding rows), via the Umeyama SVD formulation used by
    few-view-plant's camera alignment."""
    src = np.asarray(source, dtype=np.float64)
    dst = np.asarray(destination, dtype=np.float64)
    if src.shape != dst.shape or src.shape[1] != 3 or len(src) < 3:
        raise ValueError("Sim3 requires matching [N, 3] arrays with N >= 3")

    src_centered = src - src.mean(axis=0)
    dst_centered = dst - dst.mean(axis=0)
    if (
        np.linalg.matrix_rank(src_centered) < 2
        or np.linalg.matrix_rank(dst_centered) < 2
    ):
        raise ValueError("Sim3 requires at least three non-collinear points")

    covariance = dst_centered.T @ src_centered / len(src)
    left, singular_values, right_transpose = np.linalg.svd(covariance)
    correction = np.eye(3, dtype=np.float64)
    if np.linalg.det(left @ right_transpose) < 0:
        correction[-1, -1] = -1.0
    rotation = left @ correction @ right_transpose

    src_variance = float(np.sum(src_centered**2) / len(src))
    if src_variance <= 1e-12:
        raise ValueError("source points have negligible variance")
    scale = float(np.sum(singular_values * np.diag(correction)) / src_variance)
    if not math.isfinite(scale) or scale <= 0.0:
        raise ValueError("Sim3 produced a non-positive scale")
    translation = dst.mean(axis=0) - scale * (rotation @ src.mean(axis=0))

    matrix = np.eye(4, dtype=np.float64)
    matrix[:3, :3] = scale * rotation
    matrix[:3, 3] = translation
    return matrix


def _estimate_rigid(source: np.ndarray, destination: np.ndarray) -> np.ndarray:
    """Rigid (unit-scale) rotation + translation fitting corresponding rows.

    Umeyama variant used when a cloud's scale relative to the reference is
    known in advance (e.g. pose-free Gaussians whose canonical frame has an
    arbitrary scale): the scale is held fixed so nearest-neighbour refinement
    cannot collapse the cloud onto a dense reference centre.
    """
    src = np.asarray(source, dtype=np.float64)
    dst = np.asarray(destination, dtype=np.float64)
    if src.shape != dst.shape or src.shape[1] != 3 or len(src) < 3:
        raise ValueError("rigid fit requires matching [N, 3] arrays with N >= 3")

    src_centered = src - src.mean(axis=0)
    dst_centered = dst - dst.mean(axis=0)
    if (
        np.linalg.matrix_rank(src_centered) < 2
        or np.linalg.matrix_rank(dst_centered) < 2
    ):
        raise ValueError("rigid fit requires at least three non-collinear points")

    covariance = dst_centered.T @ src_centered / len(src)
    left, _, right_transpose = np.linalg.svd(covariance)
    correction = np.eye(3, dtype=np.float64)
    if np.linalg.det(left @ right_transpose) < 0:
        correction[-1, -1] = -1.0
    rotation = left @ correction @ right_transpose
    translation = dst.mean(axis=0) - rotation @ src.mean(axis=0)

    matrix = np.eye(4, dtype=np.float64)
    matrix[:3, :3] = rotation
    matrix[:3, 3] = translation
    return matrix


def apply_sim3(points: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    values = np.asarray(points, dtype=np.float64)
    return values @ matrix[:3, :3].T + matrix[:3, 3]


@dataclass(frozen=True, slots=True)
class PointAlignment:
    matrix: np.ndarray
    residual: float


def align_points_icp(
    source: np.ndarray,
    destination: np.ndarray,
    *,
    seed: int = METRIC_SEED,
    fit_points: int = 20_000,
    iterations: int = 25,
    fixed_scale: bool = False,
) -> PointAlignment:
    """Coarse-to-fine Sim3 alignment of an unregistered point cloud.

    Two initializations are tried and the better one (by final residual) is
    kept: centroid + diagonal scaling, and a PCA rotation fit over all axis
    sign combinations. Both are refined with nearest-neighbour Sim3 refits.
    The residual is the final mean nearest-neighbour distance of the fitted
    sample in source units (lower is a better fit).

    With ``fixed_scale=True`` the scale from the bounding-box diagonal ratio
    is held constant during refinement and only rotation + translation are
    refit. This avoids the degenerate collapse that free-scale Umeyama
    refinement can produce when the reference cloud is much denser near its
    centre than the (arbitrarily scaled) source cloud.
    """
    src = _finite_points(source, name="source")
    dst = _finite_points(destination, name="destination")
    src_diagonal = float(np.linalg.norm(src.max(axis=0) - src.min(axis=0)))
    dst_diagonal = float(np.linalg.norm(dst.max(axis=0) - dst.min(axis=0)))
    if src_diagonal <= 0.0 or dst_diagonal <= 0.0:
        raise ValueError("alignment requires non-degenerate point clouds")

    scale = dst_diagonal / src_diagonal
    centroid_scale = np.eye(4, dtype=np.float64)
    centroid_scale[:3, :3] *= scale
    centroid_scale[:3, 3] = dst.mean(axis=0) - src.mean(axis=0) * scale

    def _refit(fit: np.ndarray, targets: np.ndarray) -> np.ndarray:
        if fixed_scale:
            return _estimate_rigid(fit, targets)
        return estimate_sim3(fit, targets)

    def _run(matrix: np.ndarray) -> tuple[np.ndarray, float]:
        aligned = apply_sim3(src, matrix)
        fit = sample_points(aligned, maximum=fit_points, seed=seed)
        tree = KDTree(dst)
        total = matrix.copy()
        for _ in range(iterations):
            _, indices = tree.query(fit, workers=-1)
            step = _refit(fit, dst[indices])
            aligned = apply_sim3(aligned, step)
            total = step @ total
            fit = apply_sim3(fit, step)
        residual = float(np.mean(tree.query(fit, workers=-1)[0]))
        return total, residual

    candidates: list[tuple[np.ndarray, float]] = [_run(centroid_scale)]

    # PCA rotation init: align principal axes, trying every sign assignment
    # and keeping the one with the smallest mean nearest-neighbour distance.
    _, _, right_transpose_src = np.linalg.svd(
        src - src.mean(axis=0), full_matrices=False
    )
    _, _, right_transpose_dst = np.linalg.svd(
        dst - dst.mean(axis=0), full_matrices=False
    )
    axes_src = right_transpose_src.T
    axes_dst = right_transpose_dst.T
    tree = KDTree(dst)
    best_rotation = None
    best_score = float("inf")
    for signs in itertools.product((1.0, -1.0), repeat=3):
        rotation = axes_dst @ (axes_src * np.asarray(signs)).T
        if np.linalg.det(rotation) < 0:
            rotation[:, 2] *= -1.0
        aligned = (src - src.mean(axis=0)) * scale @ rotation.T + dst.mean(axis=0)
        score = float(np.mean(tree.query(aligned, workers=-1)[0]))
        if score < best_score:
            best_score = score
            best_rotation = rotation
    pca_matrix = np.eye(4, dtype=np.float64)
    pca_matrix[:3, :3] = best_rotation
    pca_matrix[:3, 3] = dst.mean(axis=0) - best_rotation @ src.mean(axis=0)
    candidates.append(_run(pca_matrix))

    matrix, residual = min(candidates, key=lambda item: item[1])
    return PointAlignment(matrix=matrix, residual=residual)


def load_plantdreamer_gt(
    dataset_root: str | Path, scene: str
) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    """Load a PlantDreamer scene's curated reference point cloud and GT c2w.

    Returns (reference_points, {view_stem: camera_to_world}).
    """
    root = Path(dataset_root) / scene
    references = sorted((root / "data").glob("*_real_pointcloud.ply"))
    if len(references) != 1:
        raise ValueError(
            f"expected one *_real_pointcloud.ply in {root / 'data'}, "
            f"found {len(references)}"
        )
    points = load_ply_points(references[0])

    transforms_path = root / "transforms" / "original" / "transforms.json"
    if not transforms_path.is_file():
        raise ValueError(f"missing transforms file: {transforms_path}")
    document = json.loads(transforms_path.read_text())
    cameras: dict[str, np.ndarray] = {}
    for frame in document["frames"]:
        view_id = Path(frame["file_path"]).stem
        cameras[view_id] = np.asarray(frame["transform_matrix"], dtype=np.float64)
    return points, cameras


def load_plantdreamer_masks(
    dataset_root: str | Path, scene: str, view_ids: Sequence[str]
) -> dict[str, np.ndarray]:
    """Load binary foreground masks for the given views (few-view-plant layout:
    `<scene>/images/mask/<view_id>.png.png`, one byte per pixel)."""
    mask_dir = Path(dataset_root) / scene / "images" / "mask"
    masks: dict[str, np.ndarray] = {}
    for view_id in view_ids:
        path = mask_dir / f"{view_id}.png.png"
        if not path.is_file():
            raise ValueError(f"missing foreground mask for view {view_id}: {path}")
        image = Image.open(path).convert("L")
        masks[view_id] = np.asarray(image) >= 128
    return masks


def infer_patch_grid(flat_count: int, view_count: int) -> tuple[int, int]:
    """Recover the per-view (H, W) prediction grid from a flattened point array."""
    if view_count <= 0 or flat_count % view_count != 0:
        raise ValueError("flattened point count is not divisible by the view count")
    per_view = flat_count // view_count
    side = round(per_view**0.5)
    if side * side != per_view:
        raise ValueError(
            f"cannot infer a square prediction grid from {per_view} points per view; "
            "rerun the pipeline to persist the grid shape"
        )
    return side, side


def normalize_view_ids(values: Sequence[str] | None) -> list[str]:
    """Normalize pipeline `images` metadata to bare GT view ids.

    `run_pipeline.py` records image file names (e.g. ``0005_train.png``)
    while GT view ids are extension-less (``0005_train``); held-out view
    sampling must exclude both forms or conditioning views leak into the
    evaluation.
    """
    return [Path(str(value)).stem for value in (values or [])]


def replay_mask(mask: np.ndarray, target_hw: tuple[int, int]) -> np.ndarray:
    """Resize a binary mask to the model output grid with nearest-neighbour
    interpolation, matching few-view-plant's mask replay for full-frame crops."""
    target_h, target_w = target_hw
    resized = Image.fromarray(np.asarray(mask).astype(np.uint8) * 255, mode="L").resize(
        (target_w, target_h), Image.Resampling.NEAREST
    )
    return np.asarray(resized) >= 128


def depth_edge_mask(
    depth: np.ndarray, *, rtol: float, kernel_size: int = 3
) -> np.ndarray:
    """Mark pixels where the local depth range jumps relative to the center
    depth (occlusion boundaries), mirroring few-view-plant's filter."""
    values = np.asarray(depth)
    if values.ndim != 3 or kernel_size <= 0 or kernel_size % 2 == 0:
        raise ValueError("depth must have shape [V, H, W] and an odd kernel size")
    if not math.isfinite(rtol) or rtol < 0.0:
        raise ValueError("depth edge rtol must be finite and non-negative")
    pad = kernel_size // 2
    padded = np.pad(values, ((0, 0), (pad, pad), (pad, pad)), mode="edge")
    local_max = np.full_like(values, -np.inf)
    local_min = np.full_like(values, np.inf)
    for y_offset in range(kernel_size):
        for x_offset in range(kernel_size):
            window = padded[
                :,
                y_offset : y_offset + values.shape[1],
                x_offset : x_offset + values.shape[2],
            ]
            local_max = np.maximum(local_max, window)
            local_min = np.minimum(local_min, window)
    relative_jump = (local_max - local_min) / np.maximum(np.abs(values), 1e-6)
    return relative_jump > rtol


def camera_space_depth(
    world_grid: np.ndarray, camera_to_world: np.ndarray
) -> np.ndarray:
    """Per-view camera-space depth proxy from world points and predicted c2w.

    Uses the distance along the camera view axis (the c2w z column). The model
    also predicts local per-view depths; this fallback is used when they are
    not persisted, and is exact when the predicted poses match the pointmaps.
    """
    centers = np.asarray(camera_to_world, dtype=np.float64)[:, :3, 3]
    axes = np.asarray(camera_to_world, dtype=np.float64)[:, :3, 2]
    return np.einsum("nhwd,vd->nhw", world_grid - centers[:, None, None, :], axes)


def extract_foreground(
    points_flat: np.ndarray,
    confidence_flat: np.ndarray,
    *,
    colors_flat: np.ndarray | None = None,
    view_ids: Sequence[str],
    camera_to_world: np.ndarray,
    masks: dict[str, np.ndarray],
    patch_hw: tuple[int, int],
    confidence_percentile: float = 20.0,
    depth_edge_rtol: float = 0.03,
    local_depth: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray | None]:
    """Replicate few-view-plant's foreground protocol: GT mask replay, finite
    checks, depth-edge removal, and a confidence percentile cut. Returns
    (points, colors) with colors in [0, 1] when `colors_flat` is provided."""
    grid_h, grid_w = patch_hw
    view_count = len(view_ids)
    world = np.asarray(points_flat, dtype=np.float64).reshape(
        view_count, grid_h, grid_w, 3
    )
    colors = (
        np.asarray(colors_flat, dtype=np.float64).reshape(view_count, grid_h, grid_w, 3)
        if colors_flat is not None
        else None
    )
    confidence = np.asarray(confidence_flat, dtype=np.float64).reshape(
        view_count, grid_h, grid_w
    )
    depth = (
        np.asarray(local_depth, dtype=np.float64).reshape(view_count, grid_h, grid_w)
        if local_depth is not None
        else camera_space_depth(world, camera_to_world)
    )

    keep = np.zeros((view_count, grid_h, grid_w), dtype=bool)
    for index, view_id in enumerate(view_ids):
        keep[index] = replay_mask(masks[view_id], patch_hw)
    valid = keep & np.isfinite(world).all(axis=-1)
    valid &= np.isfinite(depth)
    valid &= np.isfinite(confidence)
    valid &= confidence > 1e-5
    valid &= ~depth_edge_mask(depth, rtol=depth_edge_rtol)
    if not 0.0 <= confidence_percentile < 100.0:
        raise ValueError("confidence percentile must be in [0, 100)")
    threshold = float(np.percentile(confidence[valid], confidence_percentile))
    valid &= confidence >= threshold
    return world[valid], colors[valid] if colors is not None else None


def extract_foreground_points(
    points_flat: np.ndarray,
    confidence_flat: np.ndarray,
    *,
    view_ids: Sequence[str],
    camera_to_world: np.ndarray,
    masks: dict[str, np.ndarray],
    patch_hw: tuple[int, int],
    confidence_percentile: float = 20.0,
    depth_edge_rtol: float = 0.03,
    local_depth: np.ndarray | None = None,
) -> np.ndarray:
    """Points-only wrapper around `extract_foreground`."""
    points, _ = extract_foreground(
        points_flat,
        confidence_flat,
        view_ids=view_ids,
        camera_to_world=camera_to_world,
        masks=masks,
        patch_hw=patch_hw,
        confidence_percentile=confidence_percentile,
        depth_edge_rtol=depth_edge_rtol,
        local_depth=local_depth,
    )
    return points
