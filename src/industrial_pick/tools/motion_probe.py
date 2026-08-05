"""Quantitative motion probe for the scripted pick-and-place.

Runs ONE scripted rollout (reusing the exact grasp_demo motion primitives so the
dynamics are identical to recording/eval) and samples, every control step (100 Hz):

  * joint positions / velocities (measured) and command tracking error,
  * end-effector (hand link) linear speed and acceleration,
  * the picked object's pose expressed in the HAND frame -> in-gripper slip
    (translational + rotational drift relative to the moment of grasp).

Each step is tagged with its phase (pregrasp / descend / grasp / lift / transport /
release / retreat) so acceleration spikes can be aligned with slip. Outputs a figure
and a per-phase summary table, so we can pinpoint which motion step is the worst.

Usage:
    uv run python franka_fruit_pick/tools/motion_probe.py --pick 011_banana
    uv run python franka_fruit_pick/tools/motion_probe.py --pick 011_banana 018_plum
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

# This tool lives in tools/; put the package dir (its parent) on sys.path so the flat
# sibling imports below resolve.
_PKG = Path(__file__).resolve().parent.parent
if str(_PKG) not in sys.path:
    sys.path.insert(0, str(_PKG))

import genesis as gs

from build_scene import build_scene
from paths import EVAL_RESULTS_DIR
from grasp_demo import (
    FINGERS_DOF,
    LIFT_HAND_Z,
    MOTORS_DOF,
    PLACE_HAND_Z_ABOVE_TARGET,
    PREGRASP_CLEARANCE,
    RETREAT_HAND_Z,
    GRIPPER_OPEN,
    TaskSpec,
    _descend_vertical,
    _goto_direct,
    _goto_interp as landed_goto_interp,
    _goto_plan,
    _grasp_hand_z,
    _ik,
    _obj_xy_yaw,
    _resolve_place,
    _settle,
    _topdown_quat,
    check_success,
)
from randomize import RandomizationConfig, EnvRandomizer

DT = 0.01  # sim timestep (build_scene SimOptions dt=0.01) -> 100 Hz control

# Ordered phases with the color used to shade them in the plot.
PHASE_COLORS = {
    "1_pregrasp": "#cfe8ff",
    "2_descend": "#d7f0d7",
    "3_grasp": "#fff2b8",
    "4_lift": "#ffd8a8",
    "5_transport": "#ffb3b3",
    "6_release": "#e6ccff",
    "7_retreat": "#dddddd",
}


def _np(x) -> np.ndarray:
    if hasattr(x, "detach"):
        x = x.detach().cpu().numpy()
    return np.asarray(x).reshape(-1)


# ---- minimal quaternion helpers (Genesis quats are wxyz) ---------------------
def quat_conj(q: np.ndarray) -> np.ndarray:
    return np.array([q[0], -q[1], -q[2], -q[3]])


def quat_mul(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    w1, x1, y1, z1 = a
    w2, x2, y2, z2 = b
    return np.array([
        w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2,
        w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
        w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
        w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2,
    ])


def quat_to_R(q: np.ndarray) -> np.ndarray:
    w, x, y, z = q / (np.linalg.norm(q) + 1e-12)
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ])


def quat_angle(q: np.ndarray) -> float:
    """Rotation angle (deg) of a wxyz quaternion."""
    w = abs(float(q[0]) / (np.linalg.norm(q) + 1e-12))
    return float(np.degrees(2.0 * np.arccos(np.clip(w, -1.0, 1.0))))


class Probe:
    """Records measured state each control step; tag phase via ``probe.phase``."""

    def __init__(self, bundle, obj_name: str):
        self.bundle = bundle
        self.obj = bundle.ycb[obj_name]
        self.hand = bundle.franka.get_link("hand")
        self.phase = "1_pregrasp"
        self.rows: list[dict] = []

    def on_step(self, action) -> None:
        fr = self.bundle.franka
        act = _np(action)
        q_cmd = act[:7]
        try:
            q_meas = _np(fr.get_dofs_position(MOTORS_DOF))
            v_meas = _np(fr.get_dofs_velocity(MOTORS_DOF))
        except Exception:
            q_meas = _np(fr.get_dofs_position())[:7]
            v_meas = _np(fr.get_dofs_velocity())[:7]
        self.rows.append({
            "phase": self.phase,
            "q": q_meas,
            "qv": v_meas,
            "q_cmd": q_cmd,
            "hand_pos": _np(self.hand.get_pos()),
            "hand_quat": _np(self.hand.get_quat()),
            "obj_pos": _np(self.obj.get_pos()),
            "obj_quat": _np(self.obj.get_quat()),
        })


def instrumented_rollout(bundle, task: TaskSpec, probe: Probe, *, mode: str = "baseline", max_dq: float = 0.006) -> None:
    """Mirror grasp_demo.run_pick_place, tagging each phase. ``mode`` controls how the two
    GRASPED-object moves (lift, transport) are executed, to compare before/after:
      * "baseline" -> the OLD _goto_direct (setpoint jump / max-accel dash)
      * "landed"   -> the NEW grasp_demo._goto_interp (velocity-limited, as shipped)
    All other phases are identical across modes so the effect is isolated to lift+transport.
    """
    pick_entity = bundle.ycb[task.pick_object]
    profile = task.grasp_profile()

    _settle(bundle, 60)  # not recorded (matches run_pick_place)

    obj_pos, obj_yaw = _obj_xy_yaw(pick_entity)
    grasp_quat = _topdown_quat(obj_yaw + profile.yaw_offset)

    probe.phase = "1_pregrasp"
    pregrasp = np.array([obj_pos[0], obj_pos[1], obj_pos[2] + PREGRASP_CLEARANCE])
    _goto_plan(bundle, pregrasp, grasp_quat, finger=GRIPPER_OPEN, recorder=probe)

    probe.phase = "2_descend"
    grasp_z = _grasp_hand_z(pick_entity, profile)
    _descend_vertical(bundle, (obj_pos[0], obj_pos[1]), pregrasp[2], grasp_z, grasp_quat,
                      finger=GRIPPER_OPEN, recorder=probe)
    grasp = np.array([obj_pos[0], obj_pos[1], grasp_z])

    probe.phase = "3_grasp"
    _goto_direct(bundle, grasp, grasp_quat, finger_cmd=0.0, steps=100,
                 close_force=profile.close_force, recorder=probe)

    def grasped_move(pos, steps):
        if mode == "baseline":
            _goto_direct(bundle, pos, grasp_quat, finger_cmd=0.0, steps=steps,
                         close_force=profile.close_force, recorder=probe)
        elif mode == "landed":
            landed_goto_interp(bundle, pos, grasp_quat, finger_cmd=0.0,
                               close_force=profile.close_force, max_dq=max_dq, recorder=probe)
        else:
            raise ValueError(mode)

    probe.phase = "4_lift"
    lift = np.array([grasp[0], grasp[1], LIFT_HAND_Z])
    grasped_move(lift, 100)

    probe.phase = "5_transport"
    place_xy, place_ref_z, _ = _resolve_place(bundle, task.place_target)
    above = np.array([place_xy[0], place_xy[1], place_ref_z + PLACE_HAND_Z_ABOVE_TARGET])
    grasped_move(above, 120)

    probe.phase = "6_release"
    _goto_direct(bundle, above, grasp_quat, finger_cmd=GRIPPER_OPEN, steps=80, recorder=probe)

    probe.phase = "7_retreat"
    retreat = np.array([place_xy[0], place_xy[1], RETREAT_HAND_Z])
    _goto_direct(bundle, retreat, grasp_quat, finger_cmd=GRIPPER_OPEN, steps=80, recorder=probe)
    _settle(bundle, 60, recorder=probe)


def analyze(probe: Probe) -> dict:
    rows = probe.rows
    n = len(rows)
    phases = [r["phase"] for r in rows]
    q = np.stack([r["q"] for r in rows])          # (n,7) measured joint pos
    qv = np.stack([r["qv"] for r in rows])        # (n,7) measured joint vel
    q_cmd = np.stack([r["q_cmd"] for r in rows])  # (n,7) commanded joint pos
    hand_pos = np.stack([r["hand_pos"] for r in rows])   # (n,3)
    hand_quat = np.stack([r["hand_quat"] for r in rows]) # (n,4)
    obj_pos = np.stack([r["obj_pos"] for r in rows])     # (n,3)
    obj_quat = np.stack([r["obj_quat"] for r in rows])   # (n,4)

    t = np.arange(n) * DT

    # End-effector kinematics (finite difference of measured hand pos).
    hand_vel = np.gradient(hand_pos, DT, axis=0)
    hand_speed = np.linalg.norm(hand_vel, axis=1)
    hand_acc = np.linalg.norm(np.gradient(hand_vel, DT, axis=0), axis=1)

    # Joint accel (from measured velocities) and command tracking error.
    joint_acc = np.gradient(qv, DT, axis=0)                 # (n,7)
    max_joint_acc = np.max(np.abs(joint_acc), axis=1)       # (n,)
    track_err = np.linalg.norm(q_cmd - q, axis=1)           # (n,) rad, ||cmd - meas||

    # In-gripper object slip: object pose in the HAND frame, referenced to grasp end.
    slip_trans = np.zeros(n)
    slip_rot = np.zeros(n)
    grasp_idx = [i for i, p in enumerate(phases) if p == "3_grasp"]
    ref_i = grasp_idx[-1] if grasp_idx else 0

    def obj_in_hand(i):
        R = quat_to_R(hand_quat[i])
        p_rel = R.T @ (obj_pos[i] - hand_pos[i])
        q_rel = quat_mul(quat_conj(hand_quat[i]), obj_quat[i])
        return p_rel, q_rel

    p_ref, q_ref = obj_in_hand(ref_i)
    for i in range(n):
        p_rel, q_rel = obj_in_hand(i)
        slip_trans[i] = np.linalg.norm(p_rel - p_ref) * 1000.0  # mm
        slip_rot[i] = quat_angle(quat_mul(quat_conj(q_ref), q_rel))  # deg

    # Slip in the gripper is only meaningful while the object is actually held:
    # from the grasp reference up to (but not including) the intentional release.
    # Outside that window the object has detached, so mask it (NaN) to avoid the
    # metric exploding when the freed object stays put while the hand flies away.
    release_list = [i for i, p in enumerate(phases) if p == "6_release"]
    release_i = release_list[0] if release_list else n
    slip_trans[:ref_i] = 0.0
    slip_rot[:ref_i] = 0.0
    slip_trans[release_i:] = np.nan
    slip_rot[release_i:] = np.nan

    return {
        "t": t, "phases": phases, "ref_i": ref_i, "release_i": release_i,
        "hand_speed": hand_speed, "hand_acc": hand_acc,
        "max_joint_acc": max_joint_acc, "track_err": track_err,
        "slip_trans": slip_trans, "slip_rot": slip_rot,
    }


def phase_segments(phases: list[str]):
    segs = []
    start = 0
    for i in range(1, len(phases) + 1):
        if i == len(phases) or phases[i] != phases[start]:
            segs.append((phases[start], start, i))
            start = i
    return segs


def summarize(res: dict) -> list[dict]:
    segs = phase_segments(res["phases"])
    out = []
    st = res["slip_trans"]
    sr = res["slip_rot"]
    def _held_gain(arr, a, b):
        seg = arr[a:b]
        if np.all(np.isnan(seg)):
            return float("nan")
        return float(np.nanmax(seg) - np.nan_to_num(arr[a], nan=np.nanmin(seg)))

    for name, a, b in segs:
        sl = slice(a, b)
        out.append({
            "phase": name,
            "steps": b - a,
            "peak_hand_acc": float(np.max(res["hand_acc"][sl])),
            "peak_hand_speed": float(np.max(res["hand_speed"][sl])),
            "peak_joint_acc": float(np.max(res["max_joint_acc"][sl])),
            "peak_track_err": float(np.max(res["track_err"][sl])),
            "slip_trans_gain": _held_gain(st, a, b),
            "slip_rot_gain": _held_gain(sr, a, b),
        })
    return out


def plot(res: dict, summ: list[dict], obj_name: str, out_path: Path) -> None:
    segs = phase_segments(res["phases"])
    t = res["t"]
    fig, axes = plt.subplots(4, 1, figsize=(12, 12), sharex=True)

    def shade(ax):
        for name, a, b in segs:
            ax.axvspan(t[a], t[min(b, len(t) - 1)], color=PHASE_COLORS.get(name, "#eee"), alpha=0.5, lw=0)

    ax = axes[0]
    shade(ax)
    ax.plot(t, res["hand_acc"], color="crimson", lw=1.3)
    ax.set_ylabel("EE accel\n(m/s²)")
    ax.set_title(f"{obj_name}: motion vs in-gripper slip  (phases shaded)")

    ax = axes[1]
    shade(ax)
    ax.plot(t, res["hand_speed"], color="darkorange", lw=1.3, label="EE speed (m/s)")
    ax.plot(t, res["track_err"], color="navy", lw=1.1, label="cmd tracking err ‖q_cmd−q‖ (rad)")
    ax.legend(loc="upper right", fontsize=8)
    ax.set_ylabel("EE speed /\ntrack err")

    ax = axes[2]
    shade(ax)
    ax.plot(t, res["max_joint_acc"], color="purple", lw=1.1)
    ax.set_ylabel("max |joint\naccel| (rad/s²)")

    ax = axes[3]
    shade(ax)
    ax.plot(t, res["slip_trans"], color="black", lw=1.6, label="translational slip (mm)")
    ax.plot(t, res["slip_rot"], color="green", lw=1.3, label="rotational slip (deg)")
    ax.legend(loc="upper left", fontsize=8)
    ax.set_ylabel("in-gripper\nslip")
    ax.set_xlabel("time (s)")

    # Phase labels along the top.
    for name, a, b in segs:
        xc = 0.5 * (t[a] + t[min(b, len(t) - 1)])
        axes[0].text(xc, axes[0].get_ylim()[1] * 0.92, name.split("_")[1],
                     ha="center", va="top", fontsize=8, rotation=0)

    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=130)
    plt.close(fig)


def held_slip_max(res: dict) -> tuple[float, float]:
    """Max in-gripper slip (mm, deg) over the held window (grasp ref .. release)."""
    st = res["slip_trans"]
    sr = res["slip_rot"]
    a, b = res["ref_i"], res["release_i"]
    seg_t = st[a:b]
    seg_r = sr[a:b]
    mt = float(np.nanmax(seg_t)) if seg_t.size and not np.all(np.isnan(seg_t)) else 0.0
    mr = float(np.nanmax(seg_r)) if seg_r.size and not np.all(np.isnan(seg_r)) else 0.0
    return mt, mr


def phase_row(summ: list[dict], name: str) -> dict:
    return next((s for s in summ if s["phase"] == name), {})


def run_single(bundle, obj, place, out_dir):
    task = TaskSpec(pick_object=obj, place_target=place)
    probe = Probe(bundle, obj)
    instrumented_rollout(bundle, task, probe)
    res = analyze(probe)
    summ = summarize(res)
    print(f"\n===== motion probe: {obj} =====")
    hdr = f"{'phase':<12}{'steps':>6}{'pkEEacc':>9}{'pkEEspd':>9}{'pkJacc':>9}{'pkTrkErr':>9}{'dSlipMM':>9}{'dSlipDeg':>9}"
    print(hdr)
    for s in summ:
        print(f"{s['phase']:<12}{s['steps']:>6}{s['peak_hand_acc']:>9.2f}{s['peak_hand_speed']:>9.3f}"
              f"{s['peak_joint_acc']:>9.1f}{s['peak_track_err']:>9.3f}{s['slip_trans_gain']:>9.2f}{s['slip_rot_gain']:>9.2f}")
    out_path = out_dir / f"{obj}_motion_probe.png"
    plot(res, summ, obj, out_path)
    print(f"[probe] wrote {out_path}")


def _rollout_row(bundle, randomizer, obj, place, seed, mode, max_dq):
    """One instrumented rollout at a given initial state; returns metrics + success flag."""
    randomizer.reset(seed=seed)  # identical initial object/arm poses across modes
    task = TaskSpec(pick_object=obj, place_target=place)
    probe = Probe(bundle, obj)
    instrumented_rollout(bundle, task, probe, mode=mode, max_dq=max_dq)
    res = analyze(probe)
    summ = summarize(res)
    lift = phase_row(summ, "4_lift")
    trans = phase_row(summ, "5_transport")
    mt, mr = held_slip_max(res)
    return {
        "mode": mode, "seed": seed,
        "tot_steps": len(probe.rows),
        "lt_steps": lift.get("steps", 0) + trans.get("steps", 0),
        "tr_pk_ee_acc": trans.get("peak_hand_acc", float("nan")),
        "tr_pk_j_acc": trans.get("peak_joint_acc", float("nan")),
        "lift_pk_ee_acc": lift.get("peak_hand_acc", float("nan")),
        "slip_mm": mt, "slip_deg": mr,
        "success": bool(check_success(bundle, task)),
    }


def run_compare(bundle, obj, place, seeds, max_dq):
    """Before/after robustness comparison over multiple seeds. For each seed the baseline
    (_goto_direct) and the landed velocity-limited primitive are run from the SAME initial
    state, so metric deltas isolate the primitive change."""
    modes = ["baseline", "landed"]
    per_mode = {m: [] for m in modes}
    print(f"\n===== before/after: {obj} (max_dq={max_dq} rad/step = {max_dq/DT:.2f} rad/s, "
          f"seeds={list(seeds)}) =====")
    hdr = (f"{'seed':>4} {'mode':<9}{'succ':>5}{'totSteps':>9}{'trEEacc':>9}{'trJacc':>9}"
           f"{'liftEEacc':>10}{'slip_mm':>9}{'slip_deg':>9}")
    print(hdr)
    for seed in seeds:
        randomizer = EnvRandomizer(bundle, RandomizationConfig(randomize_pick=False, seed=seed))
        for mode in modes:
            r = _rollout_row(bundle, randomizer, obj, place, seed, mode, max_dq)
            per_mode[mode].append(r)
            print(f"{seed:>4} {mode:<9}{('Y' if r['success'] else 'n'):>5}{r['tot_steps']:>9}"
                  f"{r['tr_pk_ee_acc']:>9.1f}{r['tr_pk_j_acc']:>9.1f}{r['lift_pk_ee_acc']:>10.1f}"
                  f"{r['slip_mm']:>9.1f}{r['slip_deg']:>9.1f}")

    def _mean(rows, k):
        vals = [x[k] for x in rows if not (isinstance(x[k], float) and np.isnan(x[k]))]
        return float(np.mean(vals)) if vals else float("nan")

    b, l = per_mode["baseline"], per_mode["landed"]
    n = len(seeds)
    print(f"--- aggregate over {n} seeds (mean; success = #placed/{n}) ---")
    for name, rows in (("baseline", b), ("landed", l)):
        print(f"{name:<9} succ={sum(x['success'] for x in rows)}/{n}  "
              f"trEEacc={_mean(rows,'tr_pk_ee_acc'):.1f}  liftEEacc={_mean(rows,'lift_pk_ee_acc'):.1f}  "
              f"slip_mm={_mean(rows,'slip_mm'):.1f}  slip_deg={_mean(rows,'slip_deg'):.1f}  "
              f"steps={_mean(rows,'tot_steps'):.0f}")
    base_slip, land_slip = _mean(b, "slip_mm"), _mean(l, "slip_mm")
    base_acc, land_acc = _mean(b, "tr_pk_ee_acc"), _mean(l, "tr_pk_ee_acc")
    base_st, land_st = _mean(b, "tot_steps"), _mean(l, "tot_steps")
    pct = lambda new, old: (new - old) / old * 100.0 if old and not np.isnan(old) else float("nan")
    print(f"landed vs baseline:  Δslip_mm={pct(land_slip, base_slip):+.0f}%  "
          f"ΔtrEEacc={pct(land_acc, base_acc):+.0f}%  Δsteps={pct(land_st, base_st):+.0f}%")
    return per_mode


def main() -> None:
    ap = argparse.ArgumentParser(description="Probe scripted-rollout motion vs in-gripper slip.")
    ap.add_argument("--pick", nargs="+", default=["011_banana"])
    ap.add_argument("--place", default="024_bowl")
    ap.add_argument("-c", "--cpu", action="store_true")
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--compare", action="store_true", help="Run baseline vs landed primitive over --seeds.")
    ap.add_argument("--seeds", type=int, nargs="+", default=[0], help="Randomizer seeds for --compare.")
    ap.add_argument("--max-dq", type=float, default=0.006, help="Landed per-step joint cap (rad); joint speed = max_dq/dt.")
    args = ap.parse_args()

    out_dir = Path(args.out_dir) if args.out_dir else EVAL_RESULTS_DIR / "motion_probe"
    gs.init(backend=gs.cpu if args.cpu else gs.gpu)
    bundle = build_scene(show_viewer=False, n_envs=1, add_world_cam=True, add_wrist_cam=True)

    for obj in args.pick:
        if args.compare:
            run_compare(bundle, obj, args.place, args.seeds, args.max_dq)
        else:
            run_single(bundle, obj, args.place, out_dir)


if __name__ == "__main__":
    main()
