"""Scripted pick-and-place, parameterized via TaskSpec.

Reuses build_scene() from build_scene.py. The robot performs a scripted
pick-and-place state machine using IK + motion planning + force-controlled grasp.

A task is described by a `TaskSpec` (what to pick, where to place, success
tolerance). Per-object grasp behavior is described by a `GraspProfile`.

Examples:
    # pick the banana and place it into the bowl (default)
    uv run python grasp_demo.py --cpu --save-frames

    # pick the mug and place it onto a tabletop coordinate
    uv run python grasp_demo.py --cpu --pick 025_mug --place 0.5,0.2
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Union

import numpy as np

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import genesis as gs
from genesis.utils.geom import euler_to_quat, quat_to_xyz

from build_scene import build_scene
from paths import FRAMES_DIR
from scene_config import FRANKA_QPOS, TABLE_TOP_Z

# A place target is either an object name (place onto/into it) or a tabletop (x, y).
PlaceTarget = Union[str, tuple[float, float]]

# End-effector control constants shared across objects (world frame, meters).
# The hand-link origin sits ~0.095 m above the fingertips, so to place the
# fingertips near the tabletop (z=TABLE_TOP_Z) the hand link must be ~0.105 above it.
PREGRASP_CLEARANCE = 0.18  # hand-link height above object centroid before descending
LIFT_HAND_Z = TABLE_TOP_Z + 0.30  # absolute world z to lift the hand to after grasping
RETREAT_HAND_Z = TABLE_TOP_Z + 0.35  # absolute world z to retreat to after releasing
PLACE_HAND_Z_ABOVE_TARGET = 0.16  # hand-link height above the place reference z when releasing
# For container (bowl) placement success: how far below the rim the object's lowest
# point must drop to count as "inside", so a resting object clearly dips in rather than
# grazing the rim. Kept small since an elongated object (banana) only partly sinks.
_BOWL_RIM_MARGIN = 0.01

# Vertical offset from the hand-link origin (the IK target) down to the fingertip midline.
# Used by the geometry-adaptive grasp height to line the fingertips up with an object's center.
HAND_TO_FINGERTIP = 0.105
# Aim the fingertips this fraction of the object's half-height *below* its vertical center, so
# the jaws cup just under the equator of a round object (grasping exactly at the widest point is
# marginal -- a squeezed convex object slips out). Scales with object size.
GRASP_CENTER_DROP_FRAC = 0.45
# Minimum gap kept between the hand body / finger crossbar and the top of the object, so the
# crossbar does not graze (and roll away) a round object before the fingers close.
PALM_CLEARANCE = 0.02

GRIPPER_OPEN = 0.04

# Velocity limiting for GRASPED-object moves (lift + transport). The old approach commanded
# the far IK setpoint immediately, which a stiff PD + high torque limit turns into a max-accel
# dash -- the acceleration spike shakes/ejects the object from the gripper (verified with
# motion_probe.py: transport EE accel ~22 m/s^2 and large in-gripper slip). Interpolating the
# joint target one waypoint per control step caps the joint speed to MOVE_MAX_DQ / dt and
# removes the spike (transport accel ~10 m/s^2, plum slip -77%) at ~no extra sim-step cost.
MOVE_MAX_DQ = 0.006  # max per-control-step joint delta (rad); ~0.6 rad/s at 100 Hz
MOVE_MIN_STEPS = 40  # floor so short grasped moves still ramp smoothly
MOVE_SETTLE_STEPS = 15  # hold at the goal after arriving, to stabilize before the next phase

MOTORS_DOF = np.arange(7)
FINGERS_DOF = np.arange(7, 9)


@dataclass(frozen=True)
class GraspProfile:
    """Per-object top-down grasp parameters."""

    yaw_offset: float = 90.0  # deg added to the object yaw to orient the jaws
    grasp_hand_z: float = TABLE_TOP_Z + 0.105  # absolute hand-link z at grasp (used when center_align=False)
    close_force: float = -10.0  # N, finger force-control while holding the grasp
    # When True, the grasp height is computed at runtime from the object's actual AABB
    # (fingertips aligned to the object center + a crossbar-clearance floor above its top)
    # instead of the fixed grasp_hand_z. Meant for round/near-spherical objects, where a
    # too-deep fixed descent lets the crossbar graze the top and roll the object away.
    center_align: bool = False


# Defaults are tuned for the banana; other objects fall back to DEFAULT_PROFILE
# and can be tuned here as needed.
DEFAULT_PROFILE = GraspProfile()
GRASP_PROFILES: dict[str, GraspProfile] = {
    "011_banana": GraspProfile(yaw_offset=90.0, grasp_hand_z=TABLE_TOP_Z + 0.105, close_force=-10.0),
    # apple/orange: large smooth spheres (~7.5 cm, original scale) -- only marginally
    # graspable (excluded from the reliable pickable pool); profiles kept for completeness.
    # Round -> center_align so the fingertips meet the equator and the crossbar clears the top.
    "013_apple": GraspProfile(yaw_offset=0.0, close_force=-12.0, center_align=True),
    "017_orange": GraspProfile(yaw_offset=0.0, close_force=-12.0, center_align=True),
    # lemon: small oblate ellipsoid, grasped near its equator -- reliable (verified 6/6).
    "014_lemon": GraspProfile(yaw_offset=0.0, close_force=-12.0, center_align=True),
    # plum: small near-sphere, grasped near its equator -- reliable (verified 5/5).
    "018_plum": GraspProfile(yaw_offset=0.0, close_force=-12.0, center_align=True),
    # pear: profile kept for completeness, but its round cross-section slips on lift
    # (not reliably graspable -- excluded from the pickable pool). Jaws close across short axis.
    "016_pear": GraspProfile(yaw_offset=90.0, grasp_hand_z=TABLE_TOP_Z + 0.13, close_force=-12.0),
    "025_mug": GraspProfile(yaw_offset=0.0, grasp_hand_z=TABLE_TOP_Z + 0.085, close_force=-12.0),
    "006_mustard_bottle": GraspProfile(yaw_offset=0.0, grasp_hand_z=TABLE_TOP_Z + 0.11, close_force=-12.0),
}


@dataclass
class TaskSpec:
    """Describes a single pick-and-place task."""

    pick_object: str
    place_target: PlaceTarget
    success_tol: float = 0.06

    def grasp_profile(self) -> GraspProfile:
        return GRASP_PROFILES.get(self.pick_object, DEFAULT_PROFILE)


def _to_numpy(x) -> np.ndarray:
    """Convert a value to a 1-D numpy array, handling GPU torch tensors."""
    if hasattr(x, "detach"):
        x = x.detach().cpu().numpy()
    return np.asarray(x).reshape(-1)


def _topdown_quat(yaw_deg: float) -> np.ndarray:
    """Top-down grasp orientation with an extra yaw about world z."""
    return euler_to_quat(np.array([180.0, 0.0, yaw_deg]))


def _settle(bundle, steps: int, recorder=None) -> None:
    hold = np.array(FRANKA_QPOS)
    for _ in range(steps):
        if recorder is not None:
            recorder.on_step(hold)
        bundle.franka.control_dofs_position(hold)
        bundle.scene.step()
        bundle.update_wrist_cam()


def _obj_xy_yaw(entity) -> tuple[np.ndarray, float]:
    pos = entity.get_pos().cpu().numpy().reshape(-1)
    quat = entity.get_quat().cpu().numpy().reshape(-1)
    yaw = float(quat_to_xyz(quat, degrees=True)[2])
    return pos, yaw


def _entity_aabb(entity) -> np.ndarray:
    """Return the entity's world-frame AABB as a (2, 3) array: row 0 = min, row 1 = max."""
    aabb = entity.get_AABB()
    if hasattr(aabb, "detach"):
        aabb = aabb.detach().cpu().numpy()
    aabb = np.asarray(aabb)
    if aabb.ndim == 3:  # (n_envs, 2, 3) for batched builds -> take the first env
        aabb = aabb[0]
    return aabb


