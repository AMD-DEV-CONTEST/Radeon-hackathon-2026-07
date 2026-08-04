"""Parallel dataset recording using Genesis multi-env batched simulation.

Uses n_envs=N to run N episodes simultaneously on the GPU. All motion
primitives are rewritten in batched form ([n_envs, ...] tensors) so a
single scene.step() advances all N environments at once.

Key differences from record_dataset.py:
- n_envs > 1 (batched simulation, ~8x speedup)
- _goto_interp replaces _goto_plan (plan_path doesn't support batching)
- Each env independently randomizes + picks a different object
- Camera renders only env 0 per step; to record all envs we cycle through
  them (one env's frames per batch). With n_envs=8 and cycling, each env
  gets its frames captured every 8 steps — sufficient at 100Hz (12.5fps
  effective per env, decimated to 30fps dataset = capture every ~3rd
  batch step).

Usage:
    python record_dataset_parallel.py --episodes 200 --n-envs 8 --split train
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

import cv2
import numpy as np

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import genesis as gs
from lerobot.configs.video import RGBEncoderConfig
from lerobot.datasets.lerobot_dataset import LeRobotDataset

from build_scene import build_scene
from paths import DATASETS_DIR
from randomize import RandomizationConfig
from sk_grasp_demo import DEFAULT_PROFILE, GRASP_PROFILES
from scene_config import (
    CONTAINER_INNER_SIZE,
    CONTAINER_RIM_MARGIN,
    CONTAINER_RIM_Z_OFFSET,
    FRANKA_QPOS,
    FRANKA_KP,
    FRANKA_KV,
    FRANKA_FORCE_MIN,
    FRANKA_FORCE_MAX,
    REACH_X,
    REACH_Y,
    TABLE_TOP_Z,
    YCB_DISPLAY_NAMES,
    YCB_LAYOUT,
    get_ycb_assets,
    get_ycb_names_for_split,
)
from genesis.utils.geom import euler_to_quat, euler_to_R, trans_R_to_T

# Motion constants (from sk_grasp_demo)
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
CLOSE_FORCE = -12.0

CONTROL_FPS = 100
JOINT_NAMES = [
    "panda_joint1", "panda_joint2", "panda_joint3", "panda_joint4",
    "panda_joint5", "panda_joint6", "panda_joint7",
    "panda_finger_joint1", "panda_finger_joint2",
]
TRAIN_YCB_NAMES = ("013_apple", "011_banana", "018_plum")
EVAL_YCB_NAMES = ("014_lemon", "017_orange")


def task_description(pick_object: str, place_color: str) -> str:
    display = YCB_DISPLAY_NAMES.get(pick_object, pick_object)
    return f"pick the {display} into the {place_color} bin"


def _ycb_names_for_split(split: str) -> tuple[str, ...]:
    return get_ycb_names_for_split(split)


def build_features(img_wh: tuple[int, int]) -> dict:
    w, h = img_wh
    vec = {"dtype": "float32", "shape": (len(JOINT_NAMES),), "names": JOINT_NAMES}
    img = {"dtype": "video", "shape": (h, w, 3), "names": ["height", "width", "channel"]}
    return {
        "observation.state": dict(vec),
        "action": dict(vec),
        "observation.images.world": dict(img),
        "observation.images.wrist": dict(img),
    }


class BatchRecorder:
    """Records frames from one specific env index of a batched scene.

    At 100Hz sim with n_envs=N, we capture env `env_idx` every batch step.
    Decimation to target fps (30) via fractional-step accumulator.
    """

    def __init__(self, bundle, *, env_idx: int, fps: int, img_wh: tuple[int, int]):
        self.bundle = bundle
        self.env_idx = env_idx
        self.fps = fps
        self.img_w, self.img_h = img_wh
        self.steps_per_frame = CONTROL_FPS / fps
        self.reset()

    def reset(self) -> None:
        self.states: list[np.ndarray] = []
        self.actions: list[np.ndarray] = []
        self.world_imgs: list[np.ndarray] = []
        self.wrist_imgs: list[np.ndarray] = []
        self._accum = self.steps_per_frame

    def __len__(self) -> int:
        return len(self.states)

    def on_step(self, actions: np.ndarray) -> None:
        """Called every sim step with [n_envs, 9] actions. Records env_idx."""
        self._accum += 1.0
        if self._accum < self.steps_per_frame:
            return
        self._accum -= self.steps_per_frame

        idx = self.env_idx
        qpos = self.bundle.franka.get_qpos()[idx].cpu().numpy().reshape(-1).astype(np.float32)
        action = np.asarray(actions[idx]).reshape(-1).astype(np.float32)

        # Render this env's camera by switching _env_idx
        self.bundle.world_cam._env_idx = idx
        self.bundle.wrist_cam._env_idx = idx
        world_img = self.bundle.world_cam.render(rgb=True)
        wrist_img = self.bundle.wrist_cam.render(rgb=True)

        # render returns tuple; img[0] is the bound env's image
        world = self._resize(world_img[0] if isinstance(world_img, tuple) else world_img)
        wrist = self._resize(wrist_img[0] if isinstance(wrist_img, tuple) else wrist_img)

        self.states.append(qpos)
        self.actions.append(action)
        self.world_imgs.append(world)
        self.wrist_imgs.append(wrist)

    def _resize(self, img) -> np.ndarray:
        img = np.asarray(img)
        if (img.shape[1], img.shape[0]) != (self.img_w, self.img_h):
            img = cv2.resize(img, (self.img_w, self.img_h), interpolation=cv2.INTER_AREA)
        return np.ascontiguousarray(img, dtype=np.uint8)

    def flush_to(self, dataset: LeRobotDataset, task: str) -> None:
        for state, action, world, wrist in zip(self.states, self.actions, self.world_imgs, self.wrist_imgs):
            dataset.add_frame({
                "observation.state": state,
                "action": action,
                "observation.images.world": world,
                "observation.images.wrist": wrist,
                "task": task,
            })
        dataset.save_episode()


# ---- Batched motion primitives ----

def _batch_quat(yaw_deg: np.ndarray, n: int) -> np.ndarray:
    """Top-down quaternion for each env. yaw_deg: [n] array."""
    quats = []
    for i in range(n):
        q = euler_to_quat(np.array([180.0, 0.0, float(yaw_deg[i])]))
        quats.append(q)
    return np.array(quats)  # [n, 4]


def _batch_ik(franka, pos: np.ndarray, quat: np.ndarray) -> np.ndarray:
    """IK for all envs. pos: [n, 3], quat: [n, 4] → qpos [n, 9]."""
    hand = franka.get_link("hand")
    return franka.inverse_kinematics(link=hand, pos=pos, quat=quat).cpu().numpy()


def _batch_settle(bundle, steps: int, step_callback=None) -> None:
    """Settle all envs with hold position."""
    n = bundle.scene.n_envs
    hold = np.tile(np.array(FRANKA_QPOS), (n, 1))
    for _ in range(steps):
        bundle.franka.control_dofs_position(hold)
        bundle.scene.step()
        bundle.update_wrist_cam()
        if step_callback is not None:
            step_callback(hold)


def _batch_goto_interp(bundle, pos_goal: np.ndarray, quat_goal: np.ndarray,
                       *, finger_cmd: float, close_force: float | np.ndarray | None = None,
                       active: np.ndarray | None = None,
                       max_dq=MOVE_MAX_DQ, min_steps=MOVE_MIN_STEPS,
                       settle=MOVE_SETTLE_STEPS,
                       step_callback=None) -> np.ndarray:
    """Batched interpolation to a target pose. Only active envs move; others hold.

    pos_goal: [n, 3], quat_goal: [n, 4]
    active: [n] bool mask (None = all active)
    close_force: scalar (all envs) or [n] per-env array; None → position control.
    """
    n = bundle.scene.n_envs
    if active is None:
        active = np.ones(n, dtype=bool)

    q_goal = _batch_ik(bundle.franka, pos_goal, quat_goal)  # [n, 9]
    arm_goal = q_goal[:, :-2]
    arm_start = bundle.franka.get_dofs_position(MOTORS_DOF).cpu().numpy()  # [n, 7]

    # Per-env step count based on max joint distance
    dist = np.max(np.abs(arm_goal - arm_start), axis=1)
    n_steps = int(max(min_steps, np.ceil(np.max(dist[active]) / max_dq))) if np.any(active) else min_steps

    close_arr = None if close_force is None else np.broadcast_to(np.asarray(close_force, dtype=float), (n,))
    # Symbolic encoding: record -0.04 (close) / +0.04 (open) so the finger
    # dimension has the same value range as v6 baseline. Physical control
    # still uses close_force (-12N) — only the recorded action value changes.
    # Eval's apply_action maps finger < 0 → force(finger * 300), >= 0 → position.
    finger_target = -0.04 if close_force is not None else finger_cmd

    for i in range(1, n_steps + 1):
        alpha = i / n_steps
        arm = arm_start + (arm_goal - arm_start) * alpha  # [n, 7]
        # Inactive envs hold their start position
        arm[~active] = arm_start[~active]
        action = np.concatenate([arm, np.full((n, 2), finger_target)], axis=1)

        bundle.franka.control_dofs_position(arm, MOTORS_DOF)
        if close_arr is not None:
            bundle.franka.control_dofs_force(np.column_stack([close_arr, close_arr]), FINGERS_DOF)
        else:
            fingers = np.full((n, 2), finger_cmd)
            bundle.franka.control_dofs_position(fingers, FINGERS_DOF)
        bundle.scene.step()
        bundle.update_wrist_cam()
        if step_callback is not None:
            step_callback(action)

    # Settle
    hold_arm = arm_goal.copy()
    hold_arm[~active] = arm_start[~active]
    hold_action = np.concatenate([hold_arm, np.full((n, 2), finger_target)], axis=1)
    for _ in range(settle):
        bundle.franka.control_dofs_position(hold_arm, MOTORS_DOF)
        if close_arr is not None:
            bundle.franka.control_dofs_force(np.column_stack([close_arr, close_arr]), FINGERS_DOF)
        else:
            bundle.franka.control_dofs_position(np.full((n, 2), finger_cmd), FINGERS_DOF)
        bundle.scene.step()
        bundle.update_wrist_cam()
        if step_callback is not None:
            step_callback(hold_action)

    return q_goal


def _batch_descend(bundle, xy: np.ndarray, z_from: float, z_to: np.ndarray,
                   quat: np.ndarray, *, finger: float, steps: int = 80,
                   settle: int = 15, active: np.ndarray | None = None,
                   step_callback=None) -> np.ndarray:
    """Batched vertical descent. xy: [n, 2], z_to: [n], quat: [n, 4]."""
    n = bundle.scene.n_envs
    if active is None:
        active = np.ones(n, dtype=bool)

    qpos_last = None
    for step in range(steps):
        frac = (step + 1) / steps
        z_cur = z_from + (z_to - z_from) * frac  # [n]
        pos = np.column_stack([xy, z_cur])  # [n, 3]
        q = _batch_ik(bundle.franka, pos, quat)
        q[:, -2:] = finger
        arm = q[:, :-2]
        arm[~active] = bundle.franka.get_dofs_position(MOTORS_DOF).cpu().numpy()[~active]
        action = q.copy()
        action[~active] = np.concatenate([
            bundle.franka.get_dofs_position(MOTORS_DOF).cpu().numpy()[~active],
            np.full(((~active).sum(), 2), finger)
        ], axis=1)
        bundle.franka.control_dofs_position(arm, MOTORS_DOF)
        bundle.franka.control_dofs_position(np.full((n, 2), finger), FINGERS_DOF)
        bundle.scene.step()
        bundle.update_wrist_cam()
        if step_callback is not None:
            step_callback(action)
        qpos_last = q

    # Settle
    for _ in range(settle):
        arm = qpos_last[:, :-2]
        bundle.franka.control_dofs_position(arm, MOTORS_DOF)
        bundle.franka.control_dofs_position(np.full((n, 2), finger), FINGERS_DOF)
        bundle.scene.step()
        bundle.update_wrist_cam()
        if step_callback is not None:
            step_callback(qpos_last.copy())

    return qpos_last


def _batch_goto_direct(bundle, pos_goal: np.ndarray, quat_goal: np.ndarray,
                       *, finger_cmd: float, close_force: float | np.ndarray | None = None,
                       steps: int = 120, active: np.ndarray | None = None,
                       step_callback=None) -> np.ndarray:
    """Batched direct move (hold position for `steps` steps with force/position control).

    close_force may be a scalar (all envs) or an [n] per-env array; None → position control.
    """
    n = bundle.scene.n_envs
    if active is None:
        active = np.ones(n, dtype=bool)

    q = _batch_ik(bundle.franka, pos_goal, quat_goal)
    arm = q[:, :-2]
    arm_start = bundle.franka.get_dofs_position(MOTORS_DOF).cpu().numpy()
    arm[~active] = arm_start[~active]

    close_arr = None if close_force is None else np.broadcast_to(np.asarray(close_force, dtype=float), (n,))
    finger_target = -0.04 if close_force is not None else finger_cmd
    action = np.concatenate([arm, np.full((n, 2), finger_target)], axis=1)

    for _ in range(steps):
        bundle.franka.control_dofs_position(arm, MOTORS_DOF)
        if close_arr is not None:
            bundle.franka.control_dofs_force(np.column_stack([close_arr, close_arr]), FINGERS_DOF)
        else:
            bundle.franka.control_dofs_position(np.full((n, 2), finger_cmd), FINGERS_DOF)
        bundle.scene.step()
        bundle.update_wrist_cam()
        if step_callback is not None:
            step_callback(action)

    return q


def _batch_grasp_hand_z(bundle, obj_name: str, env_idx: int) -> float:
    """Get grasp height for one object in one env, honoring the object's GraspProfile."""
    profile = GRASP_PROFILES.get(obj_name, DEFAULT_PROFILE)
    if not profile.center_align:
        return profile.grasp_hand_z
    entity = bundle.objects[obj_name]
    aabb = entity.get_AABB().cpu().numpy()  # [n, 2, 3]
    aabb_env = aabb[env_idx]
    z_min, z_max = float(aabb_env[0, 2]), float(aabb_env[1, 2])
    center_z = 0.5 * (z_min + z_max)
    half_height = 0.5 * (z_max - z_min)
    fingertip_z = center_z - GRASP_CENTER_DROP_FRAC * half_height
    z_jaw_align = fingertip_z + HAND_TO_FINGERTIP
    z_top_clear = z_max + PALM_CLEARANCE
    return max(z_jaw_align, z_top_clear)


