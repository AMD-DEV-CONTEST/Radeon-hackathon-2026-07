"""Session 4, Priority 3 (batched arm): a raw physics-stepping throughput benchmark,
separate from the literal same-structure attribution rerun.

Why this exists: the codesign pipeline's evaluate_candidate() (and everything built on
it -- search.py, run_attribution.py) runs ONE environment at a time, scripted
sequentially. That is not the workload Genesis's GPU backend is built to accelerate --
its throughput claims (and the project brief's "tens of millions of simulation frames
per second") come from stepping THOUSANDS of environments in lockstep on the GPU, not
from running a single environment faster. Confirmed empirically: n_envs=1 on GPU was
~3.5x *slower* than CPU for the same single-environment workload (session 4 smoke
test) -- entirely expected once you know GPU sim engines are designed for batch
parallelism, not single-instance latency.

This benchmark isolates that batching axis directly: build the *same* scene (Franka +
YCB objects + bowl) used throughout this project, at varying n_envs, and time raw
`scene.step()` throughput on CPU vs GPU. It reuses build_scene.py's own n_envs-aware
scene construction (already wired for batching -- see build_scene.py's own --n-envs
CLI flag) rather than reinventing it, just with the backend made explicit (gs.amdgpu,
not build_scene.py main()'s hardcoded gs.gpu, which is not guaranteed to resolve to
the AMD backend on a ROCm host) and normal-mode (not exploratory scripted-grasp)
stepping so the numbers are a clean physics-throughput measurement, not conflated with
IK/control logic cost.

Reports both raw steps/sec (scene.step() calls per wall-second) and env-steps/sec
(steps/sec * n_envs -- the number that actually matters for "how many trials could
this evaluate per hour," since one scene.step() at n_envs=256 advances 256 independent
trials at once).
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
from build_scene import FRANKA_QPOS, build_scene  # noqa: E402


def run_one(*, n_envs: int, steps: int, backend, warmup_steps: int = 20, log_fn=print) -> dict:
    gs.init(backend=backend)
    bundle = build_scene(show_viewer=False, n_envs=n_envs, add_world_cam=False, add_wrist_cam=False)

    hold_qpos = np.array(FRANKA_QPOS)
    if n_envs > 1:
        hold_qpos = np.tile(hold_qpos, (n_envs, 1))

    # Warmup: pays the one-time JIT/kernel-compile cost (session 4 found this can be
    # ~10-90s depending on cache state) outside the timed region, so the reported
    # throughput reflects steady-state stepping, not compile overhead.
    for _ in range(warmup_steps):
        bundle.franka.control_dofs_position(hold_qpos)
        bundle.scene.step()

    t0 = time.time()
    for _ in range(steps):
        bundle.franka.control_dofs_position(hold_qpos)
        bundle.scene.step()
    wall = time.time() - t0

    steps_per_sec = steps / wall
    env_steps_per_sec = steps_per_sec * n_envs
    log_fn(f"n_envs={n_envs:>4}  steps={steps}  wall={wall:.2f}s  steps/sec={steps_per_sec:.1f}  env-steps/sec={env_steps_per_sec:.0f}")

    gs.destroy()
    return {"n_envs": n_envs, "steps": steps, "wall_seconds": wall, "steps_per_sec": steps_per_sec, "env_steps_per_sec": env_steps_per_sec}


def main() -> None:
    ap = argparse.ArgumentParser(description="Raw physics-stepping throughput benchmark (CPU vs GPU, varying n_envs).")
    ap.add_argument("--backend", choices=["cpu", "amdgpu", "gpu", "cuda"], default="cpu")
    ap.add_argument("--n-envs", type=int, nargs="+", default=[1, 8, 32, 128])
    ap.add_argument("--steps", type=int, default=300)
    ap.add_argument("--out", type=str, default=str(_ROOT.parent.parent / "results" / "04_rocm_benchmark" / "throughput_bench.json"))
    args = ap.parse_args()

    backend = {"cpu": gs.cpu, "amdgpu": gs.amdgpu, "gpu": gs.gpu, "cuda": gs.cuda}[args.backend]
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    results = []
    for n_envs in args.n_envs:
        print(f"=== backend={args.backend} n_envs={n_envs} ===")
        r = run_one(n_envs=n_envs, steps=args.steps, backend=backend)
        r["backend"] = args.backend
        results.append(r)

    out_path.write_text(json.dumps(results, indent=2))
    print(f"\nwrote {out_path}")


if __name__ == "__main__":
    main()
