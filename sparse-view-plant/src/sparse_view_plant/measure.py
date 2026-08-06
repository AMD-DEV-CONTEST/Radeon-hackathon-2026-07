"""Plant phenotype measurements from a reconstructed point cloud.

Digital-twin-friendly, dependency-light (numpy + scipy) metrics: bounding
box / PCA extents, convex-hull and voxel volumes, a surface-area proxy and
compactness/solidity ratios. All values are reported in the reconstruction
frame; `estimated_meters` scales them by the frontend `metric_scale` when it is
available, which is a rough global scale and should not be treated as
calibrated ground truth (a Sim3 against known geometry is needed for real
metric measurements).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

_PCA_SEED = 0


@dataclass(frozen=True, slots=True)
class PlantMeasurements:
    point_count: int
    bbox_min: tuple[float, float, float]
    bbox_max: tuple[float, float, float]
    bbox_extent: tuple[float, float, float]
    diagonal: float
    pca_extent: tuple[float, float, float]  # per principal axis, significance order
    convex_hull_volume: float
    voxel_volume: float
    surface_area: float
    bbox_volume: float
    compactness: float  # convex-hull volume / bounding-box volume
    solidity: float  # voxel occupancy volume / convex-hull volume
    height_ratio: float  # longest PCA extent / diagonal
    estimated_meters: dict[str, float] | None


def measure_plant(
    points: np.ndarray,
    *,
    metric_scale: float | None = None,
    voxel_fraction: float = 0.01,
    maximum: int = 200_000,
) -> PlantMeasurements:
    """Compute rotation-invariant phenotype metrics for a plant point cloud.

    `points` is (M, 3) in the reconstruction frame. Points are uniformly
    subsampled to `maximum` before the expensive geometric measures; the
    bounding-box and PCA extents use the full cloud.
    """
    pts = np.asarray(points, dtype=np.float64)
    if pts.ndim != 2 or pts.shape[1] != 3 or len(pts) < 4:
        raise ValueError(f"points must have shape (M, 3) with M >= 4, got {pts.shape}")
    full = pts[np.isfinite(pts).all(axis=1)]
    if len(full) < 4:
        raise ValueError("fewer than 4 finite points")

    bbox_min = full.min(axis=0)
    bbox_max = full.max(axis=0)
    extent = bbox_max - bbox_min
    diagonal = float(np.linalg.norm(extent))
    if diagonal <= 0.0:
        raise ValueError("point cloud has zero diagonal")

    centred = full - full.mean(axis=0)
    _, _, vh = np.linalg.svd(centred, full_matrices=False)
    axes = vh.T  # (3, 3) principal axes, row-major significance
    rotated = centred @ axes
    pca_extent = (
        float(rotated[:, 0].max() - rotated[:, 0].min()),
        float(rotated[:, 1].max() - rotated[:, 1].min()),
        float(rotated[:, 2].max() - rotated[:, 2].min()),
    )

    sampled = _subsample(full, maximum, seed=_PCA_SEED)
    hull_volume = _convex_hull_volume(sampled)
    voxel_size = float(diagonal * voxel_fraction)
    occupancy = _occupancy_grid(sampled, voxel_size)
    voxel_volume = float(np.count_nonzero(occupancy)) * voxel_size**3
    surface_area = float(_boundary_faces(occupancy)) * voxel_size**2
    bbox_volume = float(extent[0] * extent[1] * extent[2])

    def _safe_ratio(numerator: float, denominator: float) -> float:
        return float(numerator / denominator) if denominator > 0.0 else 0.0

    estimated_meters: dict[str, float] | None = None
    if metric_scale is not None and np.isfinite(metric_scale) and metric_scale > 0.0:
        factor = float(metric_scale)
        estimated_meters = {
            "scale": factor,
            "height": pca_extent[0] * factor,
            "width": pca_extent[1] * factor,
            "depth": pca_extent[2] * factor,
            "convex_hull_volume": hull_volume * factor**3,
            "surface_area": surface_area * factor**2,
        }
    return PlantMeasurements(
        point_count=len(full),
        bbox_min=(float(bbox_min[0]), float(bbox_min[1]), float(bbox_min[2])),
        bbox_max=(float(bbox_max[0]), float(bbox_max[1]), float(bbox_max[2])),
        bbox_extent=(float(extent[0]), float(extent[1]), float(extent[2])),
        diagonal=diagonal,
        pca_extent=pca_extent,
        convex_hull_volume=float(hull_volume),
        voxel_volume=voxel_volume,
        surface_area=surface_area,
        bbox_volume=bbox_volume,
        compactness=_safe_ratio(hull_volume, bbox_volume),
        solidity=_safe_ratio(voxel_volume, hull_volume),
        height_ratio=_safe_ratio(pca_extent[0], diagonal),
        estimated_meters=estimated_meters,
    )


def _subsample(points: np.ndarray, maximum: int, *, seed: int) -> np.ndarray:
    if len(points) <= maximum:
        return points
    indices = np.sort(
        np.random.default_rng(seed).choice(len(points), maximum, replace=False)
    )
    return points[indices]


def _convex_hull_volume(points: np.ndarray) -> float:
    from scipy.spatial import ConvexHull, QhullError

    try:
        hull = ConvexHull(points)
        return float(hull.volume)
    except (QhullError, ValueError):  # degenerate (near-planar) cloud
        return 0.0


def _occupancy_grid(points: np.ndarray, voxel_size: float) -> np.ndarray:
    if voxel_size <= 0.0:
        raise ValueError("voxel_size must be positive")
    origin = points.min(axis=0)
    indices = np.floor((points - origin) / voxel_size).astype(np.int64)
    shape = tuple(int(indices[:, axis].max()) + 1 for axis in range(3))
    grid = np.zeros(shape, dtype=np.uint8)
    grid[tuple(indices[:, 0]), tuple(indices[:, 1]), tuple(indices[:, 2])] = 1
    return grid


def _boundary_faces(grid: np.ndarray) -> int:
    """Count occupied-voxel faces adjacent to an empty voxel (or the border)."""
    padded = np.pad(grid, 1, constant_values=0)
    count = 0
    for axis in range(3):
        slices = [slice(1, -1)] * 3
        below = slices.copy()
        above = slices.copy()
        below[axis] = slice(0, -2)
        above[axis] = slice(2, None)
        interior = grid > 0
        count += int(np.count_nonzero(interior & (padded[tuple(below)] == 0)))
        count += int(np.count_nonzero(interior & (padded[tuple(above)] == 0)))
    return count
