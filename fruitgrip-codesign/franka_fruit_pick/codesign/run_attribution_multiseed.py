"""Robustness pass (session 2, item 2): the 86%/14% geometry/controller split was
from ONE trial-seed set, and baseline fitness already showed 0.475-0.530 run-to-run
noise from solver nondeterminism at that same seed set. This reruns the full 4-arm
attribution experiment (run_attribution.run_one_attribution) across 5 independent
seed sets -- both the trial instances AND each CMA-ES optimizer's own internal seed
vary per rerun, so this captures both "does the specific task draw matter" and "does
the specific search trajectory matter" -- at the SAME per-arm search budget used to
produce the original 86/14 result (geom: population=5 generations=5 both finger
counts; ctrl: population=5 generations=5), then reports mean +/- std per arm rather
than a single point estimate.

Also explicitly tracks, per seed, whether arm C (controller-only) ever exceeded arm
A's (baseline) success rate -- this is a precise causal claim ("did tuning the
controller alone ever break the success ceiling") that must not be softened into an
average across seeds.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT.parent) not in sys.path:
    sys.path.insert(0, str(_ROOT.parent))

import numpy as np  # noqa: E402

from run_attribution import run_one_attribution  # noqa: E402

# 5 independent trial-instance seed sets (disjoint from each other and from the
# original single-seed run's (100, 101, 102)), each a 3-seed tuple matching the
# original trial count per candidate.
SEED_SETS = [
    (100, 101, 102),
    (200, 201, 202),
    (300, 301, 302),
    (400, 401, 402),
    (500, 501, 502),
]


def main() -> None:
    ap = argparse.ArgumentParser(description="5-seed rerun of the geometry/controller attribution experiment.")
    ap.add_argument("--geom-population", type=int, default=5)
    ap.add_argument("--geom-generations", type=int, default=5)
    ap.add_argument("--ctrl-population", type=int, default=5)
    ap.add_argument("--ctrl-generations", type=int, default=5)
    ap.add_argument("--out", type=str, default=str(_ROOT.parent.parent / "results" / "02_attribution_multiseed" / "attribution_multiseed.json"))
    args = ap.parse_args()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    runs = []
    for i, seeds in enumerate(SEED_SETS):
        print(f"\n{'#'*70}\n# SEED SET {i+1}/{len(SEED_SETS)}: trial_seeds={seeds} cma_seed_offset={i*100}\n{'#'*70}")
        r = run_one_attribution(
            trial_seeds=seeds, geom_population=args.geom_population, geom_generations=args.geom_generations,
            ctrl_population=args.ctrl_population, ctrl_generations=args.ctrl_generations, cma_seed_offset=i * 100,
        )
        runs.append(r)
        # Write incrementally after each seed so a killed/crashed run still leaves
        # partial, usable results instead of nothing.
        partial = {"completed_seed_sets": i + 1, "total_seed_sets": len(SEED_SETS), "runs": runs}
        out_path.write_text(json.dumps(partial, indent=2))

    def arr(path_fn):
        return np.array([path_fn(r) for r in runs])

    baseline_fitness = arr(lambda r: r["baseline"]["fitness"])
    baseline_success = arr(lambda r: r["baseline"]["agg"]["success_rate"])
    geom_fitness = arr(lambda r: r["geometry_only_best"]["fitness"])
    geom_success = arr(lambda r: r["geometry_only_best"]["agg"]["success_rate"])
    ctrl_fitness = arr(lambda r: r["controller_only_best"]["fitness"])
    ctrl_success = arr(lambda r: r["controller_only_best"]["agg"]["success_rate"])
    joint_fitness = arr(lambda r: r["joint_best"]["fitness"])
    joint_success = arr(lambda r: r["joint_best"]["agg"]["success_rate"])
    geometry_share = arr(lambda r: r["geometry_share"])
    controller_share = arr(lambda r: r["controller_share"])
    interaction = arr(lambda r: r["interaction"])

    # Precise causal check (item 4): per-seed, did controller-only ever beat baseline's
    # success rate? Not averaged -- reported per seed, explicitly.
    ctrl_beats_baseline = [bool(c > b) for c, b in zip(ctrl_success, baseline_success)]
    ctrl_ties_baseline = [bool(abs(c - b) < 1e-9) for c, b in zip(ctrl_success, baseline_success)]

    def stats(name, a):
        return {"name": name, "mean": float(a.mean()), "std": float(a.std(ddof=1)), "min": float(a.min()), "max": float(a.max()), "values": a.tolist()}

    summary = {
        "baseline_fitness": stats("baseline_fitness", baseline_fitness),
        "baseline_success": stats("baseline_success", baseline_success),
        "geometry_only_fitness": stats("geometry_only_fitness", geom_fitness),
        "geometry_only_success": stats("geometry_only_success", geom_success),
        "controller_only_fitness": stats("controller_only_fitness", ctrl_fitness),
        "controller_only_success": stats("controller_only_success", ctrl_success),
        "joint_fitness": stats("joint_fitness", joint_fitness),
        "joint_success": stats("joint_success", joint_success),
        "geometry_share": stats("geometry_share", geometry_share),
        "controller_share": stats("controller_share", controller_share),
        "interaction": stats("interaction", interaction),
        "controller_only_beats_baseline_per_seed": ctrl_beats_baseline,
        "controller_only_ties_baseline_per_seed": ctrl_ties_baseline,
        "controller_only_beats_baseline_count": sum(ctrl_beats_baseline),
        "n_seeds": len(SEED_SETS),
    }

    print(f"\n{'='*70}\n=== 5-SEED SUMMARY ===\n{'='*70}")
    for key in ["baseline_success", "geometry_only_success", "controller_only_success", "joint_success"]:
        s = summary[key]
        print(f"{key}: mean={s['mean']:.3f} std={s['std']:.3f} range=[{s['min']:.3f}, {s['max']:.3f}] values={[round(v,3) for v in s['values']]}")
    print(f"geometry_share: mean={summary['geometry_share']['mean']:.1%} std={summary['geometry_share']['std']:.1%} values={[f'{v:.0%}' for v in summary['geometry_share']['values']]}")
    print(f"controller_share: mean={summary['controller_share']['mean']:.1%} std={summary['controller_share']['std']:.1%} values={[f'{v:.0%}' for v in summary['controller_share']['values']]}")
    print(f"interaction: mean={summary['interaction']['mean']:+.3f} std={summary['interaction']['std']:.3f}")
    print(f"controller-only beat baseline's success rate in {summary['controller_only_beats_baseline_count']}/{len(SEED_SETS)} seeds: {ctrl_beats_baseline}")

    final = {"seed_sets": SEED_SETS, "runs": runs, "summary": summary, "wall_seconds": time.time() - t0}
    out_path.write_text(json.dumps(final, indent=2))
    print(f"\nwrote {out_path} ({final['wall_seconds']:.1f}s total)")


if __name__ == "__main__":
    main()
