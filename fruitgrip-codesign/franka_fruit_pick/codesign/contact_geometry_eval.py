"""Session 8, Part B driver: run contact_geometry_diag across a curated
10-object subset spanning ycb_generalization_findings.md's three observed
categories -- round/winner-favored, flat/baseline-favored, and both-fail/tie
-- for both frozen designs, and check whether contact-point-count / normal-
alignment (the two proxies contact_geometry_diag.py builds from what Genesis's
contact API actually exposes) predicts success independent of which design is
used, as the curvature-vs-flatness hypothesis would require.
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

import scene_config  # noqa: E402
import build_scene as build_scene_mod  # noqa: E402
import randomize as randomize_mod  # noqa: E402
from build_scene import build_scene  # noqa: E402
from randomize import DomainRandomizationConfig, RandomizationConfig, EnvRandomizer  # noqa: E402

from controller_adapt import adapt_grasp_profile  # noqa: E402
from gripper_gen import generate_gripper_xml, GripperParams  # noqa: E402
from run_attribution import BASELINE_PARAMS, JOINT_BEST_PARAMS  # noqa: E402
from sim_episode import GripperRuntime  # noqa: E402
from contact_geometry_diag import run_pick_place_geometry  # noqa: E402

DEFAULT_DR = DomainRandomizationConfig(enabled=True, friction_ratio_range=(0.7, 1.3), mass_ratio_range=(0.8, 1.2))
N_TRIALS = 10

# Category labels are this session's own read of ycb_generalization_findings.md
# S2's table -- not re-derived here, just carried over for the report.
OBJECTS = {
    "016_pear": "round_winner_favored", "005_tomato_soup_can": "round_winner_favored", "056_tennis_ball": "round_winner_favored",
    "077_rubiks_cube": "flat_baseline_favored", "051_large_clamp": "flat_baseline_favored", "037_scissors": "flat_baseline_favored",
    "061_foam_brick": "tie_both_succeed", "013_apple": "both_near_fail", "062_dice": "both_fail", "058_golf_ball": "both_fail",
}

_ORIG_YCB_LAYOUT = dict(scene_config.YCB_LAYOUT)
_ORIG_POOL = randomize_mod.RELIABLE_PICK_POOL


def _patch_layout(obj_name: str) -> None:
    layout = {
        obj_name: {"pos": (0.35, 0.0, 0.0), "euler": (0.0, 0.0, 0.0)},
        "024_bowl": {"pos": (0.50, -0.10, 0.0), "euler": (0.0, 0.0, 0.0)},
    }
    scene_config.YCB_LAYOUT = layout
    build_scene_mod.YCB_LAYOUT = layout
    randomize_mod.YCB_LAYOUT = layout
    randomize_mod.RELIABLE_PICK_POOL = (obj_name,)


def _restore_layout() -> None:
    scene_config.YCB_LAYOUT = _ORIG_YCB_LAYOUT
    build_scene_mod.YCB_LAYOUT = _ORIG_YCB_LAYOUT
    randomize_mod.YCB_LAYOUT = _ORIG_YCB_LAYOUT
    randomize_mod.RELIABLE_PICK_POOL = _ORIG_POOL


def eval_object_design(params: GripperParams, obj_name: str, finger_names: list[str], seed_base: int) -> dict:
    _patch_layout(obj_name)
    try:
        xml_path = generate_gripper_xml(params)
        gs.init(backend=gs.cpu)
        bundle = build_scene(show_viewer=False, n_envs=1, add_world_cam=False, add_wrist_cam=False, franka_xml_path=str(xml_path))
        rt = GripperRuntime(n_fingers=params.n_fingers, finger_open_travel=max(params.aperture / 2 - 0.002, 0.002))
        randomizer = EnvRandomizer(bundle, RandomizationConfig(randomize_pick=False, dr=DEFAULT_DR))

        trials = []
        t0 = time.time()
        for i in range(N_TRIALS):
            task = randomizer.reset(seed=seed_base + i)
            profile = adapt_grasp_profile(params, task.pick_object)
            r = run_pick_place_geometry(bundle, rt, task, profile, finger_names)
            trials.append(r)
        wall = time.time() - t0
        gs.destroy()
    finally:
        _restore_layout()

    succ = [t["success"] for t in trials]
    points = [t["mean_contact_points"] for t in trials]
    spreads = [t["mean_normal_spread"] for t in trials if t["mean_normal_spread"] is not None]
    return {
        "object": obj_name, "n": N_TRIALS, "success_rate": float(np.mean(succ)),
        "mean_contact_points": float(np.mean(points)) if points else 0.0,
        "mean_normal_spread": float(np.mean(spreads)) if spreads else None,
        "wall_seconds": wall,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed-base", type=int, default=11000)
    ap.add_argument("--out", type=str, default=str(_ROOT.parent.parent / "results" / "07_contact_geometry" / "contact_geometry_eval.json"))
    args = ap.parse_args()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    results = {"baseline": {}, "winner": {}, "categories": OBJECTS}

    for obj, category in OBJECTS.items():
        for label, params in (("baseline", BASELINE_PARAMS), ("winner", JOINT_BEST_PARAMS)):
            finger_names = ["left_finger", "right_finger"] if params.n_fingers == 2 else [f"finger_{i}" for i in range(params.n_fingers)]
            r = eval_object_design(params, obj, finger_names, args.seed_base)
            r["category"] = category
            results[label][obj] = r
            print(f"[{label}] {obj} ({category}): success={r['success_rate']:.1%} "
                  f"contact_pts={r['mean_contact_points']:.2f} normal_spread={r['mean_normal_spread']}")
        out_path.write_text(json.dumps(results, indent=2))

    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
