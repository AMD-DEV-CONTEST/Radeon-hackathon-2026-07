"""Session 5, Priority 7: expanded held-out generalization test.

Session 3's held-out eval (apple/pear) used n=20 total trials (8 apple, 12 pear) --
noisy given how few trials landed on each object. The batched pipeline (session 5,
Priority 6) makes a much larger trial count affordable, so this reruns the SAME
held-out objects (apple, pear -- deliberately not new object classes; see
rocm_findings.md's note on mustard_bottle/mug needing an explicit grasp-height meta
override this session didn't build and validate) at 10x the trial count, to get a
statistically solid picture of the winning geometry's actual clearance-limit boundary
rather than session 3's small-N estimate.
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

import genesis as gs  # noqa: E402

from confirmation_eval import wilson_ci  # noqa: E402
from evaluate import evaluate_candidate_batched  # noqa: E402
from held_out_eval import HELD_OUT_LAYOUT, HELD_OUT_POOL, activate_held_out_scene  # noqa: E402
from run_attribution import BASELINE_PARAMS, JOINT_BEST_PARAMS  # noqa: E402


def make_seeds_by_object(seed_base: int, n_per_object: int) -> dict[str, list[int]]:
    return {obj: list(range(seed_base + i * n_per_object, seed_base + (i + 1) * n_per_object)) for i, obj in enumerate(HELD_OUT_POOL)}


def run_one(params, *, n_per_object: int, seed_base: int, label: str, backend=None, log_fn=print) -> dict:
    seeds_by_object = make_seeds_by_object(seed_base, n_per_object)
    t0 = time.time()
    result = evaluate_candidate_batched(params, seeds_by_object, backend=backend)
    wall = time.time() - t0

    successes = sum(result.per_trial_success)
    n = len(result.per_trial_success)
    ci_lo, ci_hi = wilson_ci(successes, n)

    per_object: dict[str, list[bool]] = {}
    for obj, ok in zip(result.per_trial_pick_object, result.per_trial_success):
        per_object.setdefault(obj, []).append(bool(ok))
    per_object_stats = {}
    for obj, vals in per_object.items():
        s = sum(vals)
        lo, hi = wilson_ci(s, len(vals))
        per_object_stats[obj] = {"n": len(vals), "successes": s, "success_rate": s / len(vals), "ci_95": [lo, hi]}

    log_fn(f"{label}: n={n} success_rate={result.agg.success_rate:.3f} (95% CI [{ci_lo:.3f},{ci_hi:.3f}]) per_object={ {k: round(v['success_rate'],3) for k,v in per_object_stats.items()} } wall={wall:.1f}s")
    return {
        "label": label, "n_trials": n, "success_rate": result.agg.success_rate, "success_rate_95ci": [ci_lo, ci_hi],
        "mean_peak_force_N": result.agg.mean_peak_force, "mean_max_slip_m": result.agg.mean_max_slip,
        "per_object": per_object_stats, "wall_seconds": wall,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Expanded held-out generalization eval (batched, frozen designs).")
    ap.add_argument("--n-per-object", type=int, default=100)
    ap.add_argument("--backend", choices=["cpu", "amdgpu", "gpu", "cuda"], default="cpu")
    ap.add_argument("--out", type=str, default=str(_ROOT.parent.parent / "results" / "03_generalization" / "held_out_eval_expanded.json"))
    args = ap.parse_args()

    backend = {"cpu": gs.cpu, "amdgpu": gs.amdgpu, "gpu": gs.gpu, "cuda": gs.cuda}[args.backend]
    activate_held_out_scene()
    print(f"held-out scene: {list(HELD_OUT_LAYOUT)} pool={HELD_OUT_POOL} n_per_object={args.n_per_object} backend={args.backend}")

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    baseline = run_one(BASELINE_PARAMS, n_per_object=args.n_per_object, seed_base=9000, label="baseline", backend=backend)
    winner = run_one(JOINT_BEST_PARAMS, n_per_object=args.n_per_object, seed_base=9500, label="winner", backend=backend)

    results = {
        "n_per_object": args.n_per_object, "objects": list(HELD_OUT_POOL),
        "baseline": baseline, "winner": winner,
        "session3_reference": {"baseline_n20_success_rate": 0.0, "winner_n20_success_rate": 0.25, "winner_n20_per_object": {"016_pear": 0.417, "013_apple": 0.0}},
        "wall_seconds": time.time() - t0,
    }
    out_path.write_text(json.dumps(results, indent=2))
    print(f"\nwrote {out_path} ({results['wall_seconds']:.1f}s total)")


if __name__ == "__main__":
    main()