def _batch_obj_pos_yaw(bundle, obj_name: str) -> tuple[np.ndarray, np.ndarray]:
    """Get pos [n, 3] and yaw [n] for an object across all envs."""
    entity = bundle.objects[obj_name]
    pos = entity.get_pos().cpu().numpy()  # [n, 3]
    quat = entity.get_quat().cpu().numpy()  # [n, 4]
    # Extract yaw from quaternion
    from genesis.utils.geom import quat_to_xyz
    yaw = np.array([quat_to_xyz(quat[i], degrees=True)[2] for i in range(pos.shape[0])])
    return pos, yaw


def _batch_reset_envs(bundle, env_specs: list[dict]) -> None:
    """Reset each env's robot + objects independently.

    env_specs: list of {pick_object, obj_positions: {name: [x,y,z]}, obj_quats: {name: [w,x,y,z]}} per env.
    """
    n = bundle.scene.n_envs

    # Reset robot qpos for all envs
    qpos = np.tile(np.array(FRANKA_QPOS), (n, 1))
    bundle.franka.set_qpos(qpos, zero_velocity=True)

    # Reset each object's position per env
    for obj_name in bundle.objects:
        entity = bundle.objects[obj_name]
        positions = np.zeros((n, 3))
        quats = np.zeros((n, 4))
        for i, spec in enumerate(env_specs):
            if obj_name in spec.get("obj_positions", {}):
                positions[i] = spec["obj_positions"][obj_name]
                quats[i] = spec["obj_quats"][obj_name]
            else:
                # Default home position from YCB_LAYOUT
                layout = YCB_LAYOUT[obj_name]
                x, y, _ = layout["pos"]
                z = TABLE_TOP_Z + get_ycb_assets((obj_name,))[obj_name].rest_z_offset
                positions[i] = [x, y, z]
                quats[i] = [1, 0, 0, 0]

        entity.set_pos(positions, zero_velocity=True, skip_forward=True)
        entity.set_quat(quats, zero_velocity=True, skip_forward=False)

    # Settle
    _batch_settle(bundle, 80)


