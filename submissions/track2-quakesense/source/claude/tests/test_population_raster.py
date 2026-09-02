"""Tests for geo.population_raster, using an in-memory synthetic GeoTIFF."""

from __future__ import annotations

import numpy as np
import pytest
import rasterio
from rasterio.io import MemoryFile
from rasterio.transform import from_origin

from geo.population_raster import grid_from_raster


@pytest.fixture
def synthetic_raster(tmp_path):
    """A 4x4 grid, 0.01 deg cells, north-up, starting at (lon=10, lat=41)."""
    data = np.array([
        [10.0, 20.0, 0.0, 5.0],
        [0.0, 30.0, 40.0, 0.0],
        [-1.0, 0.0, 0.0, 0.0],
        [0.0, 0.0, 0.0, 0.0],
    ], dtype=np.float32)
    transform = from_origin(10.0, 41.0, 0.01, 0.01)
    path = tmp_path / "synthetic.tif"
    with rasterio.open(
        path, "w", driver="GTiff", height=4, width=4, count=1,
        dtype=data.dtype, crs="EPSG:4326", transform=transform, nodata=-1.0,
    ) as dst:
        dst.write(data, 1)
    return path


def test_grid_from_raster_drops_zero_and_nodata(synthetic_raster):
    pop, centres, prov = grid_from_raster(synthetic_raster, (10.0, 40.96, 10.04, 41.0))
    # 4 populated cells: 10, 20, 5, 30, 40 -- zero and the -1 nodata cell dropped.
    assert sum(pop.values()) == pytest.approx(105.0)
    assert len(pop) == 5
    assert set(centres.keys()) == set(pop.keys())
    assert prov["populated_cells"] == 5


def test_grid_from_raster_centres_are_pixel_centroids(synthetic_raster):
    pop, centres, _ = grid_from_raster(synthetic_raster, (10.0, 40.96, 10.04, 41.0))
    # The top-left pixel (row 0, col 0) holds value 10.0; its centre should be
    # half a pixel in from the raster origin (10.0, 41.0).
    cell_id = next(cid for cid, v in pop.items() if v == pytest.approx(10.0))
    lon, lat = centres[cell_id]
    assert lon == pytest.approx(10.005, abs=1e-6)
    assert lat == pytest.approx(40.995, abs=1e-6)


def test_grid_from_raster_bbox_clip_excludes_out_of_window_cells(synthetic_raster):
    # Clip to just the top row.
    pop, _, prov = grid_from_raster(synthetic_raster, (10.0, 40.99, 10.04, 41.0))
    assert sum(pop.values()) == pytest.approx(35.0)  # 10 + 20 + 5
    assert prov["raster_shape_clipped"][0] == 1
