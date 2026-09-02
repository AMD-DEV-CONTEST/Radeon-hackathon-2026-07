#!/usr/bin/env python3
"""Download OSM road-network data for one or more cities already prepared
under data/multi_city/<city>/ (population + shelters, from
scripts/download_multi_city_data.py), so the block-scale pipeline
(scripts/build_city_block_evacuation.py) can run for them too.

Some scenarios have population and shelter data but no road network, which
road-enclosed block extraction needs. This script closes that gap using an
Overpass API plus mirror-fallback approach for
shelters in scripts/download_multi_city_data.py, reading each city's bbox
from its existing data/multi_city/<city>/summary.json rather than
duplicating bbox definitions.

Usage:
    python scripts/download_city_roads.py --city kathmandu
    python scripts/download_city_roads.py --all-missing
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import requests

OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]

MULTI_CITY_DIR = Path(__file__).resolve().parents[2] / "data" / "multi_city"
EXTERNAL_DIR = Path(__file__).resolve().parents[2] / "data" / "external"


def build_roads_query(bbox: list[float]) -> str:
    south, west, north, east = bbox
    return f"""
[out:json][timeout:180];
(
  way["highway"]({south},{west},{north},{east});
);
out geom;
""".strip()


def download_roads(bbox: list[float], city_label: str) -> dict:
    """Query Overpass for the road network (all `highway=*` ways) in bbox,
    using ``out geom`` so each way's full line geometry comes back inline
    (no separate node-resolution pass needed)."""
    query = build_roads_query(bbox)
    payload = {"data": query}
    headers = {"User-Agent": "SeismicEvacuationResearchDemo/0.1"}

    response = None
    for endpoint in OVERPASS_ENDPOINTS:
        try:
            print(f"  Trying Overpass: {endpoint}")
            candidate = requests.post(endpoint, data=payload, headers=headers, timeout=180)
            candidate.raise_for_status()
            response = candidate
            break
        except Exception as exc:
            print(f"  Failed: {exc}")
            response = None
            time.sleep(3)

    if response is None:
        print(f"  WARNING: all Overpass endpoints failed for {city_label}")
        return {"type": "FeatureCollection", "features": []}

    osm_data = response.json()
    features = []
    for el in osm_data.get("elements", []):
        if el.get("type") != "way" or "geometry" not in el:
            continue
        coords = [[pt["lon"], pt["lat"]] for pt in el["geometry"]]
        if len(coords) < 2:
            continue
        tags = el.get("tags", {})
        features.append({
            "type": "Feature",
            "properties": {
                "highway": tags.get("highway"),
                "osm_id": el["id"],
                "name": tags.get("name", ""),
                "source": "OpenStreetMap",
            },
            "geometry": {"type": "LineString", "coordinates": coords},
        })

    print(f"  Found {len(features)} road ways for {city_label}")
    return {"type": "FeatureCollection", "features": features}


def cities_missing_roads() -> list[str]:
    out = []
    for city_dir in sorted(MULTI_CITY_DIR.iterdir()):
        if not city_dir.is_dir():
            continue
        summary = city_dir / "summary.json"
        if not summary.exists():
            continue
        roads_path = EXTERNAL_DIR / f"{city_dir.name}_roads.geojson"
        if not roads_path.exists():
            out.append(city_dir.name)
    return out


def run_city(city: str) -> None:
    summary_path = MULTI_CITY_DIR / city / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    bbox = summary["bbox"]
    label = summary.get("label", city)
    print(f"[{city}] bbox={bbox} ({label})")
    geojson = download_roads(bbox, label)
    out_path = EXTERNAL_DIR / f"{city}_roads.geojson"
    out_path.write_text(json.dumps(geojson, ensure_ascii=False), encoding="utf-8")
    print(f"[{city}] wrote {len(geojson['features'])} features -> {out_path}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--city", help="single city slug (matches data/multi_city/<slug>/)")
    p.add_argument("--all-missing", action="store_true", help="run every city under data/multi_city/ that has no roads geojson yet")
    p.add_argument("--sleep-between", type=float, default=5.0, help="seconds to wait between cities, to be polite to Overpass")
    args = p.parse_args()

    if args.city:
        run_city(args.city)
        return

    if args.all_missing:
        missing = cities_missing_roads()
        print(f"cities missing roads: {missing}")
        for i, city in enumerate(missing):
            run_city(city)
            if i < len(missing) - 1:
                time.sleep(args.sleep_between)
        return

    p.error("pass --city <slug> or --all-missing")


if __name__ == "__main__":
    main()
