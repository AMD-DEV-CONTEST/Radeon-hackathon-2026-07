"""Attribution experiment (project brief S7): how much of the co-design gain comes
from the body, how much from the controller, and how much is interaction/synergy.

Four arms, all scored with the identical evaluate_candidate() path and the identical
fixed trial-instance set (S6/A4 -- an asymmetry here would invalidate the whole
comparison):

  A. baseline    -- fixed geometry (stock-equivalent), fixed controller
  B. geometry    -- SEARCHED geometry, controller held fixed at baseline
                     (controller_adapt.BASELINE_CONTROLLER, not the analytic
                     compliance->force co-adaptation the joint search uses)
  C. controller  -- geometry held fixed at baseline, SEARCHED controller
                     (close_force, height_offset)
  D. joint       -- both searched together (already computed in run_search.py's
                     scaled run -- re-evaluated here fresh, not parsed from the old
                     JSON, so all four numbers come from one self-consistent run)

geometry_gain    = best(B) - A
controller_gain  = best(C) - A
joint_gain       = best(D) - A
interaction      = joint_gain - geometry_gain - controller_gain

Search budgets for B and C are matched by total evaluation count (not per-branch
population), which is the fair way to compare "how much can search buy you" across
spaces of different dimensionality.
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

from controller_adapt import BASELINE_CONTROLLER  # noqa: E402
from evaluate import DEFAULT_TRIAL_SEEDS, evaluate_candidate  # noqa: E402
from gripper_gen import GripperParams  # noqa: E402
from paths import OUTPUTS_DIR  # noqa: E402
from search import run_controller_search, run_search  # noqa: E402

BASELINE_PARAMS = GripperParams(n_fingers=2, finger_length=0.0454, curvature_deg=0.0, aperture=0.08, compliance=0.0)

# The joint arm's winner from the already-completed scaled search (population=5,
# generations=5, both finger-count branches; see outputs/codesign_search/results_scaled.json),
# re-evaluated fresh below rather than parsed from that file, so arm D is produced by
# the exact same code path as A/B/C in this run.
JOINT_BEST_PARAMS = GripperParams(
    n_fingers=3, finger_length=0.04617883576142882, curvature_deg=4.203232665740063,
    aperture=0.09122108937742585, compliance=0.2337742993191176,
)


def _fmt(res) -> str:
    return f"fitness={res.fitness:.3f} success={res.agg.success_rate:.2f} force={res.agg.mean_peak_force:.1f}N slip={res.agg.mean_max_slip*1000:.0f}mm"


def run_one_attribution(
    *, trial_seeds: tuple[int, ...], geom_population: int, geom_generations: int,
    ctrl_population: int, ctrl_generations: int, cma_seed_offset: int = 0, log_fn=print,
) -> dict:
    """One full run of the 4-arm attribution experiment under a given trial-instance
    seed set. `cma_seed_offset` shifts every CMA-ES optimizer's own internal RNG seed
    (not just the trial instances) so a multi-seed rerun (run_attribution_multiseed.py)
    varies both what tasks are evaluated on AND the search trajectory itself -- not
    just one of the two, which would understate the true run-to-run variance.
    """
    t0 = time.time()

    log_fn("=== A: baseline (fixed geometry, fixed controller) ===")
    baseline = evaluate_candidate(BASELINE_PARAMS, trial_seeds=trial_seeds)
    log_fn(f"A: {_fmt(baseline)}")

    log_fn("\n=== B: geometry-only (SEARCH geometry, controller FIXED at baseline) ===")
    geom_branches = run_search(
        population=geom_population, generations=geom_generations, trial_seeds=trial_seeds,
        finger_counts=(2, 3), controller=BASELINE_CONTROLLER, log_fn=log_fn, cma_seed_offset=cma_seed_offset,
    )
    geom_best = max((b.best for b in geom_branches.values() if b.best is not None), key=lambda r: r.fitness)
    log_fn(f"B best: {_fmt(geom_best)}  ({geom_best.params})")

    log_fn("\n=== C: controller-only (geometry FIXED at baseline, SEARCH controller) ===")
    ctrl_branch = run_controller_search(
        BASELINE_PARAMS, population=ctrl_population, generations=ctrl_generations, trial_seeds=trial_seeds,
        seed=100 + cma_seed_offset, log_fn=log_fn,
    )
    ctrl_best = ctrl_branch.best
    ctrl_best_controller = ctrl_branch.best_controller
    log_fn(f"C best: {_fmt(ctrl_best)}  (close_force={ctrl_best_controller.close_force:.2f}N height_offset={ctrl_best_controller.height_offset*1000:.1f}mm)")

    log_fn("\n=== D: joint (re-evaluating the already-found scaled-search winner under THIS seed set's trials) ===")
    joint_best = evaluate_candidate(JOINT_BEST_PARAMS, trial_seeds=trial_seeds)
    log_fn(f"D: {_fmt(joint_best)}  ({joint_best.params})")

    geometry_gain = geom_best.fitness - baseline.fitness
    controller_gain = ctrl_best.fitness - baseline.fitness
    joint_gain = joint_best.fitness - baseline.fitness
    interaction = joint_gain - geometry_gain - controller_gain
    total_explainable = geometry_gain + controller_gain
    geometry_share = geometry_gain / total_explainable if total_explainable != 0 else float("nan")
    controller_share = controller_gain / total_explainable if total_explainable != 0 else float("nan")

    log_fn("\n=== attribution (this seed set) ===")
    log_fn(f"baseline fitness:            {baseline.fitness:.3f}")
    log_fn(f"geometry-only best:          {geom_best.fitness:.3f}  (gain {geometry_gain:+.3f})")
    log_fn(f"controller-only best:        {ctrl_best.fitness:.3f}  (gain {controller_gain:+.3f})")
    log_fn(f"joint best:                  {joint_best.fitness:.3f}  (gain {joint_gain:+.3f})")
    log_fn(f"interaction (joint - geom - ctrl): {interaction:+.3f}")
    log_fn(f"of the additive (geom+ctrl) gain: geometry share = {geometry_share:.0%}, controller share = {controller_share:.0%}")

    return {
        "trial_seeds": list(trial_seeds),
        "baseline": {"params": vars(baseline.params), "fitness": baseline.fitness, "agg": vars(baseline.agg)},
        "geometry_only_best": {"params": vars(geom_best.params), "fitness": geom_best.fitness, "agg": vars(geom_best.agg)},
        "controller_only_best": {"controller": vars(ctrl_best_controller), "fitness": ctrl_best.fitness, "agg": vars(ctrl_best.agg)},
        "joint_best": {"params": vars(joint_best.params), "fitness": joint_best.fitness, "agg": vars(joint_best.agg)},
        "geometry_gain": geometry_gain, "controller_gain": controller_gain, "joint_gain": joint_gain,
        "interaction": interaction, "geometry_share": geometry_share, "controller_share": controller_share,
        "wall_seconds": time.time() - t0,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Attribution experiment: geometry vs controller gain split.")
    ap.add_argument("--geom-population", type=int, default=4)
    ap.add_argument("--geom-generations", type=int, default=4)
    ap.add_argument("--ctrl-population", type=int, default=8)
    ap.add_argument("--ctrl-generations", type=int, default=4)
    ap.add_argument("--out", type=str, default=str(OUTPUTS_DIR / "codesign_search" / "attribution.json"))
    args = ap.parse_args()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    results = run_one_attribution(
        trial_seeds=DEFAULT_TRIAL_SEEDS, geom_population=args.geom_population, geom_generations=args.geom_generations,
        ctrl_population=args.ctrl_population, ctrl_generations=args.ctrl_generations,
    )
    out_path.write_text(json.dumps(results, indent=2))
    print(f"\nwrote {out_path} ({results['wall_seconds']:.1f}s total)")


if __name__ == "__main__":
    main()
