"""Scripted color-sorting pick-and-place with YCB objects, parameterized via TaskSpec.

Based on franka_fruit_pick_demo's grasp_demo.py. Key changes:
- YCB mesh objects with real textures (surface=None in build_scene)
- GraspProfile per YCB object (ported from demo's GRASP_PROFILES)
- Motion primitives preserved verbatim from demo
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
from scene_config import (
    COLOR_RGB,
    CONTAINER_INNER_SIZE,
    CONTAINER_RIM_MARGIN,
    CONTAINER_RIM_Z_OFFSET,
    TABLE_TOP_Z,
    YCB_LAYOUT,
    get_ycb_assets,
)

# End-effector control constants (preserved from demo, world frame, meters).
PREGRASP_CLEARANCE = 0.18
LIFT_HAND_Z = TABLE_TOP_Z + 0.30
RETREAT_HAND_Z = TABLE_TOP_Z + 0.35
PLACE_HAND_Z_ABOVE_TARGET = 0.16

HAND_TO_FINGERTIP = 0.105
GRASP_CENTER_DROP_FRAC = 0.45
PALM_CLEARANCE = 0.02

GRIPPER_OPEN = 0.04

MOVE_MAX_DQ = 0.006
MOVE_MIN_STEPS = 40
MOVE_SETTLE_STEPS = 15

MOTORS_DOF = np.arange(7)
FINGERS_DOF = np.arange(7, 9)


@dataclass(frozen=True)
class GraspProfile:
    """Per-YCB-object top-down grasp parameters (ported from demo)."""
    yaw_offset: float = 0.0  # deg added to object yaw to orient jaws
    grasp_hand_z: float = TABLE_TOP_Z + 0.105  # fallback when center_align=False
    close_force: float = -12.0  # N, finger force-control while holding
    center_align: bool = False  # derive grasp height from AABB (True for round objects)


# Grasp profiles per YCB object (ported from demo's GRASP_PROFILES)
# Default: banana-like (flat, yaw_offset=90 to grasp across short axis)
DEFAULT_PROFILE = GraspProfile()
GRASP_PROFILES: dict[str, GraspProfile] = {
    "011_banana": GraspProfile(yaw_offset=90.0, grasp_hand_z=TABLE_TOP_Z + 0.105, close_force=-10.0),
    "018_plum": GraspProfile(yaw_offset=0.0, close_force=-12.0, center_align=True),
    "012_strawberry": GraspProfile(yaw_offset=0.0, close_force=-12.0, center_align=True),
    "014_lemon": GraspProfile(yaw_offset=0.0, close_force=-12.0, center_align=True),
}


@dataclass
class TaskSpec:
    """Describes a single color-sorting pick-and-place task.

    pick_object: YCB object name (e.g. "013_apple", "011_banana")
    place_target: color name (auto-resolves to that color's container)
    """

    pick_object: str
    place_target: Union[str, tuple[float, float]]
    success_tol: float = 0.06

    def grasp_profile(self) -> GraspProfile:
        return GRASP_PROFILES.get(self.pick_object, DEFAULT_PROFILE)

    @property
    def pick_color(self) -> str:
        """Extract color from YCB_LAYOUT."""
        return YCB_LAYOUT[self.pick_object]["color"]


def _to_numpy(x) -> np.ndarray:
    if hasattr(x, "detach"):
        x = x.detach().cpu().numpy()
    return np.asarray(x).reshape(-1)


def _topdown_quat(yaw_deg: float) -> np.ndarray:
    return euler_to_quat(np.array([180.0, 0.0, yaw_deg]))


def _settle(bundle, steps: int, recorder=None) -> None:
    hold = np.array([0.0, -0.3, 0.0, -2.0, 0.0, 1.7, 0.79, 0.04, 0.04])
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
    aabb = entity.get_AABB()
    if hasattr(aabb, "detach"):
        aabb = aabb.detach().cpu().numpy()
    aabb = np.asarray(aabb)
    if aabb.ndim == 3:
        aabb = aabb[0]
    return aabb


def _grasp_hand_z(entity, profile: GraspProfile) -> float:
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
    qpos = _ik(bundle, pos, quat)
    finger_target = -0.04 if close_force is not None else finger_cmd
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
    q_goal = _ik(bundle, pos, quat)
    arm_goal = _to_numpy(q_goal[:-2])
    arm_start = _to_numpy(bundle.franka.get_dofs_position(MOTORS_DOF))
    dist = float(np.max(np.abs(arm_goal - arm_start))) if arm_goal.size else 0.0
    n = max(min_steps, int(np.ceil(dist / max_dq))) if dist > 1e-9 else min_steps
    finger_target = -0.04 if close_force is not None else finger_cmd

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


def _resolve_place(bundle, place_target: Union[str, tuple[float, float]]) -> tuple[np.ndarray, float, object]:
    if isinstance(place_target, str):
        ent = bundle.containers.get(place_target)
        if ent is None:
            raise ValueError(f"No container for color {place_target!r}")
        p = ent.get_pos().cpu().numpy().reshape(-1)
        return np.array([p[0], p[1]]), float(p[2]), ent
    x, y = place_target
    return np.array([float(x), float(y)]), TABLE_TOP_Z, None


def run_pick_place(bundle, task: TaskSpec, *, save_frames: bool = False, recorder=None):
    pick_entity = bundle.objects[task.pick_object]
    profile = task.grasp_profile()

    frames = []

    def snap(tag):
        if save_frames and bundle.world_cam is not None:
            frames.append((tag, bundle.world_cam.render(rgb=True)[0]))

    _settle(bundle, 60)
    snap("00_start")

    obj_pos, obj_yaw = _obj_xy_yaw(pick_entity)
    grasp_quat = _topdown_quat(obj_yaw + profile.yaw_offset)

    # 1) Pre-grasp above the object, gripper open.
    pregrasp = np.array([obj_pos[0], obj_pos[1], obj_pos[2] + PREGRASP_CLEARANCE])
    _goto_plan(bundle, pregrasp, grasp_quat, finger=GRIPPER_OPEN, recorder=recorder)
    snap("01_pregrasp")

    # 2) Descend straight down to grasp height.
    grasp_z = _grasp_hand_z(pick_entity, profile)
    _descend_vertical(
        bundle, (obj_pos[0], obj_pos[1]), pregrasp[2], grasp_z, grasp_quat,
        finger=GRIPPER_OPEN, recorder=recorder,
    )
    grasp = np.array([obj_pos[0], obj_pos[1], grasp_z])
    snap("02_reach")

    # 3) Close the gripper with force control.
    close_force = profile.close_force
    _goto_direct(bundle, grasp, grasp_quat, finger_cmd=0.0, steps=100, close_force=close_force, recorder=recorder)
    snap("03_grasp")

    # 4) Lift straight up (velocity-limited).
    lift = np.array([grasp[0], grasp[1], LIFT_HAND_Z])
    _goto_interp(bundle, lift, grasp_quat, finger_cmd=0.0, close_force=close_force, recorder=recorder)
    snap("04_lift")

    # 5) Move above the place target (velocity-limited).
    place_xy, place_ref_z, _ = _resolve_place(bundle, task.place_target)
    above = np.array([place_xy[0], place_xy[1], place_ref_z + PLACE_HAND_Z_ABOVE_TARGET])
    _goto_interp(bundle, above, grasp_quat, finger_cmd=0.0, close_force=close_force, recorder=recorder)
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
    """Whether the YCB object has been placed into its color's container.

    Two-layer test:
    1. Horizontal: object center is within the bin's inner footprint.
    2. Vertical: object center is above the bin bottom (not clipping through)
       AND below the rim (actually placed inside).
    """
    obj = bundle.objects[task.pick_object]
    pick_pos = obj.get_pos().cpu().numpy().reshape(-1)
    place_xy, place_ref_z, place_ent = _resolve_place(bundle, task.place_target)

    if place_ent is None:
        horizontal = float(np.linalg.norm(pick_pos[:2] - place_xy))
        return bool(horizontal < task.success_tol and pick_pos[2] > place_ref_z - 0.02)

    # Layer 1: horizontal — object center within bin inner footprint
    bin_xy = place_ent.get_pos().cpu().numpy().reshape(-1)[:2]
    half_inner = CONTAINER_INNER_SIZE / 2
    inside_x = abs(pick_pos[0] - bin_xy[0]) < half_inner
    inside_y = abs(pick_pos[1] - bin_xy[1]) < half_inner
    if not (inside_x and inside_y):
        return False

    # Layer 2: vertical — the object's lowest point (AABB bottom) has dropped below the
    # rim (by a small margin), so it is clearly inside the bin, not hovering/gripped above.
    # Using the object's bottom rather than its center accepts an elongated banana resting
    # partly in the bin with its center/top still above the rim (matches demo's bowl test).
    obj_aabb = _entity_aabb(obj)
    obj_bottom_z = float(obj_aabb[0, 2])
    rim_z = TABLE_TOP_Z + CONTAINER_RIM_Z_OFFSET
    inside_bin = obj_bottom_z < rim_z - CONTAINER_RIM_MARGIN
    return bool(inside_bin)


def _parse_place(text: str) -> Union[str, tuple[float, float]]:
    if "," in text:
        x_str, y_str = text.split(",")
        return (float(x_str), float(y_str))
    return text


def main() -> None:
    parser = argparse.ArgumentParser(description="Scripted color-sorting pick-and-place with YCB objects.")
    parser.add_argument("-v", "--vis", action="store_true", default=False)
    parser.add_argument("-c", "--cpu", action="store_true", default=False)
    parser.add_argument("--pick", default="011_banana", help="YCB object name to pick (e.g. 011_banana).")
    parser.add_argument("--place", default=None,
                        help="Place target: a color name (e.g. red) or 'x,y'. Default: auto from object color.")
    parser.add_argument("--tol", type=float, default=0.06, help="Success tolerance (m).")
    parser.add_argument("--save-frames", action="store_true", help="Save world-cam frames per stage.")
    args = parser.parse_args()

    if args.place is None:
        place_target = YCB_LAYOUT[args.pick]["color"]
    else:
        place_target = _parse_place(args.place)

    task = TaskSpec(pick_object=args.pick, place_target=place_target, success_tol=args.tol)

    gs.init(backend=gs.cpu if args.cpu else gs.gpu)
    bundle = build_scene(show_viewer=args.vis, ycb_names=(args.pick,))

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
