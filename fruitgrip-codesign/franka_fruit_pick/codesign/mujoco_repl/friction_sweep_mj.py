"""Escalation 1 (session 8): controlled friction dose-response sweep, MuJoCo side.

Converts the correlational friction finding from cross_simulator_findings.md S5
(winner's failures cluster at friction ratio >=1.06 in MuJoCo, >=1.24 in Genesis,
both confirmed) into a controlled sweep: friction ratio fixed (not drawn) at each
of 31 values from 0.5 to 2.0 in 0.05 steps -- deliberately past the original DR
range's 1.3 ceiling to find where the failure regime saturates, not just where it
starts.

Design decision (brief explicitly asks this be made and documented): mass ratio is
fixed at 1.0 (no mass randomization) at every point in the sweep, but POSE JITTER
(+/-3cm position, +/-30deg yaw -- randomize.RandomizationConfig's own defaults) is
KEPT ON. Reasoning: with friction fixed AND mass fixed AND no pose jitter, physics
is fully deterministic given a seed -- 30 "trials" at a single friction value would
all produce the identical outcome, making a success RATE meaningless (it could only
ever read 0% or 100%, never anything between, regardless of the truth). Pose jitter
is the one remaining, physically meaningful source of trial-to-trial variance, and
keeping it is what makes "30 trials per friction value" a real sample rather than a
single repeated data point. This choice is applied identically on the Genesis side
(see finger_contact_batch_genesis.py's sibling script) for comparability.

Object pool: lemon+plum only, matching the finger-contact diagnostic this escalates
-- banana's grasp is independently broken in this MuJoCo port (see
cross_simulator_findings.md S3) and would just inject a 100%-failure confound
unrelated to friction.
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

from confirmation_eval_mj import TrialModel, POS_JITTER, YAW_JITTER, FRANKA_QPOS_HOME, _quat_z, wilson_ci  # noqa: E402
from scene_builder import OBJECT_LAYOUT, TABLE_TOP_Z  # noqa: E402
from domain_rand import apply_friction_ratio, apply_mass_ratio  # noqa: E402
from grasp_profile import adapt_grasp_profile  # noqa: E402
from controller import run_pick_place  # noqa: E402
from run_attribution import BASELINE_PARAMS, JOINT_BEST_PARAMS  # noqa: E402

DIAG_POOL = ("014_lemon", "018_plum")
FRICTION_VALUES = np.round(np.arange(0.5, 2.0001, 0.05), 2).tolist()
N_TRIALS_PER_POINT = 30


def run_trial(tm: TrialModel, seed: int, pick: str, friction_ratio: float) -> dict:
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

    apply_friction_ratio(tm.model, tm.base_friction, friction_ratio)
    for name in OBJECT_LAYOUT:
        apply_mass_ratio(tm.model, tm.base_mass, tm.obj_body_ids[name], 1.0)  # fixed, no mass DR
    mujoco.mj_setConst(tm.model, data)
    mujoco.mj_forward(tm.model, data)

    profile = adapt_grasp_profile(tm.params, pick)
    result = run_pick_place(
        tm.model, data, obj_name=pick, place_body_name="024_bowl",
        n_fingers=tm.params.n_fingers, aperture=tm.params.aperture,
        hand_to_fingertip=profile.hand_to_fingertip, close_force=profile.close_force,
        yaw_offset_deg=profile.yaw_offset_deg, center_align=profile.center_align,
    )
    result["pick_object"] = pick
    return result


def sweep_design(params, label: str, seed_base: int, log_fn=print) -> dict:
    tm = TrialModel(params)
    points = []
    t0 = time.time()
    for fi, friction in enumerate(FRICTION_VALUES):
        trials = []
        for i in range(N_TRIALS_PER_POINT):
            pick = DIAG_POOL[i % 2]
            seed = seed_base + fi * N_TRIALS_PER_POINT + i
            trials.append(run_trial(tm, seed, pick, friction))
        successes = sum(1 for t in trials if t["success"])
        ci_lo, ci_hi = wilson_ci(successes, N_TRIALS_PER_POINT)
        force = np.array([t["peak_contact_force"] for t in trials])
        points.append({
            "friction_ratio": friction, "n": N_TRIALS_PER_POINT, "successes": successes,
            "success_rate": successes / N_TRIALS_PER_POINT, "success_rate_95ci": [ci_lo, ci_hi],
            "mean_peak_force_N": float(force.mean()),
        })
        log_fn(f"[{label}] friction={friction:.2f} success={successes}/{N_TRIALS_PER_POINT} ({successes/N_TRIALS_PER_POINT:.1%})")
    wall = time.time() - t0
    return {"label": label, "params": vars(params), "points": points, "wall_seconds": wall}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed-base", type=int, default=5000)
    ap.add_argument("--out", type=str, default=str(_ROOT.parent.parent.parent / "results" / "05_cross_simulator" / "friction_doseresponse_mujoco.json"))
    args = ap.parse_args()

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
