"""Session 7: MuJoCo replication of confirmation_eval.py's protocol -- frozen
baseline (BASELINE_PARAMS) vs frozen winner (JOINT_BEST_PARAMS), >=30 paired trials
each, same DR ranges as Genesis (friction 0.7-1.3x, mass 0.8-1.2x). Does NOT re-run
search/optimization -- both designs are copied verbatim from run_attribution.py, per
the project brief.

Per-trial protocol (mirrors randomize.py's EnvRandomizer.reset(), same knob values --
pos_jitter=0.03m, yaw_jitter=30deg, friction_ratio_range=(0.7,1.3),
mass_ratio_range=(0.8,1.2) -- but its own independent RNG draws per engine, not a
bit-exact replay of Genesis's random stream, since that isn't meaningful across
engines and isn't what the brief asks for):
  1. Reset Franka to FRANKA_QPOS home, fingers open.
  2. Re-place all 3 pool objects (banana/lemon/plum) at their home slot +/- jitter.
  3. Sample one shared friction ratio, applied to Franka + all 3 objects + table.
  4. Sample an independent mass ratio per object.
  5. Uniformly pick one object from the pool as this trial's pick target.
  6. Run the scripted episode (controller.run_pick_place) with this design's
     co-adapted grasp profile (grasp_profile.adapt_grasp_profile) for the picked
     object.
"""
from __future__ import annotations

import argparse
import json
import math
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

from scene_builder import build_scene_xml, OBJECT_LAYOUT, TABLE_TOP_Z, FRANKA_CONTYPE  # noqa: E402
from controller import MjSceneHandles, run_pick_place  # noqa: E402
from domain_rand import (  # noqa: E402
    capture_base_friction, capture_base_mass, apply_friction_ratio, apply_mass_ratio, body_geom_ids,
)
from grasp_profile import adapt_grasp_profile  # noqa: E402
from gripper_gen import generate_gripper_xml  # noqa: E402
from run_attribution import BASELINE_PARAMS, JOINT_BEST_PARAMS  # noqa: E402

POOL = tuple(OBJECT_LAYOUT.keys())
FRANKA_QPOS_HOME = np.array([0.0, -0.3, 0.0, -2.0, 0.0, 1.7, 0.79])
POS_JITTER = 0.03  # m, matches randomize.RandomizationConfig.pos_jitter
YAW_JITTER = 30.0  # deg, matches randomize.RandomizationConfig.yaw_jitter
FRICTION_RATIO_RANGE = (0.7, 1.3)
MASS_RATIO_RANGE = (0.8, 1.2)


def _quat_z(deg: float) -> np.ndarray:
    theta = math.radians(deg) / 2
    return np.array([math.cos(theta), 0.0, 0.0, math.sin(theta)])


def wilson_ci(successes: int, n: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = successes / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
    return (max(0.0, center - half), min(1.0, center + half))


class TrialModel:
    def __init__(self, params):
        self.params = params
        gripper_xml = generate_gripper_xml(params)
        self.xml_path = build_scene_xml(gripper_xml, f"confeval_{params.key()}")
        self.model = mujoco.MjModel.from_xml_path(str(self.xml_path))

        self.obj_body_ids = {n: mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_BODY, n) for n in POOL}
        self.obj_free_qposadr = {
            n: self.model.jnt_qposadr[mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_JOINT, f"{n}_free")]
            for n in POOL
        }
        self.table_id = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_BODY, "table")
        self.bowl_id = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_BODY, "024_bowl")

        franka_geoms = [g for g in range(self.model.ngeom) if self.model.geom_contype[g] == int(FRANKA_CONTYPE)]
        ycb_geoms = [g for n in POOL for g in body_geom_ids(self.model, self.obj_body_ids[n])]
        table_geoms = body_geom_ids(self.model, self.table_id)
        self.friction_geoms = franka_geoms + ycb_geoms + table_geoms
        self.base_friction = capture_base_friction(self.model, self.friction_geoms)
        self.base_mass = capture_base_mass(self.model, [self.obj_body_ids[n] for n in POOL])

        self.handles = MjSceneHandles(self.model, params.n_fingers)
        self.open_travel = max(params.aperture / 2 - 0.002, 0.002)

    def run_trial(self, seed: int) -> dict:
        rng = np.random.default_rng(seed)
        data = mujoco.MjData(self.model)

        data.qpos[:7] = FRANKA_QPOS_HOME
        for adr in self.handles.finger_qpos_adr:
            data.qpos[adr] = self.open_travel

        for name in POOL:
            hx, hy = OBJECT_LAYOUT[name]["pos"]
            hyaw = OBJECT_LAYOUT[name]["yaw"]
            dx, dy = rng.uniform(-POS_JITTER, POS_JITTER, size=2)
            dyaw = float(rng.uniform(-YAW_JITTER, YAW_JITTER))
            adr = self.obj_free_qposadr[name]
            data.qpos[adr:adr + 3] = [hx + dx, hy + dy, TABLE_TOP_Z + 0.05]
            data.qpos[adr + 3:adr + 7] = _quat_z(hyaw + dyaw)

        ratio = float(rng.uniform(*FRICTION_RATIO_RANGE))
        apply_friction_ratio(self.model, self.base_friction, ratio)
        for name in POOL:
            mratio = float(rng.uniform(*MASS_RATIO_RANGE))
            apply_mass_ratio(self.model, self.base_mass, self.obj_body_ids[name], mratio)
        mujoco.mj_setConst(self.model, data)

        pick = str(rng.choice(POOL))
        mujoco.mj_forward(self.model, data)

        profile = adapt_grasp_profile(self.params, pick)
        t0 = time.time()
        result = run_pick_place(
            self.model, data, obj_name=pick, place_body_name="024_bowl",
            n_fingers=self.params.n_fingers, aperture=self.params.aperture,
            hand_to_fingertip=profile.hand_to_fingertip, close_force=profile.close_force,
            yaw_offset_deg=profile.yaw_offset_deg, center_align=profile.center_align,
        )
        result["pick_object"] = pick
        result["wall"] = time.time() - t0
        result["friction_ratio"] = ratio
        return result


