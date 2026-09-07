"""Generalized (N-finger) scripted pick-and-place episode, with contact-force based
grasp-stability / peak-stress measurement.

This mirrors `franka_fruit_pick.grasp_demo` closely -- same phase structure (pregrasp
-> descend -> close -> lift -> transport -> release -> retreat), same IK/motion-planning
helpers -- but generalizes every place the stock file hardcodes "2 fingers" (`FINGERS_DOF
= np.arange(7, 9)`, `qpos[-2:]`, `[finger_cmd, finger_cmd]` broadcasts), and adds contact
force sampling during the lift+transport phases (the only phases where "did we keep a
stable, low-stress grip" is a meaningful question).

Object-geometry helpers that never touch finger count (`_topdown_quat`, `_obj_xy_yaw`,
`_entity_aabb`, `_resolve_place`, `check_success`, IK) are imported and reused as-is from
`grasp_demo.py` rather than duplicated.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import torch

_ROOT = Path(__file__).resolve().parent
if str(_ROOT.parent) not in sys.path:
    sys.path.insert(0, str(_ROOT.parent))

from genesis.utils.geom import euler_to_quat  # noqa: E402

from grasp_demo import (  # noqa: E402
    PlaceTarget,
    TaskSpec,
    _entity_aabb,
    _ik,
    _obj_xy_yaw,
    _resolve_place,
    _topdown_quat,
    _to_numpy,
    check_success,
)
from scene_config import FRANKA_QPOS, TABLE_TOP_Z  # noqa: E402

MOTORS_DOF = np.arange(7)

PREGRASP_CLEARANCE = 0.18
LIFT_HAND_Z = TABLE_TOP_Z + 0.30
RETREAT_HAND_Z = TABLE_TOP_Z + 0.35
PLACE_HAND_Z_ABOVE_TARGET = 0.16
GRASP_CENTER_DROP_FRAC = 0.45
PALM_CLEARANCE = 0.02
MOVE_MAX_DQ = 0.006
MOVE_MIN_STEPS = 40
MOVE_SETTLE_STEPS = 15


@dataclass
class GraspProfile:
    """Per-(object, gripper-design) grasp parameters -- the controller half of the
    body/controller pair. Unlike `grasp_demo.GraspProfile`, `grasp_hand_z` /
    `hand_to_fingertip` are always resolved from the *current design's* geometry
    (see `controller_adapt.py`), never a constant tuned for the stock finger.
    """

    yaw_offset: float = 90.0
    hand_to_fingertip: float = 0.105  # co-adapted per gripper design
    close_force: float = -10.0
    center_align: bool = False
    grasp_hand_z_override: float | None = None  # set to skip AABB-derived height entirely
    # Per-object override of the module-level GRASP_CENTER_DROP_FRAC constant, e.g. from
    # grasp_planner.plan_grasp(...).center_drop_frac. Defaults to that same constant, so
    # leaving this unset reproduces the exact prior height formula/behavior.
    center_drop_frac: float = GRASP_CENTER_DROP_FRAC


@dataclass
class GripperRuntime:
    """Everything about a generated gripper design that the episode runner needs,
    independent of `gripper_gen`'s internal representation (kept decoupled so
    `sim_episode` doesn't need to import the generator module)."""

    n_fingers: int
    finger_open_travel: float  # per-joint max travel (m) at full open

    @property
    def fingers_dof(self) -> np.ndarray:
        return np.arange(7, 7 + self.n_fingers)

    def open_vec(self) -> np.ndarray:
        return np.full(self.n_fingers, self.finger_open_travel)

    def closed_vec(self) -> np.ndarray:
        return np.zeros(self.n_fingers)


@dataclass
class EpisodeMetrics:
    success: bool = False
    peak_contact_force: float = 0.0  # N, max single-contact-pair force magnitude on the object
    contact_uptime_frac: float = 0.0  # fraction of lift+transport steps with any object-gripper contact
    max_slip: float = 0.0  # m, max horizontal drift of the object relative to the hand frame
    n_metric_steps: int = 0
    frames: list = field(default_factory=list)


