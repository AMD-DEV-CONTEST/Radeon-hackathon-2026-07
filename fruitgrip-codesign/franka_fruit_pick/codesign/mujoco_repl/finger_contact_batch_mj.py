"""Diagnostic batch: per-finger contact-onset timing for the frozen winner design
on lemon/plum only (the objects the ported controller handles reliably -- see
cross_simulator_findings.md), MuJoCo side. Reuses confirmation_eval_mj.TrialModel's
scene setup (same DR ranges, same reset protocol) but calls finger_diag's
instrumented episode runner instead of controller.run_pick_place, and restricts
the pick pool to {lemon, plum} (banana's grasp is already known-broken in this
port and would just add noise to a contact-timing question).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if str(_ROOT.parent) not in sys.path:
    sys.path.insert(0, str(_ROOT.parent))
if str(_ROOT.parent.parent) not in sys.path:
    sys.path.insert(0, str(_ROOT.parent.parent))

import numpy as np  # noqa: E402
import mujoco  # noqa: E402

from confirmation_eval_mj import TrialModel, POS_JITTER, YAW_JITTER, FRICTION_RATIO_RANGE, MASS_RATIO_RANGE, FRANKA_QPOS_HOME, _quat_z  # noqa: E402
from scene_builder import OBJECT_LAYOUT, TABLE_TOP_Z  # noqa: E402
from domain_rand import apply_friction_ratio, apply_mass_ratio  # noqa: E402
from grasp_profile import adapt_grasp_profile  # noqa: E402
from finger_diag import run_pick_place_diag  # noqa: E402
from run_attribution import JOINT_BEST_PARAMS  # noqa: E402

DIAG_POOL = ("014_lemon", "018_plum")


def run_trial_diag(tm: TrialModel, seed: int, pick: str) -> dict:
    rng = np.random.default_rng(seed)
    data = mujoco.MjData(tm.model)

    data.qpos[:7] = FRANKA_QPOS_HOME
    for adr in tm.handles.finger_qpos_adr:
        data.qpos[adr] = tm.open_travel

    for name in OBJECT_LAYOUT:
        hx, hy = OBJECT_LAYOUT[name]["pos"]
        hyaw = OBJECT_LAYOUT[name]["yaw"]
        dx, dy = rng.uniform(-POS_JITTER, POS_JITTER, size=2)
        dyaw = float(rng.uniform(-YAW_JITTER, YAW_JITTER))
        adr = tm.obj_free_qposadr[name]
        data.qpos[adr:adr + 3] = [hx + dx, hy + dy, TABLE_TOP_Z + 0.05]
        data.qpos[adr + 3:adr + 7] = _quat_z(hyaw + dyaw)

    ratio = float(rng.uniform(*FRICTION_RATIO_RANGE))
    apply_friction_ratio(tm.model, tm.base_friction, ratio)
    for name in OBJECT_LAYOUT:
        mratio = float(rng.uniform(*MASS_RATIO_RANGE))
        apply_mass_ratio(tm.model, tm.base_mass, tm.obj_body_ids[name], mratio)
    mujoco.mj_setConst(tm.model, data)
    mujoco.mj_forward(tm.model, data)

    profile = adapt_grasp_profile(tm.params, pick)
    result = run_pick_place_diag(
        tm.model, data, obj_name=pick, place_body_name="024_bowl",
        n_fingers=tm.params.n_fingers, aperture=tm.params.aperture,
        hand_to_fingertip=profile.hand_to_fingertip, close_force=profile.close_force,
        yaw_offset_deg=profile.yaw_offset_deg, center_align=profile.center_align,
    )
    result["pick_object"] = pick
    result["friction_ratio"] = ratio
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-trials", type=int, default=60)  # 30 lemon + 30 plum
    ap.add_argument("--seed-base", type=int, default=2000)
    ap.add_argument("--out", type=str, default=str(_ROOT.parent.parent.parent / "results" / "05_cross_simulator" / "finger_contact_timing_mujoco.json"))
    args = ap.parse_args()

    tm = TrialModel(JOINT_BEST_PARAMS)
    t0 = time.time()
    trials = []
    for i in range(args.n_trials):
        pick = DIAG_POOL[i % 2]
        trials.append(run_trial_diag(tm, args.seed_base + i, pick))
    wall = time.time() - t0

    n_success = sum(1 for t in trials if t["success"])
    n_all_engaged = sum(1 for t in trials if t["n_fingers_ever_engaged"] == t["n_fingers_total"])
    spreads = [t["onset_spread_steps"] for t in trials if t["onset_spread_steps"] is not None]

    print(f"MuJoCo winner (3-finger), lemon+plum, n={args.n_trials}: success={n_success}/{args.n_trials}")
    print(f"all-{JOINT_BEST_PARAMS.n_fingers}-fingers-ever-engaged: {n_all_engaged}/{args.n_trials}")
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
