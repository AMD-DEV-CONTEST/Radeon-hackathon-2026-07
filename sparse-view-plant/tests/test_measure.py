"""Tests for the plant phenotype measurement module."""

import numpy as np
import pytest

from sparse_view_plant.measure import measure_plant


def test_elongated_cloud_reports_sorted_pca_extents() -> None:
    rng = np.random.default_rng(0)
    points = rng.normal(size=(5000, 3)) * [0.5, 2.0, 0.3] + [0, 1, 0]
    result = measure_plant(points, voxel_fraction=0.02)
    assert result.point_count == 5000
    assert result.pca_extent[0] > result.pca_extent[1] > result.pca_extent[2]
    assert result.diagonal > 0.0
    assert result.convex_hull_volume > 0.0
    assert 0.0 < result.compactness <= 1.0


def test_measure_is_deterministic() -> None:
    rng = np.random.default_rng(1)
    points = rng.normal(size=(3000, 3))
    first = measure_plant(points, voxel_fraction=0.02)
    second = measure_plant(points, voxel_fraction=0.02)
    assert first.convex_hull_volume == pytest.approx(second.convex_hull_volume)
    assert first.surface_area == pytest.approx(second.surface_area)


def test_estimated_meters_scale_linearly() -> None:
    rng = np.random.default_rng(2)
    points = rng.normal(size=(2000, 3))
    base = measure_plant(points, metric_scale=1.0, voxel_fraction=0.02)
    scaled = measure_plant(points, metric_scale=2.0, voxel_fraction=0.02)
    assert scaled.estimated_meters is not None
    assert base.estimated_meters is not None
    assert scaled.estimated_meters["height"] == pytest.approx(
        2.0 * base.estimated_meters["height"]
    )
    assert scaled.estimated_meters["convex_hull_volume"] == pytest.approx(
        8.0 * base.estimated_meters["convex_hull_volume"]
    )


def test_rejects_fewer_than_four_points() -> None:
    with pytest.raises(ValueError):
        measure_plant(np.zeros((3, 3)))
