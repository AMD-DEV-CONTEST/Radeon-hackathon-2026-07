#!/usr/bin/env python3
"""Build a city's block-scale evacuation dataset and simulation.

City-agnostic by design: the road-enclosed block extraction, population
disaggregation, capacity-constrained simulation and rendered-agent sampling
are the same code path for every city. Only the *inputs* differ per city:

* ``--roads``: OSM road extract (GeoJSON) -- always OSM, always the same reader.
* Population, one of:
    - ``--population`` + ``--population-key``: a census/land-use-calibrated
      grid payload, when one is available for the study city.
    - ``--population-raster``: a population GeoTIFF (WorldPop or similar)
      clipped to ``--bbox``. This is the default path for every other city:
      no invented per-city calibration, just the raster's own pixel values.
* ``--shelters``: whatever shelter/refuge candidate data exists for that city
  (an official/verified list when one exists, an OSM-derived candidate list
  otherwise). Capacity is read from the file when present and otherwise
  falls back to a generic area-based or flat assumption -- see
  ``simulator.block_scale.load_shelters_geojson`` -- so a city with better
  local shelter data automatically gets better results without any code
  change, and a city with nothing yet still runs on the same assumptions.

Example (Naples, raw WorldPop population raster)
-------------------------------------------------
    python scripts/build_city_block_evacuation.py \\
        --city Naples \\
        --roads data/external/naples_roads.geojson \\
        --population-raster data/worldpop/ita_ppp_2020_1km_Aggregated_UNadj.tif \\
        --shelters data/multi_city/naples/shelters.geojson \\
        --bbox 14.14 40.79 14.35 40.92 \\
        --epicenter 14.27 40.84 --magnitude 6.5 \\
        --output-dir results/naples_blocks
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from geo.urban_blocks import (            # noqa: E402
    assign_districts,
    blocks_from_geojson,
    disaggregate_population,
)
from geo.population_raster import grid_from_raster  # noqa: E402
from simulator.block_scale import (         # noqa: E402
    BlockEvacuationSimulator,
    BlockScaleConfig,
    build_block_layer,
    load_shelters_geojson,
)


def load_grid_population(path: Path, key: str) -> tuple[dict, dict]:
    """Read grid centres and population from a census/land-use payload.

    Accepts a calibrated grid JSON layout: ``grids`` is a list of
    ``[grid_id, lon, lat]`` and ``home_population_25m`` / ``frames_25m[i]`` are
    parallel population arrays. This path is only available for cities that
    have gone through a census-calibration pipeline.
    """
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    grids = payload["grids"]
    centres = {int(g[0]): (float(g[1]), float(g[2])) for g in grids}

    if key.startswith("frame:"):
        index = int(key.split(":", 1)[1])
        values = payload["frames_25m"][index]
    else:
        values = payload[key]

    population = {int(g[0]): float(values[i]) for i, g in enumerate(grids)}
    return centres, population


def clip_blocks(blocks, bbox):
    west, south, east, north = bbox
    return [b for b in blocks if west <= b.lon <= east and south <= b.lat <= north]


def slugify(city: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", city.lower()).strip("_")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--city", required=True, help="City label, e.g. 'Naples'.")
    parser.add_argument("--roads", type=Path, required=True)

    pop_group = parser.add_mutually_exclusive_group(required=True)
    pop_group.add_argument("--population", type=Path,
                           help="Census/land-use-calibrated grid JSON.")
    pop_group.add_argument("--population-raster", type=Path,
                           help="Population GeoTIFF (e.g. WorldPop), clipped to --bbox.")
    parser.add_argument("--population-key", default="home_population_25m",
                        help="Key in --population payload, or 'frame:<i>' "
                             "for a specific half-hour frame. Ignored with "
                             "--population-raster.")

    parser.add_argument("--shelters", type=Path, required=True)
    parser.add_argument("--districts", type=Path,
                        help="District polygons for point-in-polygon attribution.")
    parser.add_argument("--bbox", type=float, nargs=4, required=True,
                        metavar=("WEST", "SOUTH", "EAST", "NORTH"),
                        help="Study window; also the population-raster clip window.")
    parser.add_argument("--drop-highways", nargs="*", default=["motorway", "motorway_link"],
                        help="Highway classes excluded from block boundaries.")
    parser.add_argument("--min-area", type=float, default=200.0)
    parser.add_argument("--max-area", type=float, default=5_000_000.0)
    parser.add_argument("--target-population", type=int,
                        help="Rescale block population to this total. Omit to "
                             "keep the population source's own real total.")
    parser.add_argument("--duration-minutes", type=int, default=120)
    parser.add_argument("--step-seconds", type=int, default=30)
    parser.add_argument("--magnitude", type=float, default=7.0)
    parser.add_argument("--epicenter", type=float, nargs=2, required=True,
                        metavar=("LON", "LAT"))
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--resistance", type=Path,
                        help="Optional per-block walking-resistance JSON from "
                             "scripts/fetch_terrain_resistance.py (slope + land cover). "
                             "Without it every block has resistance 1.0, i.e. the flat, "
                             "uniform-terrain assumption.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--no-block-detail", action="store_true",
                        help="Omit per-block records from the simulation JSON.")
    parser.add_argument("--rendered-agents", type=int, default=20_000,
                        help="Number of individual pedestrian points to sample "
                             "for point-based rendering (0 to skip).")
    args = parser.parse_args()

    slug = slugify(args.city)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    started = time.time()
    total_steps = 6 if args.rendered_agents > 0 else 5

    # 1. Blocks ------------------------------------------------------------
    print(f"[1/{total_steps}] extracting road-enclosed blocks ...")
    blocks, graph, provenance = blocks_from_geojson(
        args.roads,
        drop_highways=args.drop_highways,
        min_area_m2=args.min_area,
        max_area_m2=args.max_area,
    )
    print(f"      {len(blocks):,} blocks from {provenance['road_features']:,} road features")

    before = len(blocks)
    blocks = clip_blocks(blocks, args.bbox)
    provenance["study_window_bbox"] = args.bbox
    provenance["blocks_in_window"] = len(blocks)
    print(f"      clipped to study window: {before:,} -> {len(blocks):,}")

    if not blocks:
        raise SystemExit("No blocks left after filtering; check --bbox and --min-area.")

    # 2. Population --------------------------------------------------------
    print(f"[2/{total_steps}] disaggregating population onto blocks ...")
    if args.population_raster:
        grid_population, centres, raster_prov = grid_from_raster(args.population_raster, tuple(args.bbox))
        population_method = "raw population-raster pixel values, no per-city calibration"
        population_source_note = raster_prov
    else:
        centres, grid_population = load_grid_population(args.population, args.population_key)
        population_method = "areal interpolation, block-area weighted, mass conserving"
        population_source_note = {"key": args.population_key, "grid_cells": len(centres)}

    result = disaggregate_population(blocks, grid_population, centres)
    for block in blocks:
        block.population = result["assigned"].get(block.block_id, 0.0)
    assigned_total = sum(result["assigned"].values())
    print(f"      grid total {sum(grid_population.values()):,.0f} -> "
          f"blocks {assigned_total:,.0f}, residual {result['residual']:,.0f}, "
          f"conservation error {result['conservation_error']:.2e}")
    provenance["population"] = {
        "source": str(args.population_raster or args.population),
        "grid_total": sum(grid_population.values()),
        "assigned_to_blocks": assigned_total,
        "residual_outside_blocks": result["residual"],
        "conservation_error": result["conservation_error"],
        "method": population_method,
        **population_source_note,
    }

    # 3. Districts ---------------------------------------------------------
    if args.districts and args.districts.exists():
        print(f"[3/{total_steps}] attributing blocks to districts ...")
        district_geojson = json.loads(args.districts.read_text(encoding="utf-8"))
        hits = assign_districts(blocks, district_geojson)
        print(f"      {hits:,}/{len(blocks):,} blocks attributed")
        provenance["districts"] = {"source": str(args.districts), "attributed": hits}
    else:
        print(f"[3/{total_steps}] no district file supplied; skipping attribution")

    # 4. Simulation --------------------------------------------------------
    print(f"[4/{total_steps}] running block-scale evacuation ...")
    config = BlockScaleConfig(
        city=args.city,
        seed=args.seed,
        step_seconds=args.step_seconds,
        duration_minutes=args.duration_minutes,
        target_population=args.target_population,
        magnitude=args.magnitude,
        epicenter_lon=args.epicenter[0],
        epicenter_lat=args.epicenter[1],
    )
    shelters = load_shelters_geojson(args.shelters, config)
    print(f"      {len(shelters)} shelters, "
          f"capacity {sum(s.capacity for s in shelters):,.0f}")

    resistance_by_block = None
    if args.resistance:
        res_payload = json.loads(args.resistance.read_text(encoding="utf-8"))
        raw = res_payload["resistance_by_block"]
        # "Infinity" is the JSON-safe sentinel fetch_terrain_resistance.py writes
        # for land cover that is not crossable on foot (open water).
        resistance_by_block = {
            k: (float("inf") if v == "Infinity" else float(v)) for k, v in raw.items()
        }
        summary = res_payload.get("resistance_summary", {})
        print(f"      terrain resistance: {len(resistance_by_block):,} blocks, "
              f"median {summary.get('median')}, max {summary.get('max')}, "
              f"{summary.get('impassable_count')} impassable")
        provenance["terrain_resistance"] = {
            "source": str(args.resistance),
            "slope_source": res_payload.get("slope_source"),
            "landcover_source": res_payload.get("landcover_source"),
            "summary": summary,
        }

    layer = build_block_layer(blocks, resistance_by_block=resistance_by_block)
    simulator = BlockEvacuationSimulator(layer, shelters, config)
    simulator.run()
    payload = simulator.to_dict(include_blocks=not args.no_block_detail)
    payload["provenance"] = provenance

    # 5. Rendered-agent sample ----------------------------------------------
    agents = []
    if args.rendered_agents > 0:
        print(f"[5/{total_steps}] sampling individual pedestrian points for rendering ...")
        agents = simulator.sample_rendered_agents(args.rendered_agents)
        print(f"      {len(agents):,} points sampled")

    # 6. Write -------------------------------------------------------------
    print(f"[{total_steps}/{total_steps}] writing outputs ...")
    blocks_path = args.output_dir / f"{slug}_blocks.geojson"
    blocks_path.write_text(
        json.dumps(
            {"type": "FeatureCollection",
             "properties": {"attribution": provenance["attribution"]},
             "features": [b.to_feature() for b in blocks]},
            ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )

    sim_path = args.output_dir / f"{slug}_block_evacuation.json"
    sim_path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                        encoding="utf-8")

    prov_path = args.output_dir / f"{slug}_blocks_provenance.json"
    prov_path.write_text(json.dumps(provenance, ensure_ascii=False, indent=2),
                         encoding="utf-8")

    agents_path = None
    if agents:
        agents_path = args.output_dir / f"{slug}_block_agents.json"
        agents_path.write_text(json.dumps({
            "schema_version": "1.0",
            "city": args.city,
            "scale": "block",
            "duration_minutes": args.duration_minutes,
            "will_evacuate_population": payload["totals"]["will_evacuate"],
            "agents": agents,
        }, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    totals = payload["totals"]
    print()
    print("=" * 62)
    print(f"city                  {args.city}")
    print(f"blocks                {totals['blocks']:,}")
    print(f"population            {totals['population']:,.0f}")
    print(f"will evacuate         {totals['will_evacuate']:,.0f}")
    print(f"sheltered             {totals['sheltered']:,.0f}")
    print(f"still queued          {totals['still_queued']:,.0f}")
    print(f"unserved population   {totals['unserved_population']:,.0f} "
          f"({totals['unserved_blocks']:,} blocks)")
    print(f"shelter capacity      {totals['shelter_capacity']:,.0f}")
    print(f"clearance P50 / P90   {totals['clearance_time_p50_min']} / "
          f"{totals['clearance_time_p90_min']} min")
    print(f"conservation error    {payload['conservation']['relative_error']:.2e}")
    print("=" * 62)
    print(f"blocks     -> {blocks_path}  ({blocks_path.stat().st_size/1e6:.1f} MB)")
    print(f"simulation -> {sim_path}  ({sim_path.stat().st_size/1e6:.1f} MB)")
    print(f"provenance -> {prov_path}")
    if agents_path:
        print(f"agents     -> {agents_path}  ({agents_path.stat().st_size/1e6:.1f} MB, {len(agents):,} points)")
    print(f"elapsed {time.time()-started:.1f}s")


if __name__ == "__main__":
    main()
