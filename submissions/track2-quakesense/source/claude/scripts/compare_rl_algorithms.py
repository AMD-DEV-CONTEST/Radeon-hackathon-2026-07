#!/usr/bin/env python3
"""Compare three credit-assignment algorithms for the shelter admission-control
problem -- Monte Carlo control (the original SharedQLearningShelterAgents),
TD Q-learning, and SARSA (both via TDShelterAgents) -- on the identical
Naples data and objective, across three scenario variants:

    baseline        the standard run already reported elsewhere
    road_blockage   ~15% of blocks excluded from routing (debris/road
                    interruption), via BlockEvacuationSimulator's own
                    blocked_blocks mechanism
    slow_response   a labelled synthetic "night" proxy: departure_median_s
                    tripled (people take longer to start moving), NOT a
                    WorldMove-calibrated day/night effect -- see
                    ScenarioConfig.event_hour in simulator/model.py for the
                    equivalent, better-validated proxy on the individual-agent
                    model. This is a coarser stand-in for the block-scale
                    engine, which has no building-type population layer to
                    reweight the way the individual-agent model does.

Reuses the exact same blocks/population/shelters inputs as
scripts/train_shelter_agents.py.

Example
-------
    python scripts/compare_rl_algorithms.py \\
        --roads ../data/external/naples_roads.geojson \\
        --population-raster data/worldpop/ita_ppp_2020_1km_Aggregated_UNadj.tif \\
        --shelters ../data/multi_city/naples/shelters.geojson \\
        --bbox 14.14 40.79 14.35 40.92 \\
        --duration-minutes 180 --episodes 20 \\
        --epicenter 14.25 40.84 --magnitude 6.5 \\
        --output results_naples/rl_algorithm_comparison.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from geo.urban_blocks import blocks_from_geojson  # noqa: E402
from geo.population_raster import grid_from_raster  # noqa: E402
from rl.shelter_agents import ShelterAgentConfig, SharedQLearningShelterAgents, TDShelterAgents  # noqa: E402
from scripts.build_city_block_evacuation import clip_blocks, load_grid_population  # noqa: E402
from simulator.block_scale import BlockScaleConfig, ShelterSite, build_block_layer, load_shelters_geojson  # noqa: E402


def build_agent(name: str, cfg: ShelterAgentConfig):
    if name == "monte_carlo":
        return SharedQLearningShelterAgents(cfg)
    if name == "q_learning":
        return TDShelterAgents(cfg, algorithm="q_learning")
    if name == "sarsa":
        return TDShelterAgents(cfg, algorithm="sarsa")
    raise ValueError(name)


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
    p.add_argument("--duration-minutes", type=int, default=180)
    p.add_argument("--step-seconds", type=int, default=30)
    p.add_argument("--epoch-minutes", type=float, default=10.0)
    p.add_argument("--magnitude", type=float, default=6.5)
    p.add_argument("--epicenter", type=float, nargs=2, required=True, metavar=("LON", "LAT"))
    p.add_argument("--episodes", type=int, default=20)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument(
        "--resistance", type=Path,
        help=(
            "Optional per-block walking-resistance JSON from "
            "scripts/fetch_terrain_resistance.py (slope + land cover). Without it every "
            "block has resistance 1.0, i.e. the flat, uniform-terrain assumption used in "
            "all earlier runs."
        ),
    )
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()

    started = time.time()
    print("[1/3] extracting blocks + population ...")
    blocks, _, _ = blocks_from_geojson(args.roads, drop_highways=["motorway", "motorway_link"])
    blocks = clip_blocks(blocks, tuple(args.bbox))
    if not blocks:
        raise SystemExit("No blocks in --bbox")

    if args.population_raster:
        grid_population, centres, _ = grid_from_raster(args.population_raster, tuple(args.bbox))
    else:
        centres, grid_population = load_grid_population(args.population, args.population_key)
    from geo.urban_blocks import disaggregate_population
    result = disaggregate_population(blocks, grid_population, centres)
    for block in blocks:
        block.population = result["assigned"].get(block.block_id, 0.0)

    base_sim_config = BlockScaleConfig(
        city="rl-algorithm-comparison", seed=args.seed, step_seconds=args.step_seconds,
        duration_minutes=args.duration_minutes, target_population=args.target_population,
        magnitude=args.magnitude, epicenter_lon=args.epicenter[0], epicenter_lat=args.epicenter[1],
    )
    resistance_by_block = None
    if args.resistance:
        res_payload = json.loads(args.resistance.read_text(encoding="utf-8"))
        raw = res_payload["resistance_by_block"]
        # "Infinity" is the JSON-safe sentinel written by fetch_terrain_resistance.py
        # for land cover that is not crossable on foot (open water).
        resistance_by_block = {
            k: (float("inf") if v == "Infinity" else float(v)) for k, v in raw.items()
        }
        summary = res_payload.get("resistance_summary", {})
        print(f"      terrain resistance: {len(resistance_by_block):,} blocks, "
              f"median {summary.get('median')}, max {summary.get('max')}, "
              f"{summary.get('impassable_count')} impassable")

    layer = build_block_layer(blocks, resistance_by_block=resistance_by_block)
    if args.target_population:
        total = float(layer.population.sum())
        if total > 0:
            layer.population = layer.population * (args.target_population / total)
        base_sim_config.target_population = None

    shelter_sites = load_shelters_geojson(args.shelters, base_sim_config)
    print(f"      {len(blocks):,} blocks, {len(shelter_sites)} shelters, "
          f"population {int(layer.population.sum()):,}")

    def make_shelters() -> list[ShelterSite]:
        # Fresh ShelterSite instances each episode: the simulator mutates
        # `occupants` in place, and reusing objects across episodes would
        # carry over stale occupancy state (same pattern as
        # scripts/train_shelter_agents.py).
        return load_shelters_geojson(args.shelters, base_sim_config)

    n_blocked = max(1, round(len(layer) * 0.15))
    blocked_blocks = list(range(0, len(layer), max(1, len(layer) // n_blocked)))[:n_blocked]

    scenarios = {
        "baseline": {"sim_config": base_sim_config, "blocked_blocks": ()},
        "road_blockage": {"sim_config": base_sim_config, "blocked_blocks": blocked_blocks},
        "slow_response": {
            "sim_config": replace(base_sim_config, departure_median_s=base_sim_config.departure_median_s * 3),
            "blocked_blocks": (),
        },
    }

    report = {
        "episodes": args.episodes,
        "n_blocks": len(layer),
        "n_blocked_for_road_blockage": len(blocked_blocks),
        "terrain_resistance": (str(args.resistance) if args.resistance else None),
        "scenarios": {},
    }

    for scenario_name, scenario in scenarios.items():
        print(f"\n[2/3] scenario={scenario_name} ...")
        scenario_report = {"algorithms": {}}
        for algo_name in ("monte_carlo", "q_learning", "sarsa"):
            cfg = ShelterAgentConfig(seed=args.seed)
            agent = build_agent(algo_name, cfg)
            t0 = time.time()
            training = agent.train(
                layer, make_shelters, scenario["sim_config"],
                episodes=args.episodes, blocked_blocks=scenario["blocked_blocks"],
            )
            dt = time.time() - t0
            b, g = training.baseline_result, training.greedy_result
            print(f"      {algo_name:12s} reward base={training.baseline_reward:.4f} greedy={g.reward:.4f}   "
                  f"| P90 clearance base={b.clearance_p90_min}min greedy={g.clearance_p90_min}min "
                  f"| unserved base={b.unserved_fraction:.4f} greedy={g.unserved_fraction:.4f} ({dt:.1f}s)")
            scenario_report["algorithms"][algo_name] = training.to_dict()
        report["scenarios"][scenario_name] = scenario_report

    print("\n[3/3] writing report ...")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print("\n" + "=" * 108)
    print("OPERATIONAL OUTCOME MEASURES (greedy policy vs do-nothing baseline)")
    print("Note: `reward` is ~99.9% reroute-penalty by construction -- see the")
    print("rl/shelter_agents.py docstring. P90 clearance is the metric that")
    print("actually says whether people got to safety sooner.")
    print("-" * 108)
    print(f"{'scenario':15s} {'algorithm':12s} {'P90 base':>9s} {'P90 greedy':>11s} {'P90 delta':>10s} "
          f"{'P50 base':>9s} {'P50 greedy':>11s} {'unserv base':>12s} {'unserv greedy':>14s}")
    for scenario_name, scenario_report in report["scenarios"].items():
        for algo_name, d in scenario_report["algorithms"].items():
            b, g = d.get("baseline_outcome", {}), d.get("greedy_outcome", {})
            p90b, p90g = b.get("clearance_p90_min"), g.get("clearance_p90_min")
            delta = (f"{p90g - p90b:+.1f}" if (p90b is not None and p90g is not None) else "n/a")
            print(f"{scenario_name:15s} {algo_name:12s} {str(p90b):>9s} {str(p90g):>11s} {delta:>10s} "
                  f"{str(b.get('clearance_p50_min')):>9s} {str(g.get('clearance_p50_min')):>11s} "
                  f"{b.get('unserved_fraction', 0):>12.4f} {g.get('unserved_fraction', 0):>14.4f}")
    print("=" * 108)
    print("\nREWARD (training signal only -- dominated by the reroute term)")
    print(f"{'scenario':16s} {'algorithm':12s} {'base':>10s} {'greedy':>10s} {'delta':>10s}")
    for scenario_name, scenario_report in report["scenarios"].items():
        for algo_name, d in scenario_report["algorithms"].items():
            gr = d.get("greedy_outcome", {}).get("reward")
            delta = (f"{gr - d['baseline_reward']:+.4f}" if gr is not None else "n/a")
            print(f"{scenario_name:16s} {algo_name:12s} {d['baseline_reward']:>10.4f} "
                  f"{(gr if gr is not None else float('nan')):>10.4f} {delta:>10s}")
    print("=" * 70)
    print(f"elapsed {time.time()-started:.1f}s")


if __name__ == "__main__":
    main()
