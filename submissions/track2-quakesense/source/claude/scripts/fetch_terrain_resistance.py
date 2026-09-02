#!/usr/bin/env python3
"""Sample slope (SRTM) and land cover (ESA WorldCover v200) at each block
centroid via Earth Engine, and write the per-block walking-resistance value
the block-scale simulator consumes as ``BlockLayer.resistance``.

Must run from a machine with unrestricted access to Google's IP ranges --
this project's cloud GPU server blocks outbound to googleapis.com (see
scripts/test_gee_auth.py), which is why block centroids are exported there
(scripts/export_block_centroids.py) and the resistance values are sent back.

Sampling is chunked because ``getInfo`` has a payload ceiling and a city can
have tens of thousands of blocks; each chunk is retried on transient
failure, and a chunk that still fails is recorded as missing rather than
silently dropped or defaulted -- a block with no terrain data keeps
resistance 1.0 (no penalty) and is counted in the report, so the caller can
see how much of the surface is real.

    python scripts/fetch_terrain_resistance.py \\
        --centroids results_naples/naples_block_centroids.json \\
        --output results_naples/naples_block_resistance.json
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ee  # noqa: E402
from google.oauth2 import service_account  # noqa: E402

from geo.terrain_resistance import combined_resistance  # noqa: E402

SCOPES = ["https://www.googleapis.com/auth/earthengine"]


def init_ee(key_path: Path) -> None:
    credentials = service_account.Credentials.from_service_account_file(str(key_path), scopes=SCOPES)
    project_id = json.loads(key_path.read_text())["project_id"]
    ee.Initialize(credentials, project=project_id)


def sample_chunk(points: list[dict], scale: int, retries: int = 4) -> list[dict]:
    """Sample slope% and WorldCover class at a chunk of lon/lat points."""
    slope = ee.Terrain.slope(ee.Image("USGS/SRTMGL1_003")).rename("slope_deg")
    cover = ee.Image("ESA/WorldCover/v200/2021").select("Map").rename("cover")
    stack = slope.addBands(cover)

    fc = ee.FeatureCollection([
        ee.Feature(ee.Geometry.Point([p["lon"], p["lat"]]), {"block_id": p["block_id"]})
        for p in points
    ])

    last_exc = None
    for attempt in range(retries):
        try:
            sampled = stack.reduceRegions(collection=fc, reducer=ee.Reducer.first(), scale=scale)
            return sampled.getInfo()["features"]
        except Exception as exc:  # noqa: BLE001 - GEE raises a variety of transport errors
            last_exc = exc
            print(f"    retry {attempt + 1}/{retries} after: {exc}")
            time.sleep(4 * (attempt + 1))
    raise last_exc  # type: ignore[misc]


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--centroids", type=Path, required=True)
    p.add_argument(
        "--key",
        type=Path,
        required=True,
        help="Path to a local Earth Engine service-account JSON file; never commit it.",
    )
    p.add_argument("--chunk-size", type=int, default=400)
    p.add_argument("--scale", type=int, default=30, help="sampling scale in metres (SRTM native ~30 m)")
    p.add_argument(
        "--max-resistance", type=float, default=33.1,
        help=(
            "Cap on the finite slope penalty. Default 33.1 is Tobler's own resistance at a "
            "45-degree slope: past that the hiking function's exponential produces values "
            "(1,100x at 63 degrees, 29,000x at 71 degrees) that are not meaningful claims "
            "about pedestrian walking speed but artefacts of point-sampling a 30 m DEM on a "
            "cliff face. Capping declines to extrapolate the function outside its calibrated "
            "domain; the count of capped blocks is reported so the choice stays visible."
        ),
    )
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()

    init_ee(args.key)
    print("GEE initialized")

    payload = json.loads(args.centroids.read_text(encoding="utf-8"))
    blocks = payload["blocks"]
    print(f"sampling {len(blocks):,} block centroids in chunks of {args.chunk_size} at {args.scale} m ...")

    resistance: dict[str, float] = {}
    diagnostics = {"slope_missing": 0, "cover_missing": 0, "impassable": 0,
                   "chunks_failed": 0, "capped_at_max": 0}
    started = time.time()

    for i in range(0, len(blocks), args.chunk_size):
        chunk = blocks[i:i + args.chunk_size]
        try:
            features = sample_chunk(chunk, args.scale)
        except Exception as exc:  # noqa: BLE001
            diagnostics["chunks_failed"] += 1
            print(f"  chunk {i}-{i + len(chunk)} FAILED permanently: {exc}")
            continue

        for feat in features:
            props = feat.get("properties", {})
            block_id = props.get("block_id")
            if block_id is None:
                continue
            slope_deg = props.get("slope_deg")
            cover_class = props.get("cover")
            if slope_deg is None:
                diagnostics["slope_missing"] += 1
            if cover_class is None:
                diagnostics["cover_missing"] += 1
            # Tobler's function takes slope as a percentage (rise/run x 100),
            # while ee.Terrain.slope returns degrees.
            slope_percent = math.tan(math.radians(float(slope_deg))) * 100.0 if slope_deg is not None else None
            r = combined_resistance(slope_percent, int(cover_class) if cover_class is not None else None)
            if math.isinf(r):
                # Open water and other classes marked not-crossable-on-foot stay
                # infinite: that is a categorical statement ("you do not wade
                # across the bay"), not an extrapolated speed penalty, so the
                # cap below deliberately does not apply to it.
                diagnostics["impassable"] += 1
                resistance[block_id] = float("inf")
            else:
                if r > args.max_resistance:
                    diagnostics["capped_at_max"] += 1
                    r = args.max_resistance
                resistance[block_id] = round(r, 4)

        done = min(i + args.chunk_size, len(blocks))
        elapsed = time.time() - started
        rate = done / max(elapsed, 1e-9)
        print(f"  {done:,}/{len(blocks):,}  ({rate:.0f} pts/s, {elapsed:.0f}s elapsed)")

    finite = [v for v in resistance.values() if math.isfinite(v)]
    report = {
        "source_centroids": str(args.centroids),
        "slope_source": "USGS/SRTMGL1_003 via ee.Terrain.slope (degrees -> percent)",
        "landcover_source": "ESA/WorldCover/v200/2021 band Map",
        "sample_scale_m": args.scale,
        "max_resistance_cap": args.max_resistance,
        "max_resistance_cap_rationale": (
            "Tobler resistance at a 45-degree slope. Beyond that the hiking function's "
            "exponential yields values that are DEM point-sampling artefacts on cliff faces "
            "rather than pedestrian-speed claims; capping declines to extrapolate outside "
            "the function's calibrated domain. Land-cover impassability (open water) is "
            "categorical and stays infinite, uncapped."
        ),
        "blocks_requested": len(blocks),
        "blocks_resolved": len(resistance),
        "diagnostics": diagnostics,
        "resistance_summary": {
            "min": round(min(finite), 4) if finite else None,
            "median": round(sorted(finite)[len(finite) // 2], 4) if finite else None,
            "max": round(max(finite), 4) if finite else None,
            "impassable_count": diagnostics["impassable"],
        },
        # inf is not valid JSON; the consumer converts this sentinel back.
        "resistance_by_block": {k: ("Infinity" if math.isinf(v) else v) for k, v in resistance.items()},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report), encoding="utf-8")

    print(f"\nwrote {len(resistance):,} resistance values -> {args.output}")
    print(f"  summary: {report['resistance_summary']}")
    print(f"  diagnostics: {diagnostics}")


if __name__ == "__main__":
    main()
