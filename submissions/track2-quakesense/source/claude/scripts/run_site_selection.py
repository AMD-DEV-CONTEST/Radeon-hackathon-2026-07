#!/usr/bin/env python3
"""Greedy search for where k new shelters should go, on a real city.

Candidates default to the highest-population currently-*unserved* block
centroids (the ones the existing shelter set can't reach at all) -- the most
obviously defensible starting candidate pool, though any list of real
proposed sites can be substituted with --candidates-geojson.

Example
-------
    python scripts/run_site_selection.py \\
        --roads data/external/naples_roads.geojson \\
        --population-raster data/worldpop/ita_ppp_2020_1km_Aggregated_UNadj.tif \\
        --shelters data/multi_city/naples/shelters.geojson \\
        --bbox 14.14 40.79 14.35 40.92 \\
        --epicenter 14.25 40.84 --magnitude 6.5 \\
        --k 5 --candidate-pool 30 --new-shelter-capacity 5000 \\
        --output results_naples/site_selection.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from geo.urban_blocks import blocks_from_geojson, disaggregate_population  # noqa: E402
from geo.population_raster import grid_from_raster  # noqa: E402
from scripts.build_city_block_evacuation import clip_blocks, load_grid_population  # noqa: E402
from simulator.block_scale import (  # noqa: E402
    BlockEvacuationSimulator, BlockScaleConfig, ShelterSite, build_block_layer, load_shelters_geojson,
)
from simulator.site_selection import greedy_shelter_siting  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--roads", type=Path, required=True)
    pop = p.add_mutually_exclusive_group(required=True)
    pop.add_argument("--population", type=Path)
    pop.add_argument("--population-raster", type=Path)
    p.add_argument("--population-key", default="home_population_25m")
    p.add_argument("--shelters", type=Path, required=True)
    p.add_argument("--bbox", type=float, nargs=4, required=True, metavar=("WEST", "SOUTH", "EAST", "NORTH"))
    p.add_argument("--duration-minutes", type=int, default=120)
    p.add_argument("--magnitude", type=float, default=7.0)
    p.add_argument("--epicenter", type=float, nargs=2, required=True, metavar=("LON", "LAT"))
    p.add_argument("--k", type=int, default=5, help="Number of new shelters to place.")
    p.add_argument("--candidate-pool", type=int, default=30,
                   help="How many of the highest-population unserved blocks to consider as candidates.")
    p.add_argument("--new-shelter-capacity", type=float, default=5_000.0,
                   help="Assumed capacity for a new shelter, persons.")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()

    started = time.time()
    print("[1/4] extracting blocks + population ...")
    blocks, _, _ = blocks_from_geojson(args.roads, drop_highways=["motorway", "motorway_link"])
    blocks = clip_blocks(blocks, args.bbox)
    if not blocks:
        raise SystemExit("No blocks in --bbox")

    if args.population_raster:
        grid_population, centres, _ = grid_from_raster(args.population_raster, tuple(args.bbox))
    else:
        centres, grid_population = load_grid_population(args.population, args.population_key)
    result = disaggregate_population(blocks, grid_population, centres)
    for block in blocks:
        block.population = result["assigned"].get(block.block_id, 0.0)

    sim_config = BlockScaleConfig(
        city="siting-run", seed=args.seed, duration_minutes=args.duration_minutes,
        magnitude=args.magnitude, epicenter_lon=args.epicenter[0], epicenter_lat=args.epicenter[1],
    )
    layer = build_block_layer(blocks)
    base_shelters = load_shelters_geojson(args.shelters, sim_config)
    print(f"      {len(blocks):,} blocks, {len(base_shelters)} existing shelters, "
          f"population {layer.population.sum():,.0f}")

    print("[2/4] finding candidate sites (highest-population unserved blocks) ...")
    probe = BlockEvacuationSimulator(layer, base_shelters, sim_config)
    probe.run()
    unserved_idx = [i for i in range(len(layer)) if probe.unserved_mask[i]]
    unserved_idx.sort(key=lambda i: layer.population[i], reverse=True)
    pool = unserved_idx[:args.candidate_pool]
    candidates = [
        ShelterSite(f"NEW-{rank:03d}", f"candidate at block {layer.block_ids[i]}",
                   float(layer.lon[i]), float(layer.lat[i]), capacity=args.new_shelter_capacity,
                   provenance="candidate site under evaluation, not built")
        for rank, i in enumerate(pool)
    ]
    print(f"      {len(candidates)} candidates from {len(unserved_idx):,} unserved blocks "
          f"({float(layer.population[probe.unserved_mask].sum()):,.0f} people)")

    print(f"[3/4] greedy search for the best {args.k} of {len(candidates)} candidates "
          f"({args.k * len(candidates)} simulation runs) ...")
    result = greedy_shelter_siting(layer, base_shelters, candidates, sim_config, k=args.k)

    print("[4/4] writing report ...")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result.to_dict(), indent=2), encoding="utf-8")

    print()
    print("=" * 60)
    print(f"baseline unserved population   {result.baseline_unserved_population:,.0f}")
    print(f"final unserved population      {result.final_unserved_population:,.0f}")
    print(f"total reduction                {result.baseline_unserved_population - result.final_unserved_population:,.0f}")
    for step in result.steps:
        print(f"  #{step.rank} {step.shelter_id:<10} at ({step.lon:.4f},{step.lat:.4f})  "
              f"-{step.marginal_gain:,.0f} people")
    print("=" * 60)
    print(f"elapsed {time.time() - started:.1f}s")


if __name__ == "__main__":
    main()
