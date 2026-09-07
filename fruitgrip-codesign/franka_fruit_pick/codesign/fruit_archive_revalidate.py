"""Escalation 3 follow-up: re-validate FruitArchive's top cells at full
statistical power, PER OBJECT -- including apple, forced explicitly.

Necessary correction: fruit_archive.py evaluated each genotype on only 3
random trials drawn from a 4-object pool (banana/lemon/plum/apple), to keep
the ~500-evaluation search affordable. Checking the saved archive after the
run found that, by chance, ZERO of the 64 filled cells ever had apple drawn in
their 3-trial sample -- meaning the search's own results say nothing about
apple at all, despite that being this escalation's explicit named question
("does any cell solve the apple-style narrow-clearance failure mode"). This
script closes that gap: it re-evaluates the archive's top cells (and the
original frozen winner, for direct comparison) with 30 trials PER OBJECT,
forced via `force_pick_object`, not randomly pooled -- so apple gets a real,
adequately-powered answer.
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

from evaluate import evaluate_candidate  # noqa: E402
from gripper_gen import GripperParams  # noqa: E402
from run_attribution import BASELINE_PARAMS, JOINT_BEST_PARAMS  # noqa: E402
from confirmation_eval import wilson_ci  # noqa: E402
from fruit_archive import _patch_pool, _restore_pool  # noqa: E402

OBJECTS = ("011_banana", "014_lemon", "018_plum", "013_apple")
N_TRIALS = 30


def revalidate(label: str, params: GripperParams, seed_base: int, log_fn=print) -> dict:
    _patch_pool()
    try:
        per_object = {}
        for obj in OBJECTS:
            trial_seeds = tuple(seed_base + i for i in range(N_TRIALS))
            result = evaluate_candidate(params, trial_seeds=trial_seeds, force_pick_object=obj)
            successes = int(round(result.agg.success_rate * result.agg.n_trials))
            ci_lo, ci_hi = wilson_ci(successes, N_TRIALS)
            per_object[obj] = {
                "successes": successes, "n": N_TRIALS, "success_rate": result.agg.success_rate,
                "success_rate_95ci": [ci_lo, ci_hi], "mean_peak_force": result.agg.mean_peak_force,
            }
            log_fn(f"[{label}] {obj}: {successes}/{N_TRIALS} ({result.agg.success_rate:.1%})")
            seed_base += N_TRIALS
    finally:
        _restore_pool()
    return {"label": label, "params": vars(params), "per_object": per_object}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--archive", type=str, default=str(_ROOT.parent.parent / "results" / "06_fruit_archive_qd" / "fruit_archive.json"))
    ap.add_argument("--top-n", type=int, default=4)
    ap.add_argument("--seed-base", type=int, default=9000)
    ap.add_argument("--out", type=str, default=str(_ROOT.parent.parent / "results" / "06_fruit_archive_qd" / "fruit_archive_revalidation.json"))
    args = ap.parse_args()

    archive = json.loads(Path(args.archive).read_text())["archive"]
    top_cells = sorted(archive.items(), key=lambda kv: -kv[1]["fitness"])[: args.top_n]

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    results = []
    t0 = time.time()

    results.append(revalidate("frozen_winner", JOINT_BEST_PARAMS, args.seed_base))
    out_path.write_text(json.dumps(results, indent=2))
    results.append(revalidate("frozen_baseline", BASELINE_PARAMS, args.seed_base + 1000))
    out_path.write_text(json.dumps(results, indent=2))

    for i, (cell_key, cell) in enumerate(top_cells):
        params = GripperParams(**cell["params"]).clipped()
        label = f"archive_cell_{cell_key}_rank{i+1}"
        results.append(revalidate(label, params, args.seed_base + 2000 + i * 1000))
        out_path.write_text(json.dumps(results, indent=2))

    print(f"wrote {out_path} ({time.time()-t0:.1f}s total)")


if __name__ == "__main__":
    main()