def _grasp_hand_z(entity, profile: GraspProfile) -> float:
    """Absolute hand-link z at which to close the gripper.

    For ``center_align`` profiles this is derived from the object's actual (post-settle) AABB
    rather than a fixed constant, combining two conditions:

    * jaw alignment -- put the fingertip midline just below the object's vertical center (its
      equator for a sphere) so the jaws cup under it: ``center_z - drop`` where ``drop`` is
      ``GRASP_CENTER_DROP_FRAC`` of the half-height. Hand z = that + ``HAND_TO_FINGERTIP``;
    * crossbar clearance (floor) -- keep the hand/crossbar above the object's top with a margin,
      so a large object can't be grazed before the jaws close: ``top_z + PALM_CLEARANCE``.

    The higher (safer) of the two is used. Non-``center_align`` profiles keep the tuned constant.
    """
    if not profile.center_align:
        return profile.grasp_hand_z
    aabb = _entity_aabb(entity)
    z_min, z_max = float(aabb[0, 2]), float(aabb[1, 2])
    center_z = 0.5 * (z_min + z_max)
    half_height = 0.5 * (z_max - z_min)
    fingertip_z = center_z - GRASP_CENTER_DROP_FRAC * half_height
    z_jaw_align = fingertip_z + HAND_TO_FINGERTIP
    z_top_clear = z_max + PALM_CLEARANCE
    return max(z_jaw_align, z_top_clear)


