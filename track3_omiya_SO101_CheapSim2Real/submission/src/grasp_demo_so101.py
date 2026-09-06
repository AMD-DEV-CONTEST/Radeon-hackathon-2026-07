"""Scripted pick-and-place for the SO101 scene (cube → white target sheet).

Follows the structure of grasp_demo.py (Franka): a TaskSpec describes what to
pick and where to place; run_pick_place() executes a scripted state machine
using IK waypoints with per-step joint interpolation.

The SO101 arm has 5 DOF + gripper, so all approaches are top-down
(tool axis vertical); yaw around the vertical axis stays free via wrist_roll.
IK targets the URDF's fingertip TCP link ``gripper_frame_link`` (its +z points
along the approach direction, i.e. straight down during grasping).

Examples:
    # pick the red cube and place it onto the white target (default)
    uv run python -m franka_fruit_pick.grasp_demo_so101 --save-video

    # watch it live in the viewer
    uv run python -m franka_fruit_pick.grasp_demo_so101 -v
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import genesis as gs
from scipy.spatial.transform import Rotation as _Rot

from build_scene_so101 import (
    CUBE_SIZE,
    SO101_HOME_QPOS,
    SO101_POS,
    TARGET_POS,
    TARGET_SIZE,
    WORKSPACE_Z,
    SceneBundleSO101,
    build_scene_so101,
    default_backend,
)

# Arm base position on the table (xy): grasp bearing and transport arcs are
# computed around this point.
BASE_XY = np.array(SO101_POS[:2], dtype=np.float64)

# --- Control gains (STS3215-class servos; tuned for stable position tracking) --

ARM_DOFS     = np.arange(5)           # shoulder_pan..wrist_roll
GRIPPER_DOF  = 5
SO101_KP     = np.array([120.0, 120.0, 120.0, 120.0, 60.0, 40.0])
SO101_KV     = np.array([10.0, 10.0, 10.0, 10.0, 5.0, 3.0])
SO101_FORCE  = np.array([10.0, 10.0, 10.0, 10.0, 5.0, 4.0])   # |torque| clamp per dof
                         # jaw clamp 4.0 is calibrated: stronger punches the cube out of
                         # the closing rake, weaker cannot hold it through transport

# --- Gripper jaw angles (rad; revolute jaw, open = large angle) ---------------

GRIPPER_OPEN   = 1.3     # open enough that the jaw clears the cube during descent
                         # (verified 5/5 holds); also the resting state at start/end,
                         # so no separate open transition is needed before grasping
GRIPPER_IDLE   = GRIPPER_OPEN
GRIPPER_RELEASE = 0.8    # set-down release: just enough to free the cube — opening
                         # all the way at the sheet flicks the cube forward
GRIPPER_CLOSE  = -0.05   # commanded past contact → PD squeeze holds the cube
                         # (jaw stalls on the 4 cm cube at ~+0.27 rad; verified holding)

# --- Motion parameters ---------------------------------------------------------

# Genesis merges fixed joints, so the URDF's gripper_frame_link TCP is welded into
# gripper_link. IK targets gripper_link with the TCP expressed as a local_point
# (the gripper_frame_joint origin from the URDF).
TCP_LINK       = "gripper_link"
TCP_LOCAL      = np.array([-0.0079, -0.000218, -0.098127])   # fixed fingertip in gripper_link frame
# SO101 grasp geometry (measured in-sim from the URDF meshes): the jaw is single-
# actuated and swings in the arm's sagittal plane — with the jaw open its tip sits
# ~6 cm ABOVE the fixed fingertip, so closing pinches the object between the
# descending jaw and the fixed finger, tong-style. The strategy is therefore:
# put the fixed fingertip just BEYOND the cube (along the base→cube bearing) at
# table height, then close so the jaw sweeps the cube against the fixed finger.
# SO101 grasp geometry (measured in-sim, jaw-angle sweep of the URDF meshes):
# the moving jaw opens to ~9.5 cm BEYOND the fixed fingertip and, when closing,
# rakes down and back along the table toward the base — sweeping anything in front
# of the fixed finger into it. The gripper grabs like a scoop, so:
#   * the fixed finger descends on the NEAR side of the object (base side),
#   * the open jaw clears the object's far side by >4 cm during descent,
#   * closing drags the object against the fixed finger; the jaw stalls on it
#     (tip-to-finger gap is 2 cm fully closed, so a 4 cm cube is held squeezed).
GRASP_STANDOFF  = 0.028   # fingertip this far on the NEAR side of the object center:
                          # cube half (0.02) + finger thickness margin (calibrated 5/5 holds)
PLACE_HELD_OFFSET = 0.009 # while held, the cube rides this far on the near side of the
                          # fingertip (measured), so aim the fingertip this far PAST the
                          # place center for a centered set-down
FINGER_TABLE_Z  = 0.016   # fingertip height above the table at grasp (m) — just below
                          # cube mid-height (calibrated 5/5 holds with substeps=4)
HOVER_ABOVE    = 0.06    # TCP height above cube top for pregrasp/lift (m)
GRASP_DEPTH    = CUBE_SIZE[2] / 2   # TCP at cube-center height at grasp (fingers straddle it)
PLACE_DROP     = 0.020   # TCP height above the sheet when releasing (m)
MOVE_MAX_DQ    = 0.010   # max per-step joint delta (rad) → ~1 rad/s at 100 Hz
                         # (calibrated: slower ramps let the cube settle out of the rake)
MOVE_MIN_STEPS = 30      # floor so short moves still ramp smoothly
SETTLE_STEPS   = 60      # hold steps after reaching each waypoint (PD creep needs ~0.5 s)
GRIP_STEPS     = 280     # steps to ramp the jaw closed/open (~0.5 rad/s). Slow enough
                         # that the jaw rakes the object without visible contact bounce
                         # (140 closed at ~1 rad/s and the cube recoiled at first touch)
GRASP_ATTEMPTS = 2       # re-approach once if the lift check shows the cube was not held
                         # (the rake grasp is marginal in small workspace pockets; a second
                         # attempt from the cube's re-read position usually lands)
HELD_MIN_Z     = WORKSPACE_Z + 0.04   # cube center above this after lift → it is held

# Success tolerance: cube center within the white sheet, resting on the table.
PLACE_TOL_XY = TARGET_SIZE[0] / 2 - CUBE_SIZE[0] / 4   # ~0.045 m
PLACE_TOL_Z  = 0.05


@dataclass
class TaskSpec:
    """What to pick and where to place it."""

    place_xy: tuple[float, float] = (TARGET_POS[0], TARGET_POS[1])


def check_success(bundle: SceneBundleSO101, task: TaskSpec | None = None) -> bool:
    """Task success, independent of how the arm was driven (scripted or policy):
    cube center inside the white sheet footprint, resting at table height."""
    task = task or TaskSpec()
    final = np.asarray(bundle.cube.get_pos().tolist(), dtype=np.float64)
    err_xy = np.abs(final[:2] - np.asarray(task.place_xy, dtype=np.float64))
    return bool((err_xy <= PLACE_TOL_XY).all() and final[2] <= WORKSPACE_Z + PLACE_TOL_Z)


# --- IK helpers ----------------------------------------------------------------

# Max forward tilt of the tool axis from vertical. The manipulation protocol keeps
# the gripper vertical (teleop uses the same convention): vertical descent/ascent,
# constant-height transport. A small allowance keeps IK well-conditioned.
MAX_TOOL_TILT_DEG = 5.0


def _tool_tilt_deg(bundle: SceneBundleSO101, q6: np.ndarray) -> float:
    """Tool-axis angle from straight-down for a candidate qpos (pure FK, no sim state)."""
    _, links_quat = bundle.robot.forward_kinematics(np.asarray(q6, dtype=np.float32))
    idx = bundle.robot.get_link(TCP_LINK).idx_local
    w, x, y, z = np.asarray(links_quat.tolist())[idx]
    Rm = _Rot.from_quat([x, y, z, w]).as_matrix()
    tool = -Rm[:, 2]
    return float(np.degrees(np.arccos(np.clip(-tool[2], -1.0, 1.0))))


def _solve(bundle: SceneBundleSO101, tcp_pos, init_q6, dofs) -> np.ndarray:
    q, err = bundle.robot.inverse_kinematics(
        link=bundle.robot.get_link(TCP_LINK),
        pos=np.asarray(tcp_pos, dtype=np.float64),
        local_point=TCP_LOCAL,
        init_qpos=np.asarray(init_q6, dtype=np.float64),
        dofs_idx_local=np.asarray(dofs),
        return_error=True,
    )
    err = np.asarray(err.tolist()).ravel()
    pos_err = float(np.linalg.norm(err[:3]))
    if pos_err > 0.01:
        print(f"[WARN] IK position error {pos_err*1000:.1f} mm for target {tcp_pos}")
    return np.asarray(q.tolist(), dtype=np.float64)


def _ik(bundle: SceneBundleSO101, tcp_pos,
        max_tilt_deg: float = MAX_TOOL_TILT_DEG) -> np.ndarray:
    """Solve arm qpos so the fingertip TCP reaches tcp_pos, with bounded tool tilt.

    Full orientation constraints force the 5-DOF arm into a horizontal "crane"
    posture, so instead: solve position-only first (natural elbow-up posture),
    then, if the tool tilts too far forward, steepen the wrist and re-solve the
    position over pan/lift/elbow with the wrist locked, iterating to convergence.
    """
    home6 = np.append(SO101_HOME_QPOS[:5], GRIPPER_OPEN)
    q = _solve(bundle, tcp_pos, home6, np.arange(5))
    tilt = _tool_tilt_deg(bundle, q)
    sign = 1.0
    for _ in range(5):
        if tilt <= max_tilt_deg + 1.0:
            break
        q_try = q.copy()
        q_try[3] += sign * np.radians(tilt - max_tilt_deg)
        q2 = _solve(bundle, tcp_pos, q_try, np.array([0, 1, 2]))
        t2 = _tool_tilt_deg(bundle, q2)
        if t2 > tilt - 0.5:      # wrong wrist direction → flip and retry
            sign = -sign
            continue
        q, tilt = q2, t2
    return q


# --- Motion primitives -----------------------------------------------------------

def _step(bundle: SceneBundleSO101, on_step=None) -> None:
    bundle.scene.step()
    bundle.update_wrist_cam()
    if on_step is not None:
        on_step()


def _move_arm(bundle: SceneBundleSO101, q_goal: np.ndarray, gripper: float,
              on_step=None, settle: int = SETTLE_STEPS) -> None:
    """Interpolate the arm to q_goal with per-step joint-delta capping."""
    robot = bundle.robot
    q_now = np.asarray(robot.get_qpos().tolist(), dtype=np.float64)[ARM_DOFS]
    q_goal = np.asarray(q_goal, dtype=np.float64)[ARM_DOFS]
    dq = np.abs(q_goal - q_now)
    n = max(int(np.ceil(dq.max() / MOVE_MAX_DQ)), MOVE_MIN_STEPS)
    for i in range(1, n + 1):
        q_i = q_now + (q_goal - q_now) * (i / n)
        robot.control_dofs_position(np.append(q_i, gripper))
        _step(bundle, on_step)
    for _ in range(settle):
        robot.control_dofs_position(np.append(q_goal, gripper))
        _step(bundle, on_step)


def _move_line(bundle: SceneBundleSO101, tcp_from, tcp_to, gripper: float,
               on_step=None, segments: int = 6) -> None:
    """Move the TCP along a straight Cartesian line via intermediate IK waypoints.

    Joint-space interpolation bows the fingertip path inward (toward the base) —
    enough to knock the cube away during descent — so vertical approach/retreat
    moves are subdivided in Cartesian space instead.
    """
    a = np.asarray(tcp_from, dtype=np.float64)
    c = np.asarray(tcp_to, dtype=np.float64)
    for i in range(1, segments + 1):
        q = _ik(bundle, a + (c - a) * (i / segments))
        settle = SETTLE_STEPS if i == segments else 5
        _move_arm(bundle, q, gripper, on_step, settle=settle)


def _move_arc(bundle: SceneBundleSO101, tcp_from, tcp_to, gripper: float,
              on_step=None, segments: int = 8) -> None:
    """Constant-height transport along a base-centered arc (polar interpolation).

    A straight xy chord between two reachable points can pass within ~0.15 m of
    the arm base — inside the annulus where the 5-DOF IK has no near-vertical
    solution — so mid-transport waypoints droop and can shake the cube loose.
    Interpolating radius and bearing separately keeps every waypoint at a
    reachable distance from the base.
    """
    a = np.asarray(tcp_from, dtype=np.float64)
    c = np.asarray(tcp_to, dtype=np.float64)
    va, vc = a[:2] - BASE_XY, c[:2] - BASE_XY
    ra, rc = np.linalg.norm(va), np.linalg.norm(vc)
    th_a = np.arctan2(va[0], va[1])
    th_c = np.arctan2(vc[0], vc[1])
    dth = (th_c - th_a + np.pi) % (2 * np.pi) - np.pi   # shortest way around
    for i in range(1, segments + 1):
        t = i / segments
        r = ra + (rc - ra) * t
        th = th_a + dth * t
        xy = BASE_XY + r * np.array([np.sin(th), np.cos(th)])
        z = a[2] + (c[2] - a[2]) * t
        q = _ik(bundle, (xy[0], xy[1], z))
        settle = SETTLE_STEPS if i == segments else 5
        _move_arm(bundle, q, gripper, on_step, settle=settle)


def _set_gripper(bundle: SceneBundleSO101, target: float, on_step=None) -> None:
    """Ramp the jaw to `target`, holding the current arm setpoint."""
    robot = bundle.robot
    q_arm = np.asarray(robot.get_qpos().tolist(), dtype=np.float64)[ARM_DOFS]
    j0 = float(robot.get_qpos().tolist()[GRIPPER_DOF])
    for k in range(GRIP_STEPS):
        j_t = j0 + (target - j0) * (k + 1) / GRIP_STEPS
        robot.control_dofs_position(np.append(q_arm, j_t))
        _step(bundle, on_step)
    for _ in range(40):   # settle: let the PD squeeze (or release) stabilize
        robot.control_dofs_position(np.append(q_arm, target))
        _step(bundle, on_step)


# --- Task execution --------------------------------------------------------------

def run_pick_place(bundle: SceneBundleSO101, task: TaskSpec | None = None,
                   on_step=None) -> tuple[bool, dict]:
    """Execute one scripted pick-and-place. Returns (success, info)."""
    task = task or TaskSpec()
    robot, cube = bundle.robot, bundle.cube

    robot.set_dofs_kp(SO101_KP)
    robot.set_dofs_kv(SO101_KV)
    robot.set_dofs_force_range(-SO101_FORCE, SO101_FORCE)

    def _standoff(xy) -> np.ndarray:
        """Fingertip target: GRASP_STANDOFF short of xy along the base→xy bearing
        (the fixed finger sits on the near side; the closing jaw rakes the object in)."""
        d = np.asarray(xy, dtype=np.float64) - BASE_XY
        return np.asarray(xy) - GRASP_STANDOFF * d / np.linalg.norm(d)

    # 1. Home, jaw relaxed half-open
    _move_arm(bundle, SO101_HOME_QPOS, GRIPPER_IDLE, on_step)

    tip_z = WORKSPACE_Z + FINGER_TABLE_Z
    held = False
    attempts = 0
    for attempts in range(1, GRASP_ATTEMPTS + 1):
        # Read the cube pose only after the scene has physically settled (the cube
        # can slide a few mm during the first steps — or centimeters after a failed
        # grasp attempt), so the grasp targets track where the cube actually is.
        cube_pos = np.asarray(cube.get_pos().tolist(), dtype=np.float64)
        cube_top = cube_pos[2] + CUBE_SIZE[2] / 2
        gx, gy = _standoff(cube_pos[:2])
        hover = cube_top + HOVER_ABOVE

        # 2. Pregrasp hover above the far side of the cube, jaw swinging wide open
        q = _ik(bundle, (gx, gy, hover))
        _move_arm(bundle, q, GRIPPER_OPEN, on_step)

        # 3. Descend straight down: fixed fingertip lands just short of the cube at table height
        _move_line(bundle, (gx, gy, hover), (gx, gy, tip_z), GRIPPER_OPEN, on_step)

        # 4. Close: the jaw rakes the cube back against the fixed finger and squeezes
        _set_gripper(bundle, GRIPPER_CLOSE, on_step)

        # 5. Lift straight up, then verify the cube actually came along
        _move_line(bundle, (gx, gy, tip_z), (gx, gy, hover), GRIPPER_CLOSE, on_step)
        held = float(np.asarray(cube.get_pos().tolist())[2]) > HELD_MIN_Z
        if held:
            break
        # Missed: release whatever the jaw pinched and re-approach from wherever
        # the failed rake pushed the cube.
        _set_gripper(bundle, GRIPPER_OPEN, on_step)

    if not held:
        _move_arm(bundle, SO101_HOME_QPOS, GRIPPER_IDLE, on_step)
        final = np.asarray(cube.get_pos().tolist(), dtype=np.float64)
        err_xy = np.abs(final[:2] - np.asarray(task.place_xy))
        return False, {"cube_final": final.tolist(), "err_xy": err_xy.tolist(),
                       "on_sheet": False, "on_table": True, "attempts": attempts}

    # 6. Transport: constant-height arc around the base to the place target.
    # Fingertip aims just past the sheet center so the held cube lands centered.
    px, py = task.place_xy
    dp = np.array([px, py]) - BASE_XY
    dp /= np.linalg.norm(dp)
    tx, ty = np.array([px, py]) + PLACE_HELD_OFFSET * dp
    _move_arc(bundle, (gx, gy, hover), (tx, ty, hover), GRIPPER_CLOSE, on_step)

    # 6.5 Fine-correct: the cube's held offset from the fingertip depends on how the
    # rake pinched it, so read where the cube actually is and shift horizontally
    # until it sits over the place center (self-calibrating placement).
    cube_now = np.asarray(cube.get_pos().tolist(), dtype=np.float64)
    if cube_now[2] > WORKSPACE_Z + 0.03:      # only if the cube is actually held
        corr = np.array([px, py]) - cube_now[:2]
        if 0.001 < np.linalg.norm(corr) < 0.10:
            tx, ty = tx + corr[0], ty + corr[1]
            _move_line(bundle, (tx - corr[0], ty - corr[1], hover), (tx, ty, hover),
                       GRIPPER_CLOSE, on_step, segments=2)

    # 7. Set down: lower until the held cube rests on the sheet, THEN release.
    # The drop distance is measured from the cube's actual held height, so the cube
    # touches down instead of falling and rolling. Small clearance avoids pressing.
    sheet_top = WORKSPACE_Z + 2 * TARGET_SIZE[2]
    cube_z_held = float(np.asarray(cube.get_pos().tolist())[2])
    drop = (cube_z_held - CUBE_SIZE[2] / 2) - (sheet_top + 0.001)
    set_down_z = max(hover - drop, tip_z) if drop > 0 else hover
    _move_line(bundle, (tx, ty, hover), (tx, ty, set_down_z), GRIPPER_CLOSE, on_step)
    _set_gripper(bundle, GRIPPER_RELEASE, on_step)

    # 8. Retreat with the jaw only partially open, then home fully relaxed
    _move_line(bundle, (tx, ty, set_down_z), (tx, ty, hover), GRIPPER_RELEASE, on_step)
    _move_arm(bundle, SO101_HOME_QPOS, GRIPPER_IDLE, on_step)

    # Success: cube center on the sheet, resting near table height
    final = np.asarray(cube.get_pos().tolist(), dtype=np.float64)
    err_xy = np.abs(final[:2] - np.array([px, py]))
    ok = check_success(bundle, task)
    info = {"cube_final": final.tolist(), "err_xy": err_xy.tolist(),
            "on_sheet": bool((err_xy <= PLACE_TOL_XY).all()),
            "on_table": bool(final[2] <= WORKSPACE_Z + PLACE_TOL_Z),
            "attempts": attempts}
    return ok, info


# --- CLI ---------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="SO101 scripted pick-and-place demo.")
    parser.add_argument("-v", "--vis",       action="store_true")
    parser.add_argument("--save-video",      action="store_true",
                        help="save world+wrist cam video to so101_grasp_{world,wrist}.mp4")
    parser.add_argument("--place", type=str, default=None,
                        help="place target 'x,y' (default: white sheet center)")
    args = parser.parse_args()

    gs.init(backend=default_backend())
    bundle = build_scene_so101(show_viewer=args.vis)

    task = TaskSpec()
    if args.place:
        x, y = (float(v) for v in args.place.split(","))
        task.place_xy = (x, y)

    frames_world: list[np.ndarray] = []
    frames_wrist: list[np.ndarray] = []
    counter = {"i": 0}

    def on_step() -> None:
        counter["i"] += 1
        if args.save_video and counter["i"] % 4 == 0:   # 25 fps at dt=0.01
            out = bundle.render()
            for key, buf in (("world", frames_world), ("wrist", frames_wrist)):
                img = out[key][0] if isinstance(out[key], tuple) else out[key]
                buf.append(img)

    success, info = run_pick_place(bundle, task, on_step=on_step)
    print(f"success={success}  info={info}")

    if args.save_video and frames_world:
        import imageio.v2 as imageio
        for name, buf in (("world", frames_world), ("wrist", frames_wrist)):
            path = f"so101_grasp_{name}.mp4"
            imageio.mimwrite(path, buf, fps=25, codec="libx264", quality=8)
            print(f"Saved {path} ({len(buf)} frames)")


if __name__ == "__main__":
    main()
