"""Escalation 3 (session 8): quality-diversity (MAP-Elites) archive over the
gripper design space -- an illumination search rather than the project's usual
single-objective CMA-ES (search.py), to map out which (aperture, curvature)
regions perform best, and specifically to check whether ANY region solves the
apple-style narrow-clearance failure mode better than the single frozen winner
does.

SCALE, EXPLICITLY REDUCED FROM THE BRIEF: the full brief asked for "tens of
thousands of evaluations." Each evaluation here needs a fresh Genesis scene
build for a new gripper geometry (~18-20s) plus a few trial episodes -- at that
per-evaluation cost, tens of thousands of evaluations is a multi-day job on
this machine (a personal desktop, not a cluster; see friction_sweep_genesis.py
and ycb_generalization_eval.py's own scale-reduction notes for the same
underlying constraint). Per an explicit check-in this session, this instead
targets ~500 evaluations -- roughly the ORIGINAL project's own hackathon-scale
search budget (population=5, generations=5 branches, ~25 evaluations per
branch), not the "research scale" the brief describes. Reported honestly as
reduced-scale throughout, not as a full realization of the brief's ask.

Behavior descriptors: (aperture, curvature_deg) -- chosen (not finger_count)
because Escalation 2's ycb_generalization_findings.md found these are the two
parameters that visibly separated winner-favored (round, wide-aperture-
friendly) from baseline-favored (flat-faced, straight-finger-friendly)
objects; finger_count is left as a free (non-binned) dimension the search can
still vary within each cell, same as search.py's own "outer loop over
n_fingers" treatment.

Fitness objects: banana/lemon/plum (the original search's own set) PLUS apple
-- added specifically because the brief calls out checking whether any archive
cell solves the "apple-style narrow-clearance failure mode" better than the
single frozen winner. The other 32 objects from Escalation 2's broader set are
NOT included as fitness objects here: 20 of 36 scored 0% for both existing
designs there (a controller limitation, not a geometry one -- adding them
would just slow every evaluation down without giving the search useful
gradient). Apple's layout position is copied verbatim from scene_config.py's
own pre-existing (commented-out) entry, not invented here.
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

import scene_config  # noqa: E402
import build_scene as build_scene_mod  # noqa: E402
import randomize as randomize_mod  # noqa: E402

from evaluate import evaluate_candidate  # noqa: E402
from gripper_gen import (  # noqa: E402
    APERTURE_BOUNDS, COMPLIANCE_BOUNDS, CURVATURE_DEG_BOUNDS, FINGER_LENGTH_BOUNDS,
    FINGER_COUNT_CHOICES, GripperParams,
)
from run_attribution import BASELINE_PARAMS, JOINT_BEST_PARAMS  # noqa: E402

# -- fitness object pool: original 3 + apple -------------------------------
_APPLE_ENTRY = {"013_apple": {"pos": (0.45, 0.28, 0.0), "euler": (0.0, 0.0, 0.0), "friction": 1.0}}
_ORIG_YCB_LAYOUT = dict(scene_config.YCB_LAYOUT)
_ARCHIVE_YCB_LAYOUT = {**_ORIG_YCB_LAYOUT, **_APPLE_ENTRY}
_ORIG_POOL = randomize_mod.RELIABLE_PICK_POOL
_ARCHIVE_POOL = _ORIG_POOL + ("013_apple",)

TRIAL_SEEDS = (100, 101, 102)  # matches evaluate.DEFAULT_TRIAL_SEEDS / search.py's own convention

# -- archive binning ---------------------------------------------------------
N_BINS = 8  # 8x8 = 64 cells
APERTURE_EDGES = np.linspace(*APERTURE_BOUNDS, N_BINS + 1)
CURVATURE_EDGES = np.linspace(*CURVATURE_DEG_BOUNDS, N_BINS + 1)

MUTATION_SIGMA = 0.12  # unit-scale gaussian mutation std (search.py's CMA-ES sigma0=0.3 is population-search scale; this is a smaller local-mutation step, standard MAP-Elites practice)
FINGER_FLIP_PROB = 0.15


def _bin_index(params: GripperParams) -> tuple[int, int]:
    a_bin = int(np.clip(np.searchsorted(APERTURE_EDGES, params.aperture, side="right") - 1, 0, N_BINS - 1))
    c_bin = int(np.clip(np.searchsorted(CURVATURE_EDGES, params.curvature_deg, side="right") - 1, 0, N_BINS - 1))
    return a_bin, c_bin


def _random_genotype(rng: np.random.Generator) -> GripperParams:
    return GripperParams(
        n_fingers=int(rng.choice(FINGER_COUNT_CHOICES)),
        finger_length=float(rng.uniform(*FINGER_LENGTH_BOUNDS)),
        curvature_deg=float(rng.uniform(*CURVATURE_DEG_BOUNDS)),
        aperture=float(rng.uniform(*APERTURE_BOUNDS)),
        compliance=float(rng.uniform(*COMPLIANCE_BOUNDS)),
    ).clipped()


def _mutate(parent: GripperParams, rng: np.random.Generator) -> GripperParams:
    def _pert(val, lo, hi):
        span = hi - lo
        return float(np.clip(val + rng.normal(0, MUTATION_SIGMA * span), lo, hi))

    n_fingers = parent.n_fingers
    if rng.random() < FINGER_FLIP_PROB:
        n_fingers = int(rng.choice(FINGER_COUNT_CHOICES))
    return GripperParams(
        n_fingers=n_fingers,
        finger_length=_pert(parent.finger_length, *FINGER_LENGTH_BOUNDS),
        curvature_deg=_pert(parent.curvature_deg, *CURVATURE_DEG_BOUNDS),
        aperture=_pert(parent.aperture, *APERTURE_BOUNDS),
        compliance=_pert(parent.compliance, *COMPLIANCE_BOUNDS),
    ).clipped()


def _patch_pool() -> None:
    scene_config.YCB_LAYOUT = _ARCHIVE_YCB_LAYOUT
    build_scene_mod.YCB_LAYOUT = _ARCHIVE_YCB_LAYOUT
    randomize_mod.YCB_LAYOUT = _ARCHIVE_YCB_LAYOUT
    randomize_mod.RELIABLE_PICK_POOL = _ARCHIVE_POOL


def _restore_pool() -> None:
    scene_config.YCB_LAYOUT = _ORIG_YCB_LAYOUT
    build_scene_mod.YCB_LAYOUT = _ORIG_YCB_LAYOUT
    randomize_mod.YCB_LAYOUT = _ORIG_YCB_LAYOUT
    randomize_mod.RELIABLE_PICK_POOL = _ORIG_POOL


def evaluate_genotype(params: GripperParams) -> dict:
    _patch_pool()
    try:
        result = evaluate_candidate(params, trial_seeds=TRIAL_SEEDS)
    finally:
        _restore_pool()
    return {
        "params": vars(params), "fitness": result.fitness,
        "success_rate": result.agg.success_rate, "mean_peak_force": result.agg.mean_peak_force,
        "mean_max_slip": result.agg.mean_max_slip,
        "per_object": {obj: bool(s) for obj, s in zip(result.per_trial_pick_object, result.per_trial_success)},
    }


def run_archive(*, n_evals: int, n_init: int, seed: int, out_path: Path, log_fn=print) -> dict:
    rng = np.random.default_rng(seed)
    archive: dict[tuple[int, int], dict] = {}
    history = []
    t0 = time.time()

    for i in range(n_evals):
        if i < n_init or not archive:
            genotype = _random_genotype(rng)
        else:
            parent_cell = list(archive.keys())[rng.integers(len(archive))]
            genotype = _mutate(archive[parent_cell]["params_obj"], rng)

        r = evaluate_genotype(genotype)
        cell = _bin_index(genotype)
        improved = cell not in archive or r["fitness"] > archive[cell]["fitness"]
        if improved:
            archive[cell] = {**r, "params_obj": genotype, "cell": cell, "eval_idx": i}
        history.append({"eval_idx": i, "cell": cell, "fitness": r["fitness"], "success_rate": r["success_rate"], "improved": improved})

        if (i + 1) % 25 == 0 or i == n_evals - 1:
            elapsed = time.time() - t0
            log_fn(f"[archive] eval {i+1}/{n_evals} cells_filled={len(archive)}/{N_BINS*N_BINS} best_fitness={max(c['fitness'] for c in archive.values()):.3f} elapsed={elapsed:.0f}s")
            _write(archive, history, out_path, elapsed)

    return archive


def _write(archive, history, out_path: Path, elapsed: float) -> None:
    serializable = {
        f"{a},{c}": {k: v for k, v in cell.items() if k != "params_obj"}
        for (a, c), cell in archive.items()
    }
    out_path.write_text(json.dumps({"archive": serializable, "history": history, "elapsed_seconds": elapsed, "n_bins": N_BINS}, indent=2))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-evals", type=int, default=500)
    ap.add_argument("--n-init", type=int, default=60)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", type=str, default=str(_ROOT.parent.parent / "results" / "06_fruit_archive_qd" / "fruit_archive.json"))
    args = ap.parse_args()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    archive = run_archive(n_evals=args.n_evals, n_init=args.n_init, seed=args.seed, out_path=out_path)
    print(f"done. {len(archive)}/{N_BINS*N_BINS} cells filled.")


if __name__ == "__main__":
    main()