def _ik(bundle, pos: np.ndarray, quat: np.ndarray) -> np.ndarray:
    hand = bundle.franka.get_link("hand")
    return bundle.franka.inverse_kinematics(link=hand, pos=pos, quat=quat)


def _goto_plan(bundle, pos, quat, *, finger, num_waypoints=150, settle=20, recorder=None):
    """Plan a collision-free path to (pos, quat) and execute it."""
    qpos = _ik(bundle, pos, quat)
    qpos[-2:] = finger
    path = bundle.franka.plan_path(qpos_goal=qpos, num_waypoints=num_waypoints)
    for wp in path:
        if recorder is not None:
            recorder.on_step(wp)
        bundle.franka.control_dofs_position(wp)
        bundle.scene.step()
        bundle.update_wrist_cam()
    for _ in range(settle):
        if recorder is not None:
            recorder.on_step(qpos)
        bundle.franka.control_dofs_position(qpos)
        bundle.scene.step()
        bundle.update_wrist_cam()
    return qpos


def _goto_direct(bundle, pos, quat, *, finger_cmd, steps=120, close_force=None, recorder=None):
    """Move arm via direct position control (no planning), holding gripper command.

    If `close_force` is given, the fingers are force-controlled (grasping); otherwise
    they are position-controlled to `finger_cmd`.
    """
    qpos = _ik(bundle, pos, quat)
    # For a joint-position action space, record the intended finger target: closed (0.0)
    # while force-grasping, otherwise the commanded finger position.
    finger_target = 0.0 if close_force is not None else finger_cmd
    arm = _to_numpy(qpos[:-2])
    action = np.concatenate([arm, [finger_target, finger_target]])
    for _ in range(steps):
        if recorder is not None:
            recorder.on_step(action)
        bundle.franka.control_dofs_position(qpos[:-2], MOTORS_DOF)
        if close_force is not None:
            bundle.franka.control_dofs_force(np.array([close_force, close_force]), FINGERS_DOF)
        else:
            bundle.franka.control_dofs_position(np.array([finger_cmd, finger_cmd]), FINGERS_DOF)
        bundle.scene.step()
        bundle.update_wrist_cam()
    return qpos


def _goto_interp(
    bundle, pos, quat, *, finger_cmd, close_force=None,
    max_dq=MOVE_MAX_DQ, min_steps=MOVE_MIN_STEPS, settle=MOVE_SETTLE_STEPS, recorder=None,
):
    """Velocity-limited move: linearly interpolate the arm joint target from the current
    measured qpos to the IK goal, one waypoint per control step, then briefly hold.

    Unlike ``_goto_direct`` (which commands the far setpoint immediately -> a max-accel dash
    that shakes the grasped object loose), the per-step joint delta is capped to ``max_dq``
    (i.e. joint speed to ``max_dq / dt``), giving a smooth, low-acceleration trajectory. The
    number of waypoints scales with the move distance (floored at ``min_steps``), so short
    moves still ramp smoothly and long moves stay gentle. Used for the grasped-object phases
    (lift, transport). Fingers are force-controlled while ``close_force`` is given, else held
    at ``finger_cmd`` -- matching ``_goto_direct``.
    """
    q_goal = _ik(bundle, pos, quat)
    arm_goal = _to_numpy(q_goal[:-2])
    arm_start = _to_numpy(bundle.franka.get_dofs_position(MOTORS_DOF))
    dist = float(np.max(np.abs(arm_goal - arm_start))) if arm_goal.size else 0.0
    n = max(min_steps, int(np.ceil(dist / max_dq))) if dist > 1e-9 else min_steps
    finger_target = 0.0 if close_force is not None else finger_cmd

    def _cmd(arm):
        if recorder is not None:
            recorder.on_step(np.concatenate([arm, [finger_target, finger_target]]))
        bundle.franka.control_dofs_position(arm, MOTORS_DOF)
        if close_force is not None:
            bundle.franka.control_dofs_force(np.array([close_force, close_force]), FINGERS_DOF)
        else:
            bundle.franka.control_dofs_position(np.array([finger_cmd, finger_cmd]), FINGERS_DOF)
        bundle.scene.step()
        bundle.update_wrist_cam()

    for i in range(1, n + 1):
        _cmd(arm_start + (arm_goal - arm_start) * (i / n))
    for _ in range(settle):
        _cmd(arm_goal)
    return q_goal