class _MetricsTracker:
    """Accumulates contact-force / slip signal; call `.sample()` once per control step
    during the lift+transport phases only (pregrasp/descend/close/release/retreat are
    not informative for "how stable/gentle was the grip while moving with the object")."""

    def __init__(self, bundle, pick_entity):
        self.bundle = bundle
        self.pick_entity = pick_entity
        self.peak_force = 0.0
        self.n_steps = 0
        self.n_contact_steps = 0
        self.max_slip = 0.0
        self._ref_xy = None

    def sample(self) -> None:
        self.n_steps += 1
        contacts = self.pick_entity.get_contacts(with_entity=self.bundle.franka)
        force_b = contacts.get("force_b")
        if force_b is not None and len(force_b) > 0:
            force_b = _to_numpy_2d(force_b)
            mags = np.linalg.norm(force_b, axis=-1)
            if mags.size:
                self.peak_force = max(self.peak_force, float(mags.max()))
                self.n_contact_steps += 1

        hand_pos = self.bundle.franka.get_link("hand").get_pos()
        hand_pos = np.asarray(hand_pos.detach().cpu().numpy() if hasattr(hand_pos, "detach") else hand_pos).reshape(-1)
        obj_pos = self.pick_entity.get_pos()
        obj_pos = np.asarray(obj_pos.detach().cpu().numpy() if hasattr(obj_pos, "detach") else obj_pos).reshape(-1)
        rel_xy = obj_pos[:2] - hand_pos[:2]
        if self._ref_xy is None:
            self._ref_xy = rel_xy
        slip = float(np.linalg.norm(rel_xy - self._ref_xy))
        self.max_slip = max(self.max_slip, slip)

    def finalize(self) -> tuple[float, float, float, int]:
        uptime = (self.n_contact_steps / self.n_steps) if self.n_steps else 0.0
        return self.peak_force, uptime, self.max_slip, self.n_steps


def _to_numpy_2d(x) -> np.ndarray:
    if hasattr(x, "detach"):
        x = x.detach().cpu().numpy()
    arr = np.asarray(x)
    return arr.reshape(-1, arr.shape[-1]) if arr.ndim >= 1 else arr.reshape(1, -1)


def _set_tail(qpos, n: int, vec) -> None:
    """`qpos[-n:] = vec`, robust to `qpos` being a torch tensor (IK's return type) --
    `_ik`'s original single-finger-scalar assignment relies on torch's scalar
    broadcast, which doesn't extend to assigning a raw numpy array."""
    if hasattr(qpos, "detach"):
        qpos[-n:] = torch.as_tensor(vec, dtype=qpos.dtype, device=qpos.device)
    else:
        qpos[-n:] = vec


def _grasp_hand_z(entity, profile: GraspProfile) -> float:
    if profile.grasp_hand_z_override is not None:
        return profile.grasp_hand_z_override
    aabb = _entity_aabb(entity)
    z_min, z_max = float(aabb[0, 2]), float(aabb[1, 2])
    if not profile.center_align:
        # Non-center-align objects still need *some* height; fall back to resting on
        # the table-relative object top with the design's own fingertip reach.
        return z_max + PALM_CLEARANCE
    center_z = 0.5 * (z_min + z_max)
    half_height = 0.5 * (z_max - z_min)
    fingertip_z = center_z - profile.center_drop_frac * half_height
    z_jaw_align = fingertip_z + profile.hand_to_fingertip
    z_top_clear = z_max + PALM_CLEARANCE
    return max(z_jaw_align, z_top_clear)


def _settle(bundle, rt: GripperRuntime, steps: int) -> None:
    # Arm portion of FRANKA_QPOS unchanged; finger portion resized to n_fingers by
    # repeating the stock finger value (see build_scene._resize_finger_tail).
    arm, fingers = np.array(FRANKA_QPOS[:7]), np.array(FRANKA_QPOS[7:])
    hold = np.concatenate([arm, np.full(rt.n_fingers, fingers[-1])])
    for _ in range(steps):
        bundle.franka.control_dofs_position(hold)
        bundle.scene.step()
        bundle.update_wrist_cam()


def _goto_plan(bundle, rt: GripperRuntime, pos, quat, *, finger_vec, num_waypoints=150, settle=20):
    qpos = _ik(bundle, pos, quat)
    _set_tail(qpos, rt.n_fingers, finger_vec)
    path = bundle.franka.plan_path(qpos_goal=qpos, num_waypoints=num_waypoints)
    for wp in path:
        bundle.franka.control_dofs_position(wp)
        bundle.scene.step()
        bundle.update_wrist_cam()
    for _ in range(settle):
        bundle.franka.control_dofs_position(qpos)
        bundle.scene.step()
        bundle.update_wrist_cam()
    return qpos


def _goto_direct(bundle, rt: GripperRuntime, pos, quat, *, finger_cmd, steps=120, close_force=None):
    qpos = _ik(bundle, pos, quat)
    arm = _to_numpy(qpos[:-rt.n_fingers])
    for _ in range(steps):
        bundle.franka.control_dofs_position(arm, MOTORS_DOF)
        if close_force is not None:
            bundle.franka.control_dofs_force(np.full(rt.n_fingers, close_force), rt.fingers_dof)
        else:
            bundle.franka.control_dofs_position(np.full(rt.n_fingers, finger_cmd), rt.fingers_dof)
        bundle.scene.step()
        bundle.update_wrist_cam()
    return qpos


