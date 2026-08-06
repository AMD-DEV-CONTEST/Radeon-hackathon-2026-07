"""Point-cloud-to-Gaussians stage (no network, feed-forward).

Wraps the fused frontend point cloud as a standard 3DGS PLY so downstream
rendering/evaluation treats it like any Gaussian backend:

- means = confidence-filtered frontend points (same cut as `pointcloud.ply`),
- scales = local density (k-th nearest-neighbour distance),
- opacities = normalized confidence mapped to logits,
- colors = point RGB stored as the SH DC term.

The geometry is therefore the frontend point cloud rather than a feed-forward
GS network's latent blob; no training or GT metadata is involved.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from scipy.spatial import KDTree

from sparse_view_plant.config import GaussianConfig
from sparse_view_plant.export import write_gaussian_splat_ply
from sparse_view_plant.pointcloud import find_prediction_npz
from sparse_view_plant.rendering import SH_C0, gaussian_covariances

NN_NEIGHBORS = 8  # k-th neighbour used for the local-density scale
CONFIDENCE_KEEP_FRACTION = 0.8  # matches the pipeline's pointcloud.ply cut
MIN_SCALE = 1e-5


def _confidence_cut(
    points: np.ndarray,
    colors: np.ndarray,
    confidence: np.ndarray,
    *,
    keep_fraction: float = CONFIDENCE_KEEP_FRACTION,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Keep the top `keep_fraction` of points by confidence (eval-free)."""
    threshold = np.quantile(confidence, 1.0 - keep_fraction)
    keep = np.asarray(confidence) >= threshold
    return points[keep], colors[keep], confidence[keep]


def density_scales(points: np.ndarray, k: int = NN_NEIGHBORS) -> np.ndarray:
    """Per-point gaussian std from the distance to the k-th neighbour."""
    tree = KDTree(np.asarray(points, dtype=np.float64))
    distances, _ = tree.query(points, k=k + 1, workers=-1)
    return np.clip(distances[:, -1] / 2.0, MIN_SCALE, None)


def _opacity_logits(confidence: np.ndarray) -> np.ndarray:
    """Map confidence to sigmoid-activation logits in a renderable range."""
    lo, hi = np.quantile(confidence, 0.02), np.quantile(confidence, 0.98)
    span = max(float(hi - lo), 1e-6)
    target = 0.05 + 0.9 * np.clip((confidence - lo) / span, 0.0, 1.0)
    target = np.clip(target, 1e-3, 1.0 - 1e-3)
    return np.log(target / (1.0 - target))


def points_to_gaussians(
    points: np.ndarray,
    colors: np.ndarray,
    confidence: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Convert a frontend prediction to (means, colors, opacities, covariances)."""
    points, colors, confidence = _confidence_cut(points, colors, confidence)
    scales = np.tile(density_scales(points)[:, None], (1, 3))
    quaternions = np.tile(np.asarray([0.0, 0.0, 0.0, 1.0]), (len(points), 1))
    covariances = gaussian_covariances(scales, quaternions)
    sh_dc = (np.asarray(colors, dtype=np.float64) - 0.5) / SH_C0
    opacities = _opacity_logits(confidence)
    return points, sh_dc, opacities, covariances


@dataclass(frozen=True, slots=True)
class PointCloudGaussianStage:
    """Convert the saved frontend prediction into a renderable Gaussian PLY."""

    config: GaussianConfig

    @classmethod
    def create(cls, config: GaussianConfig) -> PointCloudGaussianStage:
        return cls(config)

    def reconstruct(
        self,
        images: Any,
        output_dir: str | Path,
        *,
        camera_to_world: np.ndarray | None = None,
    ) -> Path:
        root = Path(output_dir)
        npz_path = find_prediction_npz(root)
        if npz_path is None:
            raise RuntimeError(
                "pointcloud-gs backend needs a *_prediction.npz in the output "
                "directory; run with --stage all (or pointcloud first)"
            )
        payload = np.load(npz_path)
        means, sh_dc, opacities, covariances = points_to_gaussians(
            np.asarray(payload["points"]),
            np.asarray(payload["colors"]),
            np.asarray(payload["confidence"]),
        )
        ply_path = root / "gaussians.ply"
        write_gaussian_splat_ply(
            ply_path,
            means=means,
            covariances=covariances,
            sh_dc=sh_dc,
            opacities=opacities[:, None],
        )
        return ply_path
