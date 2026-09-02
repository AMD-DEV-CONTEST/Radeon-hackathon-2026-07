#!/usr/bin/env python3
"""Train the shared-Q-table shelter admission controller on a real city.

Reuses the exact same blocks/population/shelters inputs as
``build_city_block_evacuation.py`` -- this is validation on the real,
already-checked-in pipeline, not a synthetic RL benchmark.

Example
-------
    python scripts/train_shelter_agents.py \\
        --roads data/external/naples_roads.geojson \\
        --population-raster data/worldpop/ita_ppp_2020_1km_Aggregated_UNadj.tif \\
        --shelters data/multi_city/naples/shelters.geojson \\
        --bbox 14.14 40.79 14.35 40.92 \\
        --duration-minutes 180 --episodes 20 \\
        --epicenter 14.25 40.84 --magnitude 6.5 \\
        --output results_naples/shelter_agents_report.json
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
from rl.shelter_agents import ShelterAgentConfig, SharedQLearningShelterAgents  # noqa: E402
from scripts.build_city_block_evacuation import clip_blocks, load_grid_population  # noqa: E402
from simulator.block_scale import BlockScaleConfig, build_block_layer, load_shelters_geojson  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--roads", type=Path, required=True)
    pop = p.add_mutually_exclusive_group(required=True)
    pop.add_argument("--population", type=Path)
    pop.add_argument("--population-raster", type=Path)
    p.add_argument("--population-key", default="home_population_25m")
    p.add_argument("--shelters", type=Path, required=True)
    p.add_argument("--bbox", type=float, nargs=4, required=True, metavar=("WEST", "SOUTH", "EAST", "NORTH"))
    p.add_argument("--target-population", type=int)
    p.add_argument("--duration-minutes", type=int, default=120)
    p.add_argument("--step-seconds", type=int, default=30)
    p.add_argument("--epoch-minutes", type=float, default=10.0)
    p.add_argument("--magnitude", type=float, default=7.0)
    p.add_argument("--epicenter", type=float, nargs=2, required=True, metavar=("LON", "LAT"))
    p.add_argument("--episodes", type=int, default=20)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()

    started = time.time()
    print("[1/3] extracting blocks + population ...")
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
        city="training-run", seed=args.seed, step_seconds=args.step_seconds,
        duration_minutes=args.duration_minutes, target_population=args.target_population,
        magnitude=args.magnitude, epicenter_lon=args.epicenter[0], epicenter_lat=args.epicenter[1],
    )
    layer = build_block_layer(blocks)
    if args.target_population:
        # Rescale once, up front, so repeated BlockEvacuationSimulator(layer, ...)
        # construction inside training doesn't compound the rescale.
        total = float(layer.population.sum())
        if total > 0:
            layer.population = layer.population * (args.target_population / total)
        sim_config.target_population = None

    base_shelters_template = load_shelters_geojson(args.shelters, sim_config)
    print(f"      {len(blocks):,} blocks, {len(base_shelters_template)} shelters, "
          f"population {layer.population.sum():,.0f}")

    def make_shelters():
        # Fresh ShelterSite instances each episode: the simulator mutates
        # `occupants` in place, and reusing objects across episodes would
        # carry over stale occupancy state.
        return load_shelters_geojson(args.shelters, sim_config)

    print(f"[2/3] training {args.episodes} episodes "
          f"(each is a full {args.duration_minutes}-minute simulation run) ...")
    agents = SharedQLearningShelterAgents(ShelterAgentConfig(epoch_minutes=args.epoch_minutes, seed=args.seed))
    report = agents.train(layer, make_shelters, sim_config, episodes=args.episodes)

    # The training reward history includes exploration noise even in its
    # final episodes (epsilon anneals toward epsilon_end, not to zero), so it
    # is not a fair read of what the learned policy actually does. Evaluate
    # the converged table acting purely greedily, separately.
    greedy_eval = agents.run_episode(layer, make_shelters(), sim_config, train=False)

    print("[3/3] writing report ...")
    payload = report.to_dict()
    payload["greedy_policy_evaluation"] = {
        "reward": round(greedy_eval.reward, 5),
        "unserved_fraction": round(greedy_eval.unserved_fraction, 5),
        "reroute_events": greedy_eval.reroute_events,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    agents.save(args.output.with_name(args.output.stem + "_qtable.json"))

    print()
    print("=" * 60)
    print(f"baseline reward (cutoff always 1.0)   {report.baseline_reward:.5f}")
    print(f"mean reward, first 10 episodes (w/ exploration)  {report.mean_reward_first_10:.5f}")
    print(f"mean reward, last 10 episodes (w/ exploration)   {report.mean_reward_last_10:.5f}")
    print(f"learned policy, greedy (no exploration)          {greedy_eval.reward:.5f}")
    print(f"learned vs baseline                              {greedy_eval.reward - report.baseline_reward:+.5f}")
    print(f"Q-table states learned                {report.q_states}")
    print("=" * 60)
    print(f"elapsed {time.time() - started:.1f}s")


if __name__ == "__main__":
    main()
