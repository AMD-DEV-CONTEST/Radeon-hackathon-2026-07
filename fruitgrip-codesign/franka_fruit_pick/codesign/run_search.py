"""CLI entry point: baseline comparison + population search + A1/A2 diagnostics.

This is the "small local CPU validation run" -- it exists to prove the pipeline is
correct end-to-end and to get an early read on the search, not to produce a
throughput claim (see the project's compute-target decision: this machine has no
ROCm-capable GPU). Every number this script prints is honestly a CPU number.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

_ROOT = Path(__file__).resolve().parent
if str(_ROOT.parent) not in sys.path:
    sys.path.insert(0, str(_ROOT.parent))

import numpy as np  # noqa: E402

from evaluate import DEFAULT_TRIAL_SEEDS, evaluate_candidate  # noqa: E402
from gripper_gen import GripperParams  # noqa: E402
from paths import OUTPUTS_DIR  # noqa: E402
from search import run_search  # noqa: E402

BASELINE_PARAMS = GripperParams(n_fingers=2, finger_length=0.0454, curvature_deg=0.0, aperture=0.08, compliance=0.0)


def _result_to_dict(params: GripperParams, fitness: float, agg) -> dict:
    return {
        "n_fingers": params.n_fingers, "finger_length": params.finger_length,
        "curvature_deg": params.curvature_deg, "aperture": params.aperture, "compliance": params.compliance,
        "fitness": fitness, "success_rate": agg.success_rate, "mean_contact_uptime": agg.mean_contact_uptime,
        "mean_peak_force": agg.mean_peak_force, "mean_max_slip": agg.mean_max_slip,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Small local (CPU) validation run of the co-design search.")
    ap.add_argument("--population", type=int, default=4)
    ap.add_argument("--generations", type=int, default=2)
    ap.add_argument("--out", type=str, default=str(OUTPUTS_DIR / "codesign_search" / "results.json"))
    args = ap.parse_args()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    print("=== baseline (stock-equivalent 2-finger, straight, rigid) ===")
    baseline = evaluate_candidate(BASELINE_PARAMS, trial_seeds=DEFAULT_TRIAL_SEEDS)
    print(
        f"baseline -> success={baseline.agg.success_rate:.2f} fitness={baseline.fitness:.3f} "
        f"peak_force={baseline.agg.mean_peak_force:.2f}N slip={baseline.agg.mean_max_slip*1000:.1f}mm"
    )

    branches = run_search(population=args.population, generations=args.generations, trial_seeds=DEFAULT_TRIAL_SEEDS)

    results = {
        "trial_seeds": list(DEFAULT_TRIAL_SEEDS),
        "wall_seconds": None,
        "baseline": _result_to_dict(BASELINE_PARAMS, baseline.fitness, baseline.agg),
        "branches": {},
    }

    print("\n=== summary ===")
    print(f"baseline: fitness={baseline.fitness:.3f} success={baseline.agg.success_rate:.2f}")
    for nf, branch in branches.items():
        entries = branch.log
        fitnesses = [e.fitness for e in entries]
        print(f"\nbranch n_fingers={nf}: {len(entries)} candidates evaluated")
        print(f"  fitness range: [{min(fitnesses):.3f}, {max(fitnesses):.3f}], mean={np.mean(fitnesses):.3f}")
        if branch.best is not None:
            b = branch.best
            print(
                f"  BEST: {b.params} -> fitness={b.fitness:.3f} (baseline delta: {b.fitness - baseline.fitness:+.3f}) "
                f"success={b.agg.success_rate:.2f} peak_force={b.agg.mean_peak_force:.2f}N slip={b.agg.mean_max_slip*1000:.1f}mm"
            )
        # A2 diagnostic: parameter-space spread across this branch's evaluated candidates
        # (a collapsed search would show near-zero spread here).
        param_matrix = np.array([[e.params.finger_length, e.params.curvature_deg, e.params.aperture, e.params.compliance] for e in entries])
        spread = param_matrix.std(axis=0)
        print(f"  param std-dev (length, curvature, aperture, compliance): {spread}")

        results["branches"][str(nf)] = {
            "log": [
                {**_result_to_dict(e.params, e.fitness, SimpleNamespace(**e.agg)), "generation": e.generation, "niched_fitness": e.niched_fitness}
                for e in entries
            ],
            "best": _result_to_dict(branch.best.params, branch.best.fitness, branch.best.agg) if branch.best else None,
            "param_std_dev": spread.tolist(),
        }

    results["wall_seconds"] = time.time() - t0
    out_path.write_text(json.dumps(results, indent=2))
    print(f"\nwrote {out_path} ({results['wall_seconds']:.1f}s total)")


if __name__ == "__main__":
    main()
