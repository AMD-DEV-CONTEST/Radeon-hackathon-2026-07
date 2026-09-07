"""Escalation 3, GPU-corrected re-run (session 8 Part A). Same MAP-Elites
algorithm as fruit_archive.py, but fitness evaluation uses session 4's
validated batched-GPU path (`evaluate_candidate_batched`, backend=gs.amdgpu,
n_envs = trial count per object) instead of sequential CPU trials.

Two deliberate improvements over the CPU version, both real changes, not just
"same result faster":
1. Trials per genotype go from 3 (CPU, kept low to make 500 evaluations
   affordable) to 8 per object x 4 objects = 32 per genotype. Batching removes
   the reason to keep this low -- n_envs=8 is well inside the regime where
   session 4's own benchmark found batched GPU beats CPU, and using seeds_by_object
   means EVERY genotype now gets real apple trials (fixing the bug the CPU
   archive run had, where apple was never drawn in any of the 64 cells' 3-trial
   samples -- see fruit_archive.py's module docstring and
   cross_simulator... no: fruitarchive_findings.md S1 for that story).
2. Evaluation budget target is set from measured per-genotype wall time on
   this instance (see smoke-test numbers logged at run start), aiming for
   the largest count that fits a bounded, credit-conscious GPU session
   (this account has 10 credits total; usage is billed per GPU-hour) --
   reported explicitly in gpu_corrected_findings.md, not silently decided.
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
import genesis as gs  # noqa: E402

from evaluate import evaluate_candidate_batched  # noqa: E402
from gripper_gen import GripperParams  # noqa: E402
from fruit_archive import (  # noqa: E402
    _bin_index, _random_genotype, _mutate, _patch_pool, _restore_pool,
    _ARCHIVE_POOL, N_BINS, APERTURE_EDGES, CURVATURE_EDGES,
)

N_SEEDS_PER_OBJECT = 32


def evaluate_genotype_gpu(params: GripperParams, seed_base: int) -> dict:
    _patch_pool()
    try:
        seeds_by_object = {obj: list(range(seed_base, seed_base + N_SEEDS_PER_OBJECT)) for obj in _ARCHIVE_POOL}
        result = evaluate_candidate_batched(params, seeds_by_object, backend=gs.amdgpu)
    finally:
        _restore_pool()
    return {
        "params": vars(params), "fitness": result.fitness,
        "success_rate": result.agg.success_rate, "mean_peak_force": result.agg.mean_peak_force,
        "mean_max_slip": result.agg.mean_max_slip,
        "per_object_success": {
            obj: float(np.mean([s for o, s in zip(result.per_trial_pick_object, result.per_trial_success) if o == obj]))
            for obj in set(result.per_trial_pick_object)
        },
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

        eval_seed_base = seed * 1_000_000 + i * N_SEEDS_PER_OBJECT
        r = evaluate_genotype_gpu(genotype, eval_seed_base)
        cell = _bin_index(genotype)
        improved = cell not in archive or r["fitness"] > archive[cell]["fitness"]
        if improved:
            archive[cell] = {**r, "params_obj": genotype, "cell": cell, "eval_idx": i}
        history.append({"eval_idx": i, "cell": cell, "fitness": r["fitness"], "success_rate": r["success_rate"], "improved": improved})

        if (i + 1) % 10 == 0 or i == n_evals - 1:
            elapsed = time.time() - t0
            per_eval = elapsed / (i + 1)
            log_fn(f"[archive-gpu] eval {i+1}/{n_evals} cells_filled={len(archive)}/{N_BINS*N_BINS} best_fitness={max(c['fitness'] for c in archive.values()):.3f} elapsed={elapsed:.0f}s ({per_eval:.1f}s/eval)")
            _write(archive, history, out_path, elapsed)

    return archive


def _write(archive, history, out_path: Path, elapsed: float) -> None:
    serializable = {
        f"{a},{c}": {k: v for k, v in cell.items() if k != "params_obj"}
        for (a, c), cell in archive.items()
    }
    out_path.write_text(json.dumps({"archive": serializable, "history": history, "elapsed_seconds": elapsed, "n_bins": N_BINS, "n_seeds_per_object": N_SEEDS_PER_OBJECT}, indent=2))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-evals", type=int, default=500)
    ap.add_argument("--n-init", type=int, default=60)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", type=str, default=str(_ROOT.parent.parent / "results" / "06_fruit_archive_qd" / "fruit_archive_gpu.json"))
    args = ap.parse_args()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    archive = run_archive(n_evals=args.n_evals, n_init=args.n_init, seed=args.seed, out_path=out_path)
    print(f"done. {len(archive)}/{N_BINS*N_BINS} cells filled.")


if __name__ == "__main__":
    main()
