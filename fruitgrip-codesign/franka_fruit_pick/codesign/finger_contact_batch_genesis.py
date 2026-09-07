"""Diagnostic batch (Genesis side): per-finger contact-onset timing for the frozen
winner design on lemon/plum, 30 trials each (60 total) -- same n, same DR ranges,
same object restriction as finger_contact_batch_mj.py, for a direct comparison.
Does not modify the frozen design or Genesis's contact-solver settings; only adds
observation via finger_contact_diag.run_pick_place_diag.
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
from run_attribution import JOINT_BEST_PARAMS  # noqa: E402
from finger_contact_diag import run_pick_place_diag  # noqa: E402
from sim_episode import GripperRuntime  # noqa: E402

DR = DomainRandomizationConfig(enabled=True, friction_ratio_range=(0.7, 1.3), mass_ratio_range=(0.8, 1.2))
DIAG_POOL = ("014_lemon", "018_plum")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-trials", type=int, default=60)
    ap.add_argument("--seed-base", type=int, default=2000)
    ap.add_argument("--out", type=str, default=str(_ROOT.parent.parent / "results" / "05_cross_simulator" / "finger_contact_timing_genesis.json"))
    args = ap.parse_args()

    params = JOINT_BEST_PARAMS
    xml_path = generate_gripper_xml(params)
    finger_names = params.body_names()

    gs.init(backend=gs.cpu)
    bundle = build_scene(show_viewer=False, n_envs=1, add_world_cam=False, add_wrist_cam=False, franka_xml_path=str(xml_path))
    rt = GripperRuntime(n_fingers=params.n_fingers, finger_open_travel=max(params.aperture / 2 - 0.002, 0.002))

    orig_pool = randomize_mod.RELIABLE_PICK_POOL
    randomizer = EnvRandomizer(bundle, RandomizationConfig(randomize_pick=True, dr=DR))

    trials = []
    t0 = time.time()
    for i in range(args.n_trials):
        obj = DIAG_POOL[i % 2]
        randomize_mod.RELIABLE_PICK_POOL = (obj,)
        seed = args.seed_base + i
        task = randomizer.reset(seed=seed)
        profile = adapt_grasp_profile(params, task.pick_object)
        result = run_pick_place_diag(bundle, rt, task, profile, finger_names)
        result["pick_object"] = task.pick_object
        result["friction_ratio"] = randomizer.last_friction_ratio
        trials.append(result)
    wall = time.time() - t0
    randomize_mod.RELIABLE_PICK_POOL = orig_pool
    gs.destroy()

    n_success = sum(1 for t in trials if t["success"])
    n_all_engaged = sum(1 for t in trials if t["n_fingers_ever_engaged"] == t["n_fingers_total"])
    spreads = [t["onset_spread_steps"] for t in trials if t["onset_spread_steps"] is not None]

    print(f"Genesis winner (3-finger), lemon+plum, n={args.n_trials}: success={n_success}/{args.n_trials}")
    print(f"all-{params.n_fingers}-fingers-ever-engaged: {n_all_engaged}/{args.n_trials}")
    if spreads:
        print(f"onset spread (steps, among trials w/ >=2 fingers engaged): mean={np.mean(spreads):.1f} median={np.median(spreads):.1f} max={np.max(spreads)}")
    succ_spreads = [t["onset_spread_steps"] for t in trials if t["success"] and t["onset_spread_steps"] is not None]
    fail_spreads = [t["onset_spread_steps"] for t in trials if not t["success"] and t["onset_spread_steps"] is not None]
    print(f"onset spread | success trials: mean={np.mean(succ_spreads) if succ_spreads else float('nan'):.1f} (n={len(succ_spreads)})")
    print(f"onset spread | failure trials: mean={np.mean(fail_spreads) if fail_spreads else float('nan'):.1f} (n={len(fail_spreads)})")

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({"trials": trials, "wall_seconds": wall}, indent=2))
    print(f"wrote {out_path} ({wall:.1f}s)")


if __name__ == "__main__":
    main()