def run_confirmation(params, *, n_trials: int, seed_base: int, label: str, log_fn=print) -> dict:
    tm = TrialModel(params)
    t0 = time.time()
    trials = [tm.run_trial(seed_base + i) for i in range(n_trials)]
    wall = time.time() - t0

    successes = sum(1 for t in trials if t["success"])
    ci_lo, ci_hi = wilson_ci(successes, n_trials)
    force = np.array([t["peak_contact_force"] for t in trials])
    slip = np.array([t["max_slip"] for t in trials])
    uptime = np.array([t["contact_uptime_frac"] for t in trials])

    log_fn(
        f"{label}: n={n_trials} successes={successes} success_rate={successes/n_trials:.3f} "
        f"(95% CI [{ci_lo:.3f}, {ci_hi:.3f}]) peak_force={force.mean():.2f}+/-{force.std(ddof=1):.2f}N "
        f"max_slip={slip.mean()*1000:.1f}+/-{slip.std(ddof=1)*1000:.1f}mm wall={wall:.1f}s"
    )
    return {
        "label": label, "params": vars(params), "n_trials": n_trials, "successes": successes,
        "success_rate": successes / n_trials, "success_rate_95ci": [ci_lo, ci_hi],
        "mean_contact_uptime": float(uptime.mean()),
        "mean_peak_force_N": float(force.mean()), "std_peak_force_N": float(force.std(ddof=1)),
        "mean_max_slip_m": float(slip.mean()), "std_max_slip_m": float(slip.std(ddof=1)),
        "per_trial": trials, "wall_seconds": wall,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="MuJoCo cross-simulator confirmation eval.")
    ap.add_argument("--n-trials", type=int, default=30)
    ap.add_argument("--seed-base", type=int, default=1000)
    ap.add_argument("--out", type=str, default=str(_ROOT.parent.parent.parent / "results" / "05_cross_simulator" / "cross_simulator_confirmation_eval.json"))
    args = ap.parse_args()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    print(f"=== MuJoCo baseline (frozen, n={args.n_trials}) ===")
    baseline = run_confirmation(BASELINE_PARAMS, n_trials=args.n_trials, seed_base=args.seed_base, label="baseline")

    print(f"\n=== MuJoCo winner (frozen 3-finger, n={args.n_trials}) ===")
    winner = run_confirmation(JOINT_BEST_PARAMS, n_trials=args.n_trials, seed_base=args.seed_base, label="winner")

    print("\n=== paired comparison ===")
    print(f"baseline: {baseline['success_rate']:.1%} (95% CI [{baseline['success_rate_95ci'][0]:.1%}, {baseline['success_rate_95ci'][1]:.1%}])")
    print(f"winner:   {winner['success_rate']:.1%} (95% CI [{winner['success_rate_95ci'][0]:.1%}, {winner['success_rate_95ci'][1]:.1%}])")
    ci_overlap = not (winner["success_rate_95ci"][0] > baseline["success_rate_95ci"][1] or baseline["success_rate_95ci"][0] > winner["success_rate_95ci"][1])
    print(f"95% CIs {'OVERLAP' if ci_overlap else 'do NOT overlap'}")

    results = {
        "baseline": baseline, "winner": winner, "ci_overlap": ci_overlap,
        "force_delta_N": winner["mean_peak_force_N"] - baseline["mean_peak_force_N"],
        "slip_delta_m": winner["mean_max_slip_m"] - baseline["mean_max_slip_m"],
        "wall_seconds": time.time() - t0,
    }
    out_path.write_text(json.dumps(results, indent=2))
    print(f"\nwrote {out_path} ({results['wall_seconds']:.1f}s total)")


if __name__ == "__main__":
    main()