def _descend_vertical(bundle, xy, z_from, z_to, quat, *, finger, steps=80, settle=15, recorder=None):
    """Descend straight down along a fixed xy by interpolating z and re-solving IK.

    A single IK snap can swing the hand laterally mid-descent; for tight clearances
    (e.g. a sphere nearly as wide as the gripper) that sideways sweep grazes and rolls
    the object away. Stepping z keeps the hand on a vertical line.
    """
    qpos = None
    for z in np.linspace(z_from, z_to, steps):
        qpos = _ik(bundle, np.array([xy[0], xy[1], z]), quat)
        qpos[-2:] = finger
        if recorder is not None:
            recorder.on_step(qpos)
        bundle.franka.control_dofs_position(qpos)
        bundle.scene.step()
        bundle.update_wrist_cam()
    for _ in range(settle):
        if recorder is not None:
            recorder.on_step(qpos)
        bundle.franka.control_dofs_position(qpos)
        bundle.scene.step()
        bundle.update_wrist_cam()
    return qpos


def _resolve_place(bundle, place_target: PlaceTarget) -> tuple[np.ndarray, float, object]:
    """Return (target_xy, reference_z, target_entity_or_None) for a place target."""
    if isinstance(place_target, str):
        ent = bundle.ycb[place_target]
        p = ent.get_pos().cpu().numpy().reshape(-1)
        return np.array([p[0], p[1]]), float(p[2]), ent
    x, y = place_target
    return np.array([float(x), float(y)]), TABLE_TOP_Z, None


def run_pick_place(bundle, task: TaskSpec, *, save_frames: bool = False, recorder=None):
    pick_entity = bundle.ycb[task.pick_object]
    profile = task.grasp_profile()

    frames = []

    def snap(tag):
        if save_frames and bundle.world_cam is not None:
            frames.append((tag, bundle.world_cam.render(rgb=True)[0]))

    # Let objects settle on the table. Not recorded: keeps episodes focused on motion.
    _settle(bundle, 60)
    snap("00_start")

    obj_pos, obj_yaw = _obj_xy_yaw(pick_entity)
    # Orient the jaws relative to the object (e.g. across a banana's short axis).
    grasp_quat = _topdown_quat(obj_yaw + profile.yaw_offset)

    # 1) Pre-grasp above the object, gripper open.
    pregrasp = np.array([obj_pos[0], obj_pos[1], obj_pos[2] + PREGRASP_CLEARANCE])
    _goto_plan(bundle, pregrasp, grasp_quat, finger=GRIPPER_OPEN, recorder=recorder)
    snap("01_pregrasp")

    # 2) Descend straight down to grasp height (vertical path avoids grazing the object).
    # For round objects grasp_z is derived from the object's actual AABB (center-aligned jaws +
    # crossbar clearance) so the descent isn't too deep; others use the tuned constant.
    grasp_z = _grasp_hand_z(pick_entity, profile)
    _descend_vertical(
        bundle, (obj_pos[0], obj_pos[1]), pregrasp[2], grasp_z, grasp_quat,
        finger=GRIPPER_OPEN, recorder=recorder,
    )
    grasp = np.array([obj_pos[0], obj_pos[1], grasp_z])
    snap("02_reach")

    # 3) Close the gripper with force control.
    _goto_direct(bundle, grasp, grasp_quat, finger_cmd=0.0, steps=100, close_force=profile.close_force, recorder=recorder)
    snap("03_grasp")

    # 4) Lift straight up from the grasp xy. Velocity-limited (see _goto_interp): a gentle
    # ramp instead of a max-accel dash keeps the object from shifting/ejecting in the jaws.
    lift = np.array([grasp[0], grasp[1], LIFT_HAND_Z])
    _goto_interp(bundle, lift, grasp_quat, finger_cmd=0.0, close_force=profile.close_force, recorder=recorder)
    snap("04_lift")

    # 5) Move above the place target. Velocity-limited: this is the largest (lateral) move and
    # the phase most prone to slinging a round/elongated object out of the gripper.
    place_xy, place_ref_z, _ = _resolve_place(bundle, task.place_target)
    above = np.array([place_xy[0], place_xy[1], place_ref_z + PLACE_HAND_Z_ABOVE_TARGET])
    _goto_interp(bundle, above, grasp_quat, finger_cmd=0.0, close_force=profile.close_force, recorder=recorder)
    snap("05_above_target")

    # 6) Release the object.
    _goto_direct(bundle, above, grasp_quat, finger_cmd=GRIPPER_OPEN, steps=80, recorder=recorder)
    snap("06_release")

    # 7) Retreat upward and let the object settle.
    retreat = np.array([place_xy[0], place_xy[1], RETREAT_HAND_Z])
    _goto_direct(bundle, retreat, grasp_quat, finger_cmd=GRIPPER_OPEN, steps=80, recorder=recorder)
    _settle(bundle, 60, recorder=recorder)
    snap("07_done")

    success = check_success(bundle, task)
    return success, frames