def _goto_interp(
    bundle, rt: GripperRuntime, pos, quat, *, finger_cmd, close_force=None,
    max_dq=MOVE_MAX_DQ, min_steps=MOVE_MIN_STEPS, settle=MOVE_SETTLE_STEPS, tracker: _MetricsTracker | None = None,
):
    q_goal = _ik(bundle, pos, quat)
    arm_goal = _to_numpy(q_goal[:-rt.n_fingers])
    arm_start = _to_numpy(bundle.franka.get_dofs_position(MOTORS_DOF))
    dist = float(np.max(np.abs(arm_goal - arm_start))) if arm_goal.size else 0.0
    n = max(min_steps, int(np.ceil(dist / max_dq))) if dist > 1e-9 else min_steps

    def _cmd(arm):
        bundle.franka.control_dofs_position(arm, MOTORS_DOF)
        if close_force is not None:
            bundle.franka.control_dofs_force(np.full(rt.n_fingers, close_force), rt.fingers_dof)
        else:
            bundle.franka.control_dofs_position(np.full(rt.n_fingers, finger_cmd), rt.fingers_dof)
        bundle.scene.step()
        bundle.update_wrist_cam()
        if tracker is not None:
            tracker.sample()

    for i in range(1, n + 1):
        _cmd(arm_start + (arm_goal - arm_start) * (i / n))
    for _ in range(settle):
        _cmd(arm_goal)
    return q_goal


def _descend_vertical(bundle, rt: GripperRuntime, xy, z_from, z_to, quat, *, finger_vec, steps=80, settle=15):
    qpos = None
    for z in np.linspace(z_from, z_to, steps):
        qpos = _ik(bundle, np.array([xy[0], xy[1], z]), quat)
        _set_tail(qpos, rt.n_fingers, finger_vec)
        bundle.franka.control_dofs_position(qpos)
        bundle.scene.step()
        bundle.update_wrist_cam()
    for _ in range(settle):
        bundle.franka.control_dofs_position(qpos)
        bundle.scene.step()
        bundle.update_wrist_cam()
    return qpos


def run_pick_place(
    bundle, rt: GripperRuntime, task: TaskSpec, profile: GraspProfile, *, save_frames: bool = False,
) -> EpisodeMetrics:
    pick_entity = bundle.ycb[task.pick_object]
    tracker = _MetricsTracker(bundle, pick_entity)
    frames = []

    def snap(tag):
        if save_frames and bundle.world_cam is not None:
            frames.append((tag, bundle.world_cam.render(rgb=True)[0]))

    _settle(bundle, rt, 60)
    snap("00_start")

    obj_pos, obj_yaw = _obj_xy_yaw(pick_entity)
    grasp_quat = _topdown_quat(obj_yaw + profile.yaw_offset)

    pregrasp = np.array([obj_pos[0], obj_pos[1], obj_pos[2] + PREGRASP_CLEARANCE])
    _goto_plan(bundle, rt, pregrasp, grasp_quat, finger_vec=rt.open_vec())
    snap("01_pregrasp")

    grasp_z = _grasp_hand_z(pick_entity, profile)
    _descend_vertical(bundle, rt, (obj_pos[0], obj_pos[1]), pregrasp[2], grasp_z, grasp_quat, finger_vec=rt.open_vec())
    grasp = np.array([obj_pos[0], obj_pos[1], grasp_z])
    snap("02_reach")

    _goto_direct(bundle, rt, grasp, grasp_quat, finger_cmd=0.0, steps=100, close_force=profile.close_force)
    snap("03_grasp")

    lift = np.array([grasp[0], grasp[1], LIFT_HAND_Z])
    _goto_interp(bundle, rt, lift, grasp_quat, finger_cmd=0.0, close_force=profile.close_force, tracker=tracker)
    snap("04_lift")

    place_xy, place_ref_z, _ = _resolve_place(bundle, task.place_target)
    above = np.array([place_xy[0], place_xy[1], place_ref_z + PLACE_HAND_Z_ABOVE_TARGET])
    _goto_interp(bundle, rt, above, grasp_quat, finger_cmd=0.0, close_force=profile.close_force, tracker=tracker)
    snap("05_above_target")

    _goto_direct(bundle, rt, above, grasp_quat, finger_cmd=float(rt.finger_open_travel), steps=80)
    snap("06_release")

    retreat = np.array([place_xy[0], place_xy[1], RETREAT_HAND_Z])
    _goto_direct(bundle, rt, retreat, grasp_quat, finger_cmd=float(rt.finger_open_travel), steps=80)
    _settle(bundle, rt, 60)
    snap("07_done")

    success = check_success(bundle, task)
    peak_force, uptime, max_slip, n_steps = tracker.finalize()
    return EpisodeMetrics(
        success=success, peak_contact_force=peak_force, contact_uptime_frac=uptime,
        max_slip=max_slip, n_metric_steps=n_steps, frames=frames,
    )
