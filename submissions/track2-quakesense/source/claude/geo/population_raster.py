"""Turn a population GeoTIFF (e.g. WorldPop) into the grid dicts that
``geo.urban_blocks.disaggregate_population`` expects.

This allows a city without a census/land-use calibration pipeline to feed the
same block-scale engine: ``disaggregate_population`` only needs
``{cell_id: population}`` and
``{cell_id: (lon, lat)}`` for the coarse cells, which is exactly what a
population raster's pixels are. WorldPop's own pixel values become the "real"
population source, honestly labelled as-is -- no invented city-specific
capacity or calibration is layered on top here.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import rasterio
from rasterio.windows import from_bounds


def grid_from_raster(
    raster_path: Path,
    bbox: tuple[float, float, float, float],
    *,
    band: int = 1,
) -> tuple[dict[int, float], dict[int, tuple[float, float]], dict]:
    """Read population pixels within ``bbox`` (west, south, east, north).

    Returns ``(grid_population, grid_centres, provenance)``. Pixel cell ids
    are stable row-major indices into the clipped window, matching the
    ``dict[int, ...]`` shape ``disaggregate_population`` expects. Nodata and
    negative pixels are dropped rather than coerced to zero-with-population,
    so they don't silently participate in the conservation check.
    """
    with rasterio.open(raster_path) as src:
        west, south, east, north = bbox
        window = from_bounds(west, south, east, north, src.transform).round_offsets().round_lengths()
        values = src.read(band, window=window, boundless=True, fill_value=src.nodata or 0).astype(np.float64)
        transform = src.window_transform(window)
        nodata = src.nodata
        crs = str(src.crs)

    if nodata is not None:
        values[values == nodata] = 0.0
    values[~np.isfinite(values)] = 0.0
    values[values < 0] = 0.0

    rows, cols = values.shape
    grid_population: dict[int, float] = {}
    grid_centres: dict[int, tuple[float, float]] = {}
    for r in range(rows):
        for c in range(cols):
            pop = float(values[r, c])
            if pop <= 0:
                continue
            lon = transform.c + (c + 0.5) * transform.a
            lat = transform.f + (r + 0.5) * transform.e
            cell_id = r * cols + c
            grid_population[cell_id] = pop
            grid_centres[cell_id] = (lon, lat)

    provenance = {
        "source": str(raster_path),
        "band": band,
        "bbox": list(bbox),
        "crs": crs,
        "raster_shape_clipped": [rows, cols],
        "pixel_size_deg": [abs(transform.a), abs(transform.e)],
        "populated_cells": len(grid_population),
        "raw_raster_total": round(float(sum(grid_population.values())), 1),
    }
    return grid_population, grid_centres, provenance
