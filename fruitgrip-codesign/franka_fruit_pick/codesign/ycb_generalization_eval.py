"""Escalation 2 (session 8): full YCB-scale generalization test, Genesis only.

Expands the original held-out generalization check (apple/pear, n=200 combined,
`results/generalization_findings.md`) to a much broader, more diverse object set --
45 objects spanning cans, boxes, bottles, hand tools, balls of varying size, cups,
flat/thin items, and small graspables -- not just more fruit-like shapes. Frozen
winner and baseline designs, unchanged; this only adds evaluation objects, never
re-searches or re-tunes either design.

Each object gets its OWN single-object scene (target object + place bowl only),
built by temporarily monkeypatching `scene_config.YCB_LAYOUT` (and the same name
as separately imported into `build_scene.py` and `randomize.py` -- three distinct
module-level bindings of the same name, all three must be patched for the change
to actually take effect) to a two-entry layout, rather than trying to cram 45
objects of wildly different sizes into one shared tabletop layout the way the
original 3-fruit set does. This is a scoping/testing convenience, not a change to
how any object is scored -- reset/DR/controller code paths are all the same
frozen pipeline (build_scene, EnvRandomizer, adapt_grasp_profile,
sim_episode.run_pick_place) used everywhere else in this project.

Same DR ranges as the original confirmation-eval protocol (friction 0.7-1.3x, mass
0.8-1.2x) -- NOT Escalation 1's extended sweep, per the brief's explicit
instruction to keep this escalation on the original range.
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

import genesis as gs  # noqa: E402

import scene_config  # noqa: E402
import build_scene as build_scene_mod  # noqa: E402
import randomize as randomize_mod  # noqa: E402
from build_scene import build_scene  # noqa: E402
from randomize import DomainRandomizationConfig, RandomizationConfig, EnvRandomizer  # noqa: E402

from controller_adapt import adapt_grasp_profile  # noqa: E402
from gripper_gen import generate_gripper_xml  # noqa: E402
from run_attribution import BASELINE_PARAMS, JOINT_BEST_PARAMS  # noqa: E402
from sim_episode import GripperRuntime, run_pick_place  # noqa: E402
from confirmation_eval import wilson_ci  # noqa: E402

DEFAULT_DR = DomainRandomizationConfig(enabled=True, friction_ratio_range=(0.7, 1.3), mass_ratio_range=(0.8, 1.2))
N_TRIALS = 30

# Session-8 note: same machine-headroom constraint as friction_sweep_genesis.py --
# a single Genesis process already pushed this personal desktop into swap-thrashing
# (confirmed via vmstat) when run at originally-planned scope. N_TRIALS is
# CLI-overridable (see --n-trials below); default kept at the brief's requested 30,
# but this session's actual run uses a reduced value, applied explicitly per run
# rather than silently baked into a lowered default.

# Objects with an existing friction override from prior sessions' YCB_LAYOUT config
# (apple/orange/pear -- see scene_config.py's commented entries), reused verbatim,
# not re-tuned. Every other object gets Genesis's default material friction (None).
FRICTION_OVERRIDES = {"013_apple": 1.0, "017_orange": 1.0, "016_pear": 1.0, "014_lemon": 1.0, "018_plum": 1.0}

GENERALIZATION_OBJECTS = [
    # already-local held-out (from the original session's generalization check + disabled distractors)
    "013_apple", "017_orange", "016_pear", "025_mug", "003_cracker_box", "006_mustard_bottle",
    # cans / cylinders
    "002_master_chef_can", "005_tomato_soup_can", "010_potted_meat_can",
    # boxes
    "004_sugar_box", "008_pudding_box", "036_wood_block", "061_foam_brick",
    # bottles
    "021_bleach_cleanser", "019_pitcher_base",
    # elongated tools
    "040_large_marker", "043_phillips_screwdriver",
    "031_spoon", "032_knife", "033_spatula", "037_scissors",
    # odd/hard shapes
    "035_power_drill", "048_hammer", "042_adjustable_wrench", "051_large_clamp", "038_padlock",
    # flat/thin
    "029_plate", "026_sponge",
    # small graspables
    "062_dice", "077_rubiks_cube",
    # spheres, small to large
    "058_golf_ball", "056_tennis_ball", "054_softball", "053_mini_soccer_ball",
    # cups, small/large
    "065-a_cups", "065-j_cups",
]
# Session-8 machine-headroom note (see friction_sweep_genesis.py for the same
# issue, confirmed via vmstat): trimmed from an original 45-object list to 30
# (the brief's stated minimum) with N_TRIALS reduced via --n-trials, to keep
# this run in the same safe compute envelope as Escalation 1's reduced sweep
# rather than risk the same swap-thrashing at full scope.

_ORIG_YCB_LAYOUT = dict(scene_config.YCB_LAYOUT)
_ORIG_POOL = randomize_mod.RELIABLE_PICK_POOL


def _single_object_layout(obj_name: str) -> dict:
    layout = {
        obj_name: {"pos": (0.35, 0.0, 0.0), "euler": (0.0, 0.0, 0.0)},
        "024_bowl": {"pos": (0.50, -0.10, 0.0), "euler": (0.0, 0.0, 0.0)},
    }
    if obj_name in FRICTION_OVERRIDES:
        layout[obj_name]["friction"] = FRICTION_OVERRIDES[obj_name]
    return layout


def _patch_layout(obj_name: str) -> None:
    layout = _single_object_layout(obj_name)
    scene_config.YCB_LAYOUT = layout
    build_scene_mod.YCB_LAYOUT = layout
    randomize_mod.YCB_LAYOUT = layout
    randomize_mod.RELIABLE_PICK_POOL = (obj_name,)


def _restore_layout() -> None:
    scene_config.YCB_LAYOUT = _ORIG_YCB_LAYOUT
    build_scene_mod.YCB_LAYOUT = _ORIG_YCB_LAYOUT
    randomize_mod.YCB_LAYOUT = _ORIG_YCB_LAYOUT
    randomize_mod.RELIABLE_PICK_POOL = _ORIG_POOL


def eval_object_design(params, obj_name: str, seed_base: int, n_trials: int = N_TRIALS, use_planner: bool = False) -> dict:
    _patch_layout(obj_name)
    try:
        xml_path = generate_gripper_xml(params)
        gs.init(backend=gs.cpu)
        bundle = build_scene(show_viewer=False, n_envs=1, add_world_cam=False, add_wrist_cam=False, franka_xml_path=str(xml_path))
        rt = GripperRuntime(n_fingers=params.n_fingers, finger_open_travel=max(params.aperture / 2 - 0.002, 0.002))
        randomizer = EnvRandomizer(bundle, RandomizationConfig(randomize_pick=False, dr=DEFAULT_DR))

        successes = []
        forces, slips = [], []
        t0 = time.time()
        for i in range(n_trials):
            seed = seed_base + i
            task = randomizer.reset(seed=seed)
            profile = adapt_grasp_profile(params, task.pick_object, use_planner=use_planner)
            m = run_pick_place(bundle, rt, task, profile)
            successes.append(bool(m.success))
            forces.append(m.peak_contact_force)
            slips.append(m.max_slip)
        wall = time.time() - t0
        gs.destroy()
    finally:
        _restore_layout()

    n_succ = sum(successes)
    ci_lo, ci_hi = wilson_ci(n_succ, n_trials)
    return {
        "object": obj_name, "n": n_trials, "successes": n_succ, "success_rate": n_succ / n_trials,
        "success_rate_95ci": [ci_lo, ci_hi], "mean_peak_force_N": float(np.mean(forces)),
        "mean_max_slip_m": float(np.mean(slips)), "wall_seconds": wall,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed-base", type=int, default=7000)
    ap.add_argument("--n-trials", type=int, default=N_TRIALS)
    ap.add_argument(
        "--planner", action="store_true",
        help="Route grasp targeting through grasp_planner.plan_grasp instead of the fixed "
             "per-object-name heuristic. Off by default -- the frozen original results "
             "(confirmation-eval, attribution, this file's own committed ycb_generalization_eval.json) "
             "are produced without this flag and are unaffected by its existence.",
    )
    ap.add_argument(
        "--out", type=str, default=None,
        help="Defaults to results/03_generalization/ycb_generalization_eval.json normally, or "
             "results/08_grasp_planner/ycb_generalization_eval_planner.json with --planner -- "
             "different paths so a --planner run can never silently overwrite the frozen original.",
    )
    ap.add_argument("--objects", type=str, nargs="*", default=None, help="Override object list (for smoke tests).")
    args = ap.parse_args()

    objects = args.objects or GENERALIZATION_OBJECTS
    if args.out is not None:
        out_path = Path(args.out)
    elif args.planner:
        out_path = _ROOT.parent.parent / "results" / "08_grasp_planner" / "ycb_generalization_eval_planner.json"
    else:
        out_path = _ROOT.parent.parent / "results" / "03_generalization" / "ycb_generalization_eval.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    results = {"baseline": {}, "winner": {}, "objects": objects, "n_trials": args.n_trials, "use_planner": args.planner}
    t0 = time.time()
    for obj in objects:
        for label, params in (("baseline", BASELINE_PARAMS), ("winner", JOINT_BEST_PARAMS)):
            r = eval_object_design(params, obj, args.seed_base, n_trials=args.n_trials, use_planner=args.planner)
            results[label][obj] = r
            print(f"[{label}] {obj}: {r['successes']}/{r['n']} ({r['success_rate']:.1%}) force={r['mean_peak_force_N']:.1f}N wall={r['wall_seconds']:.1f}s")
        # Incremental write so partial progress survives an interruption.
        out_path.write_text(json.dumps(results, indent=2))

    results["wall_seconds"] = time.time() - t0
    out_path.write_text(json.dumps(results, indent=2))
    print(f"wrote {out_path} ({results['wall_seconds']:.1f}s total)")


if __name__ == "__main__":
    main()
