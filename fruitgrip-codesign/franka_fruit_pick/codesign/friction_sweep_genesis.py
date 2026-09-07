"""Escalation 1 (session 8): controlled friction dose-response sweep, Genesis side.

Companion to mujoco_repl/friction_sweep_mj.py -- same methodology, same design
decision (mass ratio fixed at 1.0, pose jitter kept ON as the residual source of
trial-to-trial variance, friction ratio fixed -- not drawn -- at each of 31 values
from 0.5 to 2.0 in 0.05 steps, 30 trials/point, lemon+plum only), so the two
sweeps are directly comparable. See that file's docstring for the full reasoning.

Reuses build_scene / GripperRuntime / adapt_grasp_profile / sim_episode.run_pick_place
exactly as evaluate.py does -- no changes to the frozen controller or design params.
Bypasses EnvRandomizer's own friction/mass sampling (which draws from a range) by
calling the same underlying entity.set_friction_ratio/set_mass_shift methods
directly with a fixed value, still going through the exact same physics-application
API the frozen pipeline uses -- not a new mechanism.
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

from build_scene import build_scene  # noqa: E402
from randomize import DomainRandomizationConfig, RandomizationConfig, EnvRandomizer  # noqa: E402
import randomize as randomize_mod  # noqa: E402

from controller_adapt import adapt_grasp_profile  # noqa: E402
from gripper_gen import generate_gripper_xml  # noqa: E402
from run_attribution import BASELINE_PARAMS, JOINT_BEST_PARAMS  # noqa: E402
from sim_episode import GripperRuntime, run_pick_place  # noqa: E402
from confirmation_eval import wilson_ci  # noqa: E402

DIAG_POOL = ("014_lemon", "018_plum")
FRICTION_VALUES = np.round(np.arange(0.5, 2.0001, 0.05), 2).tolist()
N_TRIALS_PER_POINT = 30

# Session-8 note: the machine this runs on has very little free RAM headroom
# (personal desktop, Chrome/VSCode already using most of 14GB) -- a full-resolution
# sweep drove the system into swap-thrashing (confirmed via vmstat: 78-89% iowait,
# active si/so) rather than just running slowly. Coarsened via CLI flags below
# instead of hardcoding a permanently-reduced default, so the resolution used is
# explicit and documented per run rather than silently baked in.

# DR config with mass fixed (range collapsed to (1.0, 1.0), which
# EnvRandomizer._randomize_dynamics's own `if not (mlo == 1.0 and mhi == 1.0)`
# guard already treats as "skip mass randomization" -- no new mechanism, just
# the range that produces "fixed").
FIXED_MASS_DR = DomainRandomizationConfig(enabled=True, friction_ratio_range=(1.0, 1.0), mass_ratio_range=(1.0, 1.0))


def sweep_design(params, label: str, seed_base: int, log_fn=print) -> dict:
    xml_path = generate_gripper_xml(params)

    gs.init(backend=gs.cpu)
    bundle = build_scene(show_viewer=False, n_envs=1, add_world_cam=False, add_wrist_cam=False, franka_xml_path=str(xml_path))
    rt = GripperRuntime(n_fingers=params.n_fingers, finger_open_travel=max(params.aperture / 2 - 0.002, 0.002))

    orig_pool = randomize_mod.RELIABLE_PICK_POOL
    # Friction/mass DR "enabled" so _randomize_dynamics runs (applying our fixed
    # values consistently, same code path as every other trial in this project),
    # but its own sampled ratio is immediately overwritten below with the swept
    # fixed value -- the (1.0,1.0) mass range means mass truly never moves.
    randomizer = EnvRandomizer(bundle, RandomizationConfig(randomize_pick=True, dr=FIXED_MASS_DR))

    points = []
    t0 = time.time()
    for fi, friction in enumerate(FRICTION_VALUES):
        trials = []
        for i in range(N_TRIALS_PER_POINT):
            obj = DIAG_POOL[i % 2]
            randomize_mod.RELIABLE_PICK_POOL = (obj,)
            seed = seed_base + fi * N_TRIALS_PER_POINT + i
            task = randomizer.reset(seed=seed)
            # Overwrite the just-sampled (fixed-range) friction ratio with this
            # sweep point's exact value, applied via the same set_friction_ratio
            # path _randomize_dynamics itself uses.
            randomizer._set_friction_ratio(bundle.franka, friction)
            for name in randomizer.names:
                randomizer._set_friction_ratio(bundle.ycb[name], friction)
            for table_entity in getattr(bundle, "table", []) or []:
                randomizer._set_friction_ratio(table_entity, friction)
            profile = adapt_grasp_profile(params, task.pick_object)
            m = run_pick_place(bundle, rt, task, profile)
            trials.append(m.success)
        successes = sum(1 for s in trials if s)
        ci_lo, ci_hi = wilson_ci(successes, N_TRIALS_PER_POINT)
        points.append({
            "friction_ratio": friction, "n": N_TRIALS_PER_POINT, "successes": successes,
            "success_rate": successes / N_TRIALS_PER_POINT, "success_rate_95ci": [ci_lo, ci_hi],
        })
        log_fn(f"[{label}] friction={friction:.2f} success={successes}/{N_TRIALS_PER_POINT} ({successes/N_TRIALS_PER_POINT:.1%})")

    randomize_mod.RELIABLE_PICK_POOL = orig_pool
    gs.destroy()
    wall = time.time() - t0
    return {"label": label, "params": vars(params), "points": points, "wall_seconds": wall}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed-base", type=int, default=5000)
    ap.add_argument("--friction-step", type=float, default=0.05)
    ap.add_argument("--n-trials", type=int, default=30)
    ap.add_argument("--out", type=str, default=str(_ROOT.parent.parent / "results" / "05_cross_simulator" / "friction_doseresponse_genesis.json"))
    args = ap.parse_args()

    global FRICTION_VALUES, N_TRIALS_PER_POINT
    FRICTION_VALUES = np.round(np.arange(0.5, 2.0001, args.friction_step), 2).tolist()
    N_TRIALS_PER_POINT = args.n_trials

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    baseline = sweep_design(BASELINE_PARAMS, "baseline", args.seed_base)
    winner = sweep_design(JOINT_BEST_PARAMS, "winner", args.seed_base + 100000)

    results = {"baseline": baseline, "winner": winner, "friction_values": FRICTION_VALUES, "wall_seconds": time.time() - t0}
    out_path.write_text(json.dumps(results, indent=2))
    print(f"wrote {out_path} ({results['wall_seconds']:.1f}s total)")


if __name__ == "__main__":
    main()