def _batch_check_success(bundle, env_idx: int, pick_object: str, place_color: str) -> bool:
    """Check success for one env: object inside bin (horizontal + vertical)."""
    obj = bundle.objects[pick_object]
    pos = obj.get_pos().cpu().numpy()[env_idx]  # [3]

    container = bundle.containers.get(place_color)
    if container is None:
        return False

    cont_pos = container.get_pos().cpu().numpy()[env_idx]  # [3]

    # Layer 1: horizontal — object center within bin inner footprint
    half_inner = CONTAINER_INNER_SIZE / 2
    inside_x = abs(pos[0] - cont_pos[0]) < half_inner
    inside_y = abs(pos[1] - cont_pos[1]) < half_inner
    if not (inside_x and inside_y):
        return False

    # Layer 2: vertical — the object's lowest point (AABB bottom) has dropped below the
    # rim, so it is clearly inside the bin (accepts a banana resting partly in the bin).
    obj_aabb = obj.get_AABB().cpu().numpy()[env_idx]
    obj_bottom_z = float(obj_aabb[0, 2])
    rim_z = TABLE_TOP_Z + CONTAINER_RIM_Z_OFFSET
    return bool(obj_bottom_z < rim_z - CONTAINER_RIM_MARGIN)


def _run_one_batch(bundle, env_specs: list[dict], recorders: list,
                   split_colors: tuple[str, ...]) -> list[bool]:
    """Run one batch of N parallel pick-place episodes.

    env_specs: per-env {pick_object, obj_positions, obj_quats, seed}
    recorders: per-env BatchRecorder (or None to skip recording)
    Returns: per-env success list.
    """
    n = bundle.scene.n_envs

    # Reset all envs
    _batch_reset_envs(bundle, env_specs)

    # Per-env pick info
    pick_objects = [s["pick_object"] for s in env_specs]
    place_colors = [YCB_LAYOUT[obj]["color"] for obj in pick_objects]

    # Get per-env object positions (after reset+settle)
    obj_positions = {}
    obj_yaws = {}
    for obj_name in set(pick_objects):
        pos, yaw = _batch_obj_pos_yaw(bundle, obj_name)
        obj_positions[obj_name] = pos  # [n, 3]
        obj_yaws[obj_name] = yaw  # [n]

    # Compute per-env grasp targets
    grasp_zs = {}  # per object name: per-env grasp z
    for obj_name in set(pick_objects):
        gz = np.zeros(n)
        for i in range(n):
            if pick_objects[i] == obj_name:
                gz[i] = _batch_grasp_hand_z(bundle, obj_name, i)
        grasp_zs[obj_name] = gz

    # Container positions per env
    container_positions = {}
    for color in set(place_colors):
        cont = bundle.containers[color]
        container_positions[color] = cont.get_pos().cpu().numpy()  # [n, 3]

    # Active mask: which envs are still running (not done/failed)
    active = np.ones(n, dtype=bool)
    successes = [False] * n

    # Step callback: calls each env's recorder.on_step with [n, 9] actions
    # Each recorder independently decimates (only renders when its frame counter hits)
    def _step_cb(actions: np.ndarray) -> None:
        for r in recorders:
            if r is not None:
                r.on_step(actions)
    _batch_settle(bundle, 20, step_callback=_step_cb)

    # Build per-env target positions for each phase
    # Since different envs pick different objects, we need per-env pos/quat
    def _per_env_pos(phase: str) -> np.ndarray:
        """Compute [n, 3] target positions for all envs for a given phase."""
        pos = np.zeros((n, 3))
        for i in range(n):
            obj = pick_objects[i]
            op = obj_positions[obj][i]
            gz = grasp_zs[obj][i]
            pc = place_colors[i]
            cp = container_positions[pc][i]

            if phase == "pregrasp":
                pos[i] = [op[0], op[1], op[2] + PREGRASP_CLEARANCE]
            elif phase == "grasp":
                pos[i] = [op[0], op[1], gz]
            elif phase == "lift":
                pos[i] = [op[0], op[1], LIFT_HAND_Z]
            elif phase == "above_target":
                pos[i] = [cp[0], cp[1], cp[2] + PLACE_HAND_Z_ABOVE_TARGET]
            elif phase == "retreat":
                pos[i] = [cp[0], cp[1], RETREAT_HAND_Z]
        return pos

    def _per_env_quat() -> np.ndarray:
        """Compute [n, 4] grasp quats based on each env's object yaw + profile yaw_offset."""
        yaws = np.zeros(n)
        for i in range(n):
            obj = pick_objects[i]
            yaws[i] = obj_yaws[obj][i] + GRASP_PROFILES.get(obj, DEFAULT_PROFILE).yaw_offset
        return _batch_quat(yaws, n)

    quat = _per_env_quat()
    # Per-env close force from each object's GraspProfile
    close_forces = np.array([GRASP_PROFILES.get(pick_objects[i], DEFAULT_PROFILE).close_force
                             for i in range(n)])

    # Phase 1: Pregrasp (interp — replaces _goto_plan)
    pregrasp_pos = _per_env_pos("pregrasp")
    _batch_goto_interp(bundle, pregrasp_pos, quat, finger_cmd=GRIPPER_OPEN,
                       active=active, step_callback=_step_cb)

    # Phase 2: Descend to grasp height
    grasp_pos = _per_env_pos("grasp")
    grasp_z = np.array([grasp_zs[pick_objects[i]][i] for i in range(n)])
    pregrasp_z = np.array([pregrasp_pos[i, 2] for i in range(n)])
    _batch_descend(bundle, grasp_pos[:, :2], pregrasp_z[0], grasp_z, quat,
                   finger=GRIPPER_OPEN, active=active, step_callback=_step_cb)

    # Phase 3: Close gripper (force control, per-object close force)
    _batch_goto_direct(bundle, grasp_pos, quat, finger_cmd=0.0,
                       close_force=close_forces, steps=100, active=active,
                       step_callback=_step_cb)

    # Phase 4: Lift
    lift_pos = _per_env_pos("lift")
    _batch_goto_interp(bundle, lift_pos, quat, finger_cmd=0.0,
                       close_force=close_forces, active=active,
                       step_callback=_step_cb)

    # Phase 5: Move above place target
    above_pos = _per_env_pos("above_target")
    _batch_goto_interp(bundle, above_pos, quat, finger_cmd=0.0,
                       close_force=close_forces, active=active,
                       step_callback=_step_cb)

    # Phase 6: Release
    _batch_goto_direct(bundle, above_pos, quat, finger_cmd=GRIPPER_OPEN,
                       steps=80, active=active, step_callback=_step_cb)

    # Phase 7: Retreat
    retreat_pos = _per_env_pos("retreat")
    _batch_goto_direct(bundle, retreat_pos, quat, finger_cmd=GRIPPER_OPEN,
                       steps=80, active=active, step_callback=_step_cb)

    # Settle and check success
    _batch_settle(bundle, 60, step_callback=_step_cb)

    for i in range(n):
        successes[i] = _batch_check_success(bundle, i, pick_objects[i], place_colors[i])

    return successes