def check_success(bundle, task: TaskSpec) -> bool:
    """Whether ``pick_object`` has been placed at the target.

    For a *container* target (e.g. the bowl) success requires the object to actually
    be **inside** it -- horizontally within the rim footprint *and* with its lowest
    point dropped below the rim -- rather than merely hovering above the target xy
    (which the old "within tol and above table" test wrongly accepted, e.g. while
    still gripped over the bowl). We test the object's bottom (AABB) rather than its
    center because an elongated object such as the banana cannot fully sink below the
    rim: it rests partly in the bowl with its center/top still above the rim, yet its
    bottom clearly dips inside. For a bare tabletop coordinate target we keep the
    original test.

    Note: this is an instantaneous spatial test. Callers that poll it every frame
    (closed-loop eval) should additionally require it to hold for a short dwell so
    success is only declared once the object has come to rest (see eval_policy.py).
    """
    obj = bundle.ycb[task.pick_object]
    pick_pos = obj.get_pos().cpu().numpy().reshape(-1)
    place_xy, place_ref_z, place_ent = _resolve_place(bundle, task.place_target)
    horizontal = float(np.linalg.norm(pick_pos[:2] - place_xy))

    if place_ent is None:
        # Tabletop coordinate target: object near the xy and resting at/above the table.
        return bool(horizontal < task.success_tol and pick_pos[2] > place_ref_z - 0.02)

    # Container target: require containment inside the bowl's world-frame AABB.
    bowl_aabb = _entity_aabb(place_ent)  # (2, 3): row 0 = min, row 1 = max
    rim_z = float(bowl_aabb[1, 2])
    rim_radius = 0.5 * float(min(bowl_aabb[1, 0] - bowl_aabb[0, 0], bowl_aabb[1, 1] - bowl_aabb[0, 1]))
    within_footprint = horizontal < min(task.success_tol, rim_radius)
    obj_bottom_z = float(_entity_aabb(obj)[0, 2])
    # Lowest point of the object has dropped below the rim (by a small margin so it is
    # clearly inside, not just grazing the edge). This accepts a banana lying partly in
    # the bowl while rejecting an object still hovering/gripped above it.
    inside_bowl = obj_bottom_z < rim_z - _BOWL_RIM_MARGIN
    return bool(within_footprint and inside_bowl)


def _parse_place(text: str) -> PlaceTarget:
    """Parse a --place argument: either an object name or 'x,y' tabletop coords."""
    if "," in text:
        x_str, y_str = text.split(",")
        return (float(x_str), float(y_str))
    return text


def main() -> None:
    parser = argparse.ArgumentParser(description="Scripted pick-and-place (parameterized via TaskSpec).")
    parser.add_argument("-v", "--vis", action="store_true", default=False)
    parser.add_argument("-c", "--cpu", action="store_true", default=False)
    parser.add_argument("--pick", default="011_banana", help="Object name to pick.")
    parser.add_argument(
        "--place",
        default="024_bowl",
        help="Place target: an object name (e.g. 024_bowl) or tabletop coords 'x,y'.",
    )
    parser.add_argument("--tol", type=float, default=0.06, help="Success tolerance (m).")
    parser.add_argument("--save-frames", action="store_true", help="Save world-cam frames per stage.")
    args = parser.parse_args()

    task = TaskSpec(pick_object=args.pick, place_target=_parse_place(args.place), success_tol=args.tol)

    gs.init(backend=gs.cpu if args.cpu else gs.gpu)
    bundle = build_scene(show_viewer=args.vis, n_envs=1, add_world_cam=True, add_wrist_cam=True)

    success, frames = run_pick_place(bundle, task, save_frames=args.save_frames)
    print(f"[grasp_demo] task: pick={task.pick_object} place={task.place_target} -> success = {success}")

    if args.save_frames:
        import imageio.v2 as imageio

        out_dir = FRAMES_DIR
        out_dir.mkdir(parents=True, exist_ok=True)
        for tag, img in frames:
            imageio.imwrite(out_dir / f"{tag}.png", img)
        print(f"[grasp_demo] saved {len(frames)} frames to {out_dir}")


if __name__ == "__main__":
    main()
