"""GPU-corrected re-validation (session 8 Part A, follow-up). The from-scratch
GPU MAP-Elites search (fruit_archive_gpu.py, 80 evaluations) did not find a
good design -- diagnosed as a genuine consequence of its smaller genotype
budget (80 vs the CPU run's 500), not a bug (verified: isolated GPU evaluation
of the known-good frozen winner, and of a mutation near it, both succeed
cleanly on this exact pipeline). This script instead uses the GPU for what it's
actually good for here: fast, high-trial-count confirmation of ALREADY-KNOWN
candidates (the CPU archive's top 4 cells, plus the frozen winner/baseline),
via evaluate_candidate_batched at n_envs=64 per object -- far more trials per
candidate than the CPU-side revalidation's 30, in a fraction of the time.
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
from run_attribution import BASELINE_PARAMS, JOINT_BEST_PARAMS  # noqa: E402
from fruit_archive import _patch_pool, _restore_pool, _ARCHIVE_POOL  # noqa: E402

N_ENVS_PER_OBJECT = 64


def revalidate_gpu(label: str, params: GripperParams, seed_base: int, log_fn=print) -> dict:
    _patch_pool()
    try:
        seeds_by_object = {obj: list(range(seed_base, seed_base + N_ENVS_PER_OBJECT)) for obj in _ARCHIVE_POOL}
        result = evaluate_candidate_batched(params, seeds_by_object, backend=gs.amdgpu)
        per_object = {
            obj: float(np.mean([s for o, s in zip(result.per_trial_pick_object, result.per_trial_success) if o == obj]))
            for obj in _ARCHIVE_POOL
        }
        log_fn(f"[{label}] " + " ".join(f"{o}={v:.1%}" for o, v in per_object.items()))
    finally:
        _restore_pool()
    return {"label": label, "params": vars(params), "per_object": per_object, "n_per_object": N_ENVS_PER_OBJECT}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--archive", type=str, default=str(_ROOT.parent.parent / "results" / "06_fruit_archive_qd" / "fruit_archive.json"))
    ap.add_argument("--top-n", type=int, default=4)
    ap.add_argument("--seed-base", type=int, default=77000)
    ap.add_argument("--out", type=str, default=str(_ROOT.parent.parent / "results" / "06_fruit_archive_qd" / "fruit_archive_gpu_revalidation.json"))
    args = ap.parse_args()

    archive = json.loads(Path(args.archive).read_text())["archive"]
    top_cells = sorted(archive.items(), key=lambda kv: -kv[1]["fitness"])[: args.top_n]

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    results = []
    t0 = time.time()

    results.append(revalidate_gpu("frozen_winner", JOINT_BEST_PARAMS, args.seed_base))
    out_path.write_text(json.dumps(results, indent=2))
    results.append(revalidate_gpu("frozen_baseline", BASELINE_PARAMS, args.seed_base + 100))
    out_path.write_text(json.dumps(results, indent=2))
    for i, (cell_key, cell) in enumerate(top_cells):
        params = GripperParams(**cell["params"]).clipped()
        results.append(revalidate_gpu(f"cpu_archive_cell_{cell_key}_rank{i+1}", params, args.seed_base + 200 + i * 100))
        out_path.write_text(json.dumps(results, indent=2))

    elapsed = time.time() - t0
    for r in results:
        r["wall_seconds_total_run"] = elapsed
    out_path.write_text(json.dumps(results, indent=2))
    print(f"wrote {out_path} ({elapsed:.1f}s total)")


if __name__ == "__main__":
    main()
