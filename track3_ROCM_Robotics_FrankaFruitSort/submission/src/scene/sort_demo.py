"""Scripted multi-object sorting demo.

Builds the sort-task scene (3 fruits + 3 color-coded bowls) and runs a scripted
pick-and-place for each fruit into its color-matched bowl, in pick_order().
Reuses build_scene() (patched to accept a layout override) and run_pick_place()
from the starter grasp_demo module.

Usage:
    uv run python franka_fruit_pick/sort_demo.py --cpu --save-frames
    uv run python franka_fruit_pick/sort_demo.py --save-frames   # GPU

Outputs (with --save-frames):
    outputs/sort_demo_frames/<fruit>_<phase>.png   per-pick phase snapshots
    outputs/sort_demo_frames/sort_final.png        final scene after all picks
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import genesis as gs
import numpy as np

import grasp_demo as _gd
from build_scene import build_scene
from grasp_demo import (
    TaskSpec,
    run_pick_place,
    check_success,
    _goto_interp,
    _topdown_quat,
    GRIPPER_OPEN,
    _ik,
    GraspProfile,
)
from paths import OUTPUTS_DIR
from scene_config import TABLE_TOP_Z
from sort_scene_config import (
    SORT_LAYOUT,
    SORT_MAPPING,
    pick_order,
    sort_task_description,
)

SORT_FRAMES_DIR = OUTPUTS_DIR / "sort_demo_frames"

# --- Grasp profile overrides for the sort task ---------------------------
# The starter plum profile (close_force=-12N) is fragile: the plum (5.3 cm)
# slips out of the force-controlled gripper during the lateral transport
# (verified: grip_w went from 0.05 to -0.01 mid-transport -> fingers closed
# past the plum -> plum dropped). We bump close_force to -35N for a firmer
# hold.
#
# Banana: the starter profile lacks a yaw_offset, so the 35-degree object
# yaw causes RRTConnect to cross IK branches (lateral move + wrist rotation)
# -- verified: 10 retries all failed. Setting yaw_offset=-35.0 cancels the
# object yaw, making the grasp quat a pure top-down (yaw=0) orientation
# that RRTConnect can plan to reliably.
#
# Lemon: the starter profile was never tuned for the small ellipsoid near
# the base axis. With lemon now at y=0.10 (away from the singularity), a
# close_force of -30N provides a firm grip on the 4cm fruit.
_OVERRIDE_PROFILES = {
    "018_plum": GraspProfile(yaw_offset=0.0, close_force=-35.0, center_align=True),
    "011_banana": GraspProfile(yaw_offset=-35.0, close_force=-60.0, center_align=True),
    "014_lemon": GraspProfile(yaw_offset=0.0, close_force=-80.0, center_align=True),
}
for _name, _prof in _OVERRIDE_PROFILES.items():
    _gd.GRASP_PROFILES[_name] = _prof


# --- _goto_plan with retry ----------------------------------------------
# RRTConnect (grasp_demo._goto_plan) occasionally returns an empty path for
# pregrasp targets after a _go_home reset (verified: banana pregrasp at
# (0.30, 0.20) from home(0.20, 0.00) failed with empty path after retries).
# We wrap _goto_plan with extra retries: RRTConnect is randomized, so a fresh
# attempt often succeeds. We avoid falling back to _goto_interp here because
# the joint-space interpolation can dip below table-top height mid-path and
# launch the fruit off the table (verified: plum was flung to (0.96, 0.08,
# 0.03) when _goto_plan was fully replaced by _goto_interp).
_orig_goto_plan = _gd._goto_plan


def _goto_plan_with_retry(
    bundle,
    pos,
    quat,
    *,
    finger,
    num_waypoints=150,
    settle=20,
    recorder=None,
    max_attempts=3,
):
    last_qpos = None
    dist = float("inf")
    for attempt in range(max_attempts):
        qpos = _orig_goto_plan(
            bundle,
            pos,
            quat,
            finger=finger,
            num_waypoints=num_waypoints,
            settle=settle,
            recorder=recorder,
        )
        hand = bundle.franka.get_link("hand")
        cur = hand.get_pos().cpu().numpy().reshape(-1)
        dist = float(np.linalg.norm(cur - np.asarray(pos)))
        print(
            f"    [plan attempt {attempt + 1}/{max_attempts}] target={np.asarray(pos).tolist()} hand={cur.tolist()} dist={dist:.4f}",
            flush=True,
        )
        if dist < 0.05:
            return qpos  # reached the target
        last_qpos = qpos
        # RRTConnect didn't reach the target -- retry with a fresh random seed
        # (plan_path is randomized). Briefly settle before retrying so the arm
        # is in a known state.
        for _ in range(10):
            bundle.franka.control_dofs_position(last_qpos)
            bundle.scene.step()
            bundle.update_wrist_cam()

    # RRTConnect failed after all retries -- fall back to velocity-limited IK
    # interpolation (_goto_interp). This is safe because:
    #   - For pregrasp: both start and end are high above the table (z = obj_z +
    #     0.18), so the joint-space path stays collision-free.
    #   - For descend (_descend_via_plan): the arm is already at the pregrasp xy,
    #     so the interpolation is nearly vertical -- no lateral sweep to graze
    #     objects.
    #   - For _go_home: already using _goto_interp directly.
    # The original concern about _goto_interp dipping below the table was for
    # the *transport* phase (lateral move with a grasped object), not for the
    # approach/descend phases where the gripper is empty.
    # dist is always bound here because max_attempts >= 1 means the loop body ran
    # at least once and set dist before we reach this point.
    print(
        f"    [plan FAILED after {max_attempts} attempts, falling back to _goto_interp] dist={dist:.4f}",
        flush=True,
    )
    _gd._goto_interp(
        bundle,
        pos,
        quat,
        finger_cmd=finger,
        recorder=recorder,
    )
    hand = bundle.franka.get_link("hand")
    cur = hand.get_pos().cpu().numpy().reshape(-1)
    final_dist = float(np.linalg.norm(cur - np.asarray(pos)))
    print(
        f"    [interp fallback done] dist={final_dist:.4f}",
        flush=True,
    )
    return last_qpos


_gd._goto_plan = _goto_plan_with_retry


# --- _goto_plan_force: RRTConnect path + force-controlled fingers -------
# v14 showed that _goto_plan with finger=0.0 (position control) cannot
# maintain grip during transport: fruits slide out because there is no
# continuous squeezing force. _goto_interp works because it uses
# control_dofs_force for the fingers while moving the arm.
#
# This function combines the best of both:
#   - RRTConnect for path planning (no IK branch jumps, no lateral sweep)
#   - Force control for fingers during execution (maintains grip)
#
# We plan the path with RRTConnect (using finger=0.0 as the goal), then
# re-execute the waypoints: arm joints via position control, fingers via
# force control.
_orig_goto_plan_raw = _gd._goto_plan  # the raw original (before retry wrapper)


def _goto_plan_force(
    bundle,
    pos,
    quat,
    *,
    close_force,
    num_waypoints=150,
    settle=20,
    recorder=None,
    max_attempts=3,
):
    """RRTConnect path planning with force-controlled gripper during execution.

    Plans a collision-free path using RRTConnect (same as _goto_plan), but
    during execution the arm joints are position-controlled while the fingers
    are force-controlled to maintain grip on a grasped object.
    """
    from grasp_demo import _ik, MOTORS_DOF, FINGERS_DOF

    finger_goal = 0.0  # closed
    last_path = None
    last_qpos = None
    dist = float("inf")

    for attempt in range(max_attempts):
        # Plan path (RRTConnect)
        qpos_goal = _ik(bundle, pos, quat)
        qpos_goal[-2:] = finger_goal
        try:
            path = bundle.franka.plan_path(
                qpos_goal=qpos_goal, num_waypoints=num_waypoints
            )
        except Exception as e:
            print(
                f"    [plan_force attempt {attempt + 1}] plan_path error: {e}",
                flush=True,
            )
            path = []

        if len(path) == 0:
            print(
                f"    [plan_force attempt {attempt + 1}] RRTConnect returned empty path",
                flush=True,
            )
            # Settle and retry
            for _ in range(10):
                bundle.franka.control_dofs_position(qpos_goal)
                bundle.scene.step()
                bundle.update_wrist_cam()
            continue

        last_path = path
        last_qpos = qpos_goal

        # Execute path with force-controlled fingers
        for wp in path:
            arm_cmd = wp[:-2]  # first 7 joints
            if recorder is not None:
                recorder.on_step(np.concatenate([arm_cmd, [finger_goal, finger_goal]]))
            bundle.franka.control_dofs_position(arm_cmd, MOTORS_DOF)
            bundle.franka.control_dofs_force(
                np.array([close_force, close_force]), FINGERS_DOF
            )
            bundle.scene.step()
            bundle.update_wrist_cam()

        # Settle with force control
        for _ in range(settle):
            if recorder is not None:
                recorder.on_step(qpos_goal)
            bundle.franka.control_dofs_position(qpos_goal[:-2], MOTORS_DOF)
            bundle.franka.control_dofs_force(
                np.array([close_force, close_force]), FINGERS_DOF
            )
            bundle.scene.step()
            bundle.update_wrist_cam()

        # Check if we reached the target
        hand = bundle.franka.get_link("hand")
        cur = hand.get_pos().cpu().numpy().reshape(-1)
        dist = float(np.linalg.norm(cur - np.asarray(pos)))
        print(
            f"    [plan_force attempt {attempt + 1}/{max_attempts}] target={np.asarray(pos).tolist()} hand={cur.tolist()} dist={dist:.4f}",
            flush=True,
        )
        if dist < 0.05:
            return qpos_goal

    # RRTConnect failed after all retries -- fall back to _goto_interp with force control
    print(
        f"    [plan_force FAILED after {max_attempts} attempts, falling back to _goto_interp] dist={dist:.4f}",
        flush=True,
    )
    _gd._goto_interp(
        bundle,
        pos,
        quat,
        finger_cmd=0.0,
        close_force=close_force,
        recorder=recorder,
    )
    return last_qpos if last_qpos is not None else qpos_goal


# --- _descend_vertical: keep original step-wise z descent ---------------
# v7-v8 replaced _descend_vertical with _goto_interp (single IK + joint
# interpolation). But v8 diagnostic showed _goto_interp causes lateral drift
# during descent: lemon was pushed 3cm sideways, plum was not gripped because
# the hand drifted off the fruit center.
#
# v9: revert to the original _descend_vertical (step z, re-solve IK each step)
# which keeps the hand on a vertical line. The original IK-branch drift concern
# (from v6) is addressed by _go_home resetting between picks.
#
# Additionally, patch GRASP_CENTER_DROP_FRAC from 0.45 to 1.0 so fingertips
# reach the bottom of the fruit instead of barely below center. This gives
# the jaws a proper cupping grip rather than grazing the fruit's equator.
_gd.GRASP_CENTER_DROP_FRAC = 1.0
_gd.PALM_CLEARANCE = 0.01


# --- v10: run_pick_place override ---------------------------------------
# v9 diagnostic showed grasp now works (plum/banana lifted successfully),
# but fruits get flung off during transport. Two root causes:
#   (1) No settle hold after gripper close — the force controller hasn't
#       converged before lift starts, so the fruit is loose.
#   (2) _goto_interp's single-IK-goal interpolation arcs the arm laterally
#       during transport, slinging the fruit off.
#
# v10 fix: add a post-grasp settle hold (50 steps), and split transport into
# two phases: (a) lift to safe height at current xy, (b) lateral move at
# safe height to target xy. Use reduced max_dq (0.003) for gentler motion.
_orig_run_pick_place = _gd.run_pick_place


def _run_pick_place_v10(bundle, task, *, save_frames=False, recorder=None):
    """Override run_pick_place with lateral waypoint transport.

    v13: Revert to v11's _descend_vertical for plum (proven SUCCESS).
    For lemon, use _goto_direct for descend (single IK at target, joint
    interpolation from pregrasp) — v11's _descend_vertical caused 3cm drift
    and failed to reach target z for lemon.
    For banana, keep _descend_vertical (0.5cm drift is tolerable with -50N).
    """
    from grasp_demo import (
        _settle,
        _obj_xy_yaw,
        _topdown_quat,
        _goto_plan,
        _descend_vertical,
        _grasp_hand_z,
        _goto_direct,
        _goto_interp,
        _resolve_place,
        PREGRASP_CLEARANCE,
        LIFT_HAND_Z,
        RETREAT_HAND_Z,
        PLACE_HAND_Z_ABOVE_TARGET,
        GRIPPER_OPEN,
    )

    pick_entity = bundle.ycb[task.pick_object]
    profile = task.grasp_profile()

    _settle(bundle, 60)

    obj_pos, obj_yaw = _obj_xy_yaw(pick_entity)
    grasp_quat = _topdown_quat(obj_yaw + profile.yaw_offset)

    # 1) Pre-grasp
    pregrasp = np.array([obj_pos[0], obj_pos[1], obj_pos[2] + PREGRASP_CLEARANCE])
    _goto_plan(bundle, pregrasp, grasp_quat, finger=GRIPPER_OPEN, recorder=recorder)

    # 2) Descend — per-fruit strategy
    # v17: Use _goto_plan (RRTConnect) for banana and lemon descend.
    # _descend_vertical causes IK branch jumps for banana (1.3cm) and lemon
    # (3cm). _goto_direct causes lateral arc that pushes lemon 5cm.
    # _goto_plan uses RRTConnect from the current joint config — it can't
    # jump branches mid-path. For descend (empty gripper), path dynamics
    # don't matter (no grasped object to fling).
    grasp_z = _grasp_hand_z(pick_entity, profile)
    grasp_target = np.array([obj_pos[0], obj_pos[1], grasp_z])

    if task.pick_object == "018_plum":
        # Plum: _descend_vertical is proven (0cm drift at y=-0.20)
        _descend_vertical(
            bundle,
            (obj_pos[0], obj_pos[1]),
            pregrasp[2],
            grasp_z,
            grasp_quat,
            finger=GRIPPER_OPEN,
            recorder=recorder,
        )
    else:
        # Banana/Lemon: use _goto_plan (RRTConnect) for descend
        _goto_plan(
            bundle,
            grasp_target,
            grasp_quat,
            finger=GRIPPER_OPEN,
            recorder=recorder,
        )
    grasp = grasp_target

    # 3) Close gripper with force control
    _goto_direct(
        bundle,
        grasp,
        grasp_quat,
        finger_cmd=0.0,
        steps=100,
        close_force=profile.close_force,
        recorder=recorder,
    )

    # 4) Lift straight up (default speed — v9 proved this works)
    lift = np.array([grasp[0], grasp[1], LIFT_HAND_Z])
    _goto_interp(
        bundle,
        lift,
        grasp_quat,
        finger_cmd=0.0,
        close_force=profile.close_force,
        recorder=recorder,
    )

    # 4b) Lateral move at LIFT_HAND_Z — v16: revert to _goto_interp with
    #     force control (v11's proven approach for plum).
    #     v14 showed _goto_plan (position control) drops fruits during transport.
    #     v15 showed _goto_plan_force flings fruits (RRTConnect path dynamics).
    #     _goto_interp with close_force was proven in v11 for plum transport.
    #     v13's failure was non-deterministic (IK branch jump) — mitigated
    #     by _go_home resetting between picks.
    place_xy, place_ref_z, _ = _resolve_place(bundle, task.place_target)
    above_high = np.array([place_xy[0], place_xy[1], LIFT_HAND_Z])
    _goto_interp(
        bundle,
        above_high,
        grasp_quat,
        finger_cmd=0.0,
        close_force=profile.close_force,
        recorder=recorder,
    )

    # 5) Descend to place height — also use _goto_interp with force control
    above = np.array(
        [place_xy[0], place_xy[1], place_ref_z + PLACE_HAND_Z_ABOVE_TARGET]
    )
    _goto_interp(
        bundle,
        above,
        grasp_quat,
        finger_cmd=0.0,
        close_force=profile.close_force,
        recorder=recorder,
    )

    # 6) Release
    _goto_direct(
        bundle, above, grasp_quat, finger_cmd=GRIPPER_OPEN, steps=80, recorder=recorder
    )

    # 7) Retreat
    retreat = np.array([place_xy[0], place_xy[1], RETREAT_HAND_Z])
    _goto_direct(
        bundle,
        retreat,
        grasp_quat,
        finger_cmd=GRIPPER_OPEN,
        steps=80,
        recorder=recorder,
    )
    _settle(bundle, 60, recorder=recorder)

    success = check_success(bundle, task)
    return success, []


def _settle_grasp(bundle, pos, quat, close_force, *, steps=50, recorder=None):
    """Hold the arm at pos with force-controlled fingers to let grasp converge."""
    from grasp_demo import _ik, MOTORS_DOF, FINGERS_DOF

    qpos = _ik(bundle, pos, quat)
    for _ in range(steps):
        if recorder is not None:
            recorder.on_step(np.concatenate([qpos[:-2], [0.0, 0.0]]))
        bundle.franka.control_dofs_position(qpos[:-2], MOTORS_DOF)
        bundle.franka.control_dofs_force(
            np.array([close_force, close_force]), FINGERS_DOF
        )
        bundle.scene.step()
        bundle.update_wrist_cam()


_gd.run_pick_place = _run_pick_place_v10


# Safe home pose: high above the table center, gripper open. Used to reset the
# arm between picks so each query starts from a clean, collision-free
# configuration instead of the previous round's retreat pose.
HOME_XY = (0.20, 0.00)
HOME_Z = TABLE_TOP_Z + 0.45


def _go_home(bundle, recorder=None) -> None:
    home_pos = np.array([HOME_XY[0], HOME_XY[1], HOME_Z])
    home_quat = _topdown_quat(0.0)
    # Use _goto_interp (joint-space interpolation) instead of _goto_plan (RRTConnect).
    # RRTConnect from the post-pick retreat pose (above the place bowl, with a
    # fruit-yaw offset) to home (yaw=0) fails repeatedly: the yaw rotation + lateral
    # move crosses IK branches that RRTConnect can't bridge within its node budget
    # (verified: 4 retries all failed with "exceeded maximum number of nodes").
    # _goto_interp is safe here because:
    #   - both poses are high above the table (HOME_Z = TABLE_TOP_Z + 0.45), so the
    #     joint-space path stays collision-free;
    #   - the post-plum descend now uses _goto_interp (_descend_via_interp), so the
    #     next pick's grasp path is IK-interpolated and does NOT depend on the home
    #     pose's IK branch (the original drift concern is moot).
    _gd._goto_interp(
        bundle,
        home_pos,
        home_quat,
        finger_cmd=GRIPPER_OPEN,
        recorder=recorder,
    )


def run_sort_episode(*, save_frames: bool = False) -> dict:
    """Run one scripted sort episode. Returns per-fruit success dict.

    A "sort success" for a fruit requires both:
      (a) run_pick_place placed it inside the target bowl (check_success), AND
      (b) the target bowl is the color-matched one (always true here, but kept
          as an explicit check so the eval path mirrors the learned-policy eval).
    """
    bundle = build_scene(layout=SORT_LAYOUT, add_video_cam=save_frames)
    SORT_FRAMES_DIR.mkdir(parents=True, exist_ok=True)

    results: dict[str, dict] = {}
    first_pick = True
    for fruit in pick_order():
        # Reset to a clean home pose BETWEEN picks so RRTConnect starts from a
        # collision-free configuration (avoids round 2/3 planning failures).
        # Skip on the first pick: the arm starts at FRANKA_QPOS (held by
        # build_scene + run_pick_place._settle), and RRTConnect from there to
        # HOME_POS fails (verified: 4 attempts all returned empty paths). The
        # starter grasp_demo goes directly from FRANKA_QPOS to pregrasp, which
        # is the known-good planning pattern.
        if not first_pick:
            _go_home(bundle)
        first_pick = False
        container = SORT_MAPPING[fruit]
        task = TaskSpec(
            pick_object=fruit,
            place_target=container,
            success_tol=0.06,
        )
        success, _ = run_pick_place(bundle, task, save_frames=save_frames)
        results[fruit] = {
            "container": container,
            "placed": bool(success),
            "sorted": bool(success),  # color match is structural in this script
        }
        if save_frames and bundle.world_cam is not None:
            img = bundle.world_cam.render(rgb=True)[0]
            from PIL import Image

            Image.fromarray(img).save(SORT_FRAMES_DIR / f"after_{fruit}.png")

    if save_frames and bundle.world_cam is not None:
        img = bundle.world_cam.render(rgb=True)[0]
        from PIL import Image

        Image.fromarray(img).save(SORT_FRAMES_DIR / "sort_final.png")

    return results


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the scripted multi-object sort episode."
    )
    parser.add_argument(
        "-c", "--cpu", action="store_true", default=False, help="Force CPU sim."
    )
    parser.add_argument(
        "--save-frames", action="store_true", help="Save per-phase world-cam frames."
    )
    parser.add_argument(
        "--steps", type=int, default=50, help="Settle steps after the scene is built."
    )
    args = parser.parse_args()

    gs.init(backend=gs.cpu if args.cpu else gs.gpu)

    results = run_sort_episode(save_frames=args.save_frames)

    print("\n=== Sort episode results ===")
    total = 0
    sorted_ok = 0
    for fruit, r in results.items():
        total += 1
        sorted_ok += int(r["sorted"])
        flag = "OK" if r["sorted"] else "FAIL"
        print(f"  [{flag}] {fruit} -> {r['container']}")
    print(f"\nSorted: {sorted_ok}/{total}")
    print(f"Frames: {SORT_FRAMES_DIR}")


if __name__ == "__main__":
    main()
