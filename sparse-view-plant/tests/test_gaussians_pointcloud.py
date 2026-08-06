from __future__ import annotations

import numpy as np

from sparse_view_plant.gaussians_pointcloud import points_to_gaussians
from sparse_view_plant.rendering import sh_dc_to_rgb


def _cloud(
    count: int = 300, seed: int = 0
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    points = rng.normal(size=(count, 3))
    colors = rng.uniform(0.0, 1.0, size=(count, 3))
    confidence = rng.uniform(0.01, 0.6, size=(count,))
    return points, colors, confidence


def test_points_to_gaussians_shapes_and_roundtrip() -> None:
    points, colors, confidence = _cloud()
    means, sh_dc, opacities, covariances = points_to_gaussians(
        points, colors, confidence
    )
    assert means.shape[1] == 3
    assert sh_dc.shape == (len(means), 3)
    assert opacities.shape == (len(means),)
    assert covariances.shape == (len(means), 3, 3)
    assert len(means) < len(points)  # confidence cut applies


def test_points_to_gaussians_scales_match_density() -> None:
    dense = np.random.default_rng(1).normal(scale=0.001, size=(400, 3))
    sparse = np.random.default_rng(2).normal(scale=0.1, size=(400, 3))
    confidence = np.full(400, 0.5)
    _, _, _, cov_dense = points_to_gaussians(dense, np.full((400, 3), 0.5), confidence)
    _, _, _, cov_sparse = points_to_gaussians(
        sparse, np.full((400, 3), 0.5), confidence
    )
    scale_dense = np.sqrt(cov_dense[0, 0, 0])
    scale_sparse = np.sqrt(cov_sparse[0, 0, 0])
    assert scale_sparse > 10 * scale_dense


def test_points_to_gaussians_color_roundtrip() -> None:
    points, colors, confidence = _cloud()
    means, sh_dc, _, _ = points_to_gaussians(points, colors, confidence)
    expected = colors[
        confidence >= np.quantile(confidence, 0.2)
    ]  # same keep-fraction cut as the converter
    assert len(expected) == len(means)
    decoded = sh_dc_to_rgb(sh_dc)
    np.testing.assert_allclose(decoded, expected, atol=1e-9)


def test_points_to_gaussians_opacities_in_range() -> None:
    points, colors, confidence = _cloud()
    _, _, opacities, _ = points_to_gaussians(points, colors, confidence)
    activated = 1.0 / (1.0 + np.exp(-opacities))
    assert activated.min() > 0.0 and activated.max() < 1.0
    assert activated.max() > 0.5
