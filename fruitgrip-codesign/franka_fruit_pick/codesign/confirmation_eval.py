"""Confirmation eval (robustness pass, session 2): the headline 67%-vs-100% success
numbers came from small-N search trials (n=3 per candidate), which is not a real
success-rate estimate. This script freezes the winning design and the baseline
(no further searching -- both GripperParams are copied verbatim from
run_attribution.py's BASELINE_PARAMS / JOINT_BEST_PARAMS) and re-evaluates each over
a much larger, fixed, paired trial-instance set to get a defensible success-rate
estimate with a confidence interval, plus force/slip distributions.

Paired comparison: both designs face the *same* trial-seed set (same objects, same
pose jitter, same friction/mass draws per trial index) -- the standard way to reduce
comparison variance beyond what an unpaired sample of the same size would give (S6/A4).
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT.parent) not in sys.path:
    sys.path.insert(0, str(_ROOT.parent))

import numpy as np  # noqa: E402

from evaluate import evaluate_candidate  # noqa: E402
from paths import OUTPUTS_DIR  # noqa: E402
from run_attribution import BASELINE_PARAMS, JOINT_BEST_PARAMS  # noqa: E402


def wilson_ci(successes: int, n: int, z: float = 1.959963984540054) -> tuple[float, float]:
    """95% Wilson score interval for a binomial proportion -- unlike the naive normal
    approximation, it stays inside [0, 1] and is well-behaved near p=0 or p=1 (the
    winning design's success rate is expected to sit right at/near 100%, where a naive
    Wald interval can report a nonsensical upper bound above 1.0).
    """
    if n == 0:
        return (0.0, 0.0)
    p = successes / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
    return (max(0.0, center - half), min(1.0, center + half))


def run_confirmation(params, *, n_trials: int, seed_base: int, label: str, log_fn=print) -> dict:
    trial_seeds = tuple(seed_base + i for i in range(n_trials))
    t0 = time.time()
    # evaluate_candidate builds the scene once and reuses it across all trial_seeds
    # internally, so this is one build + n_trials cheap resets, not n_trials builds.
    result = evaluate_candidate(params, trial_seeds=trial_seeds)
    wall = time.time() - t0

    successes = int(round(result.agg.success_rate * result.agg.n_trials))
    ci_lo, ci_hi = wilson_ci(successes, result.agg.n_trials)
    force = np.array(result.per_trial_peak_force)
    slip = np.array(result.per_trial_max_slip)

    log_fn(
        f"{label}: n={result.agg.n_trials} successes={successes} "
        f"success_rate={result.agg.success_rate:.3f} (95% CI [{ci_lo:.3f}, {ci_hi:.3f}]) "
        f"peak_force={force.mean():.2f}+/-{force.std(ddof=1):.2f}N max_slip={slip.mean()*1000:.1f}+/-{slip.std(ddof=1)*1000:.1f}mm "
        f"wall={wall:.1f}s"
    )
    return {
        "label": label, "params": vars(params), "trial_seeds": list(trial_seeds),
        "n_trials": result.agg.n_trials, "successes": successes, "success_rate": result.agg.success_rate,
        "success_rate_95ci": [ci_lo, ci_hi],
        "mean_contact_uptime": result.agg.mean_contact_uptime,
        "mean_peak_force_N": float(force.mean()), "std_peak_force_N": float(force.std(ddof=1)),
        "mean_max_slip_m": float(slip.mean()), "std_max_slip_m": float(slip.std(ddof=1)),
        "per_trial_success": result.per_trial_success, "per_trial_pick_object": result.per_trial_pick_object,
        "per_trial_peak_force_N": result.per_trial_peak_force, "per_trial_max_slip_m": result.per_trial_max_slip,
        "wall_seconds": wall,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Confirmation eval: frozen winner vs baseline, >=30 trials each.")
    ap.add_argument("--n-trials", type=int, default=30)
    ap.add_argument("--seed-base-winner", type=int, default=1000)
    ap.add_argument("--seed-base-baseline", type=int, default=1000)  # same base -> paired trial instances
    ap.add_argument("--out", type=str, default=str(_ROOT.parent.parent / "results" / "01_core_confirmation" / "confirmation_eval.json"))
    args = ap.parse_args()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    print(f"=== baseline (frozen, n={args.n_trials}) ===")
    baseline = run_confirmation(BASELINE_PARAMS, n_trials=args.n_trials, seed_base=args.seed_base_baseline, label="baseline")

    print(f"\n=== winner (frozen 3-finger, n={args.n_trials}) ===")
    winner = run_confirmation(JOINT_BEST_PARAMS, n_trials=args.n_trials, seed_base=args.seed_base_winner, label="winner")

    print("\n=== paired comparison ===")
    print(f"baseline: {baseline['success_rate']:.1%} (95% CI [{baseline['success_rate_95ci'][0]:.1%}, {baseline['success_rate_95ci'][1]:.1%}])")
    print(f"winner:   {winner['success_rate']:.1%} (95% CI [{winner['success_rate_95ci'][0]:.1%}, {winner['success_rate_95ci'][1]:.1%}])")
    ci_overlap = not (winner["success_rate_95ci"][0] > baseline["success_rate_95ci"][1] or baseline["success_rate_95ci"][0] > winner["success_rate_95ci"][1])
    print(f"95% CIs {'OVERLAP' if ci_overlap else 'do NOT overlap'} -> gap is {'not necessarily' if ci_overlap else ''} statistically distinguishable at this N")

    results = {
        "baseline": baseline, "winner": winner, "ci_overlap": ci_overlap,
        "force_delta_N": winner["mean_peak_force_N"] - baseline["mean_peak_force_N"],
        "slip_delta_m": winner["mean_max_slip_m"] - baseline["mean_max_slip_m"],
        "wall_seconds": time.time() - t0,
    }
    out_path.write_text(json.dumps(results, indent=2))
    print(f"\nwrote {out_path} ({results['wall_seconds']:.1f}s total)")


if __name__ == "__main__":
    main()