def main() -> None:
    parser = argparse.ArgumentParser(description="Parallel dataset recording with Genesis multi-env.")
    parser.add_argument("--episodes", type=int, default=50, help="Target SUCCESSFUL episodes.")
    parser.add_argument("--n-envs", type=int, default=8, help="Parallel environments.")
    parser.add_argument("--max-batches", type=int, default=0, help="Cap on batches (0 = auto).")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--img-width", type=int, default=640)
    parser.add_argument("--img-height", type=int, default=360)
    parser.add_argument("--split", choices=["train", "eval", "all"], default="train")
    parser.add_argument("--repo-id", default="color_sort/train_parallel")
    parser.add_argument("--root", default=None)
    parser.add_argument("--vcodec", default="libsvtav1")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--jitter", type=float, default=0.04)
    args = parser.parse_args()

    img_wh = (args.img_width, args.img_height)
    root = Path(args.root) if args.root else DATASETS_DIR / args.repo_id.split("/")[-1]
    if root.exists():
        if args.overwrite:
            shutil.rmtree(root)
        else:
            raise SystemExit(f"[record_parallel] {root} exists. Use --overwrite.")

    ycb_names = _ycb_names_for_split(args.split)
    pick_pool = list(ycb_names)

    n = args.n_envs
    gs.init(backend=gs.gpu)

    bundle = build_scene(
        n_envs=n,
        add_world_cam=True,
        add_wrist_cam=True,
        ycb_names=ycb_names,
    )

    dataset = LeRobotDataset.create(
        repo_id=args.repo_id,
        fps=args.fps,
        features=build_features(img_wh),
        root=root,
        robot_type="franka",
        use_videos=True,
        rgb_encoder=RGBEncoderConfig(vcodec=args.vcodec),
    )

    # Configure wrist cam attach
    wrist_link = bundle._wrist_link
    if bundle.wrist_cam is not None and wrist_link is not None:
        offset_T = trans_R_to_T(
            np.asarray([0.04, 0.0, 0.0], dtype=np.float64),
            euler_to_R(np.array([180.0, 0.0, 0.0], dtype=np.float64)),
        )
        bundle.wrist_cam.attach(wrist_link, offset_T)
        bundle.wrist_cam.move_to_attach()

    pick_rng = np.random.default_rng(args.seed)

    n_success = 0
    batch_num = 0
    max_batches = args.max_batches if args.max_batches > 0 else (args.episodes // n + 5) * 3

    print(f"[record_parallel] n_envs={n}, target={args.episodes} episodes, "
          f"split={args.split}, pool={pick_pool}")

    # Slot method (ported from demo randomize.py): each object owns a home slot; per-object
    # jitter is clamped to half the clearance to the nearest neighbor so jittered objects
    # can never overlap, and yaw is jittered only around the home orientation (a large yaw
    # on the long banana would swing it into neighbors).
    ycb_assets = get_ycb_assets(tuple(bundle.objects.keys()))
    names = list(bundle.objects.keys())
    home = {n: np.asarray(YCB_LAYOUT[n]["pos"][:2], dtype=float) for n in names}
    home_yaw = {n: float(YCB_LAYOUT[n]["euler"][2]) for n in names}
    radius = {n: ycb_assets[n].radius_xy for n in names}
    OVERLAP_MARGIN = 0.02
    safe_jitter: dict[str, float] = {}
    for a in names:
        gap = np.inf
        for b in names:
            if a == b:
                continue
            clearance = float(np.linalg.norm(home[a] - home[b])) - radius[a] - radius[b] - OVERLAP_MARGIN
            gap = min(gap, clearance)
        safe_jitter[a] = max(0.0, 0.5 * gap)

    while n_success < args.episodes and batch_num < max_batches:
        # Prepare per-env specs
        env_specs = []
        for i in range(n):
            episode_seed = args.seed + batch_num * n + i
            ep_rng = np.random.default_rng(episode_seed)

            pick_object = str(pick_rng.choice(pick_pool))

            # Randomize object positions for this env (non-overlapping slot jitter)
            obj_positions = {}
            obj_quats = {}
            for obj_name in names:
                jitter = min(args.jitter, safe_jitter[obj_name])
                dx, dy = ep_rng.uniform(-jitter, jitter, size=2)
                x = float(np.clip(home[obj_name][0] + dx, *REACH_X))
                y = float(np.clip(home[obj_name][1] + dy, *REACH_Y))
                z = TABLE_TOP_Z + ycb_assets[obj_name].rest_z_offset
                dyaw = float(ep_rng.uniform(-30.0, 30.0))
                quat = euler_to_quat(np.array([0.0, 0.0, home_yaw[obj_name] + dyaw]))

                obj_positions[obj_name] = [x, y, z]
                obj_quats[obj_name] = quat

            env_specs.append({
                "pick_object": pick_object,
                "obj_positions": obj_positions,
                "obj_quats": obj_quats,
                "seed": episode_seed,
            })

        # Create per-env recorders
        recorders = []
        for i in range(n):
            r = BatchRecorder(bundle, env_idx=i, fps=args.fps, img_wh=img_wh)
            recorders.append(r)

        # Run the batch
        import time
        t0 = time.time()
        successes = _run_one_batch(bundle, env_specs, recorders, ycb_names)
        t1 = time.time()

        # Save successful episodes
        for i in range(n):
            if successes[i] and len(recorders[i]) > 0:
                pick_obj = env_specs[i]["pick_object"]
                place_color = YCB_LAYOUT[pick_obj]["color"]
                task_text = task_description(pick_obj, place_color)
                recorders[i].flush_to(dataset, task_text)
                n_success += 1
                print(f"[record_parallel] ep {n_success}/{args.episodes} "
                      f"(batch {batch_num}, env {i}, pick={pick_obj}, "
                      f"{len(recorders[i])} frames)")
            elif successes[i]:
                print(f"[record_parallel] batch {batch_num} env {i}: success but 0 frames")
            else:
                pick_obj = env_specs[i]["pick_object"]
                print(f"[record_parallel] batch {batch_num} env {i}: FAIL (pick={pick_obj})")

        print(f"[record_parallel] batch {batch_num}: {sum(successes)}/{n} success "
              f"in {t1-t0:.1f}s ({n/(t1-t0):.1f} ep/s)")

        batch_num += 1

    dataset.finalize()
    print(f"[record_parallel] done: {n_success} success in {batch_num} batches -> {root}")


if __name__ == "__main__":
    main()