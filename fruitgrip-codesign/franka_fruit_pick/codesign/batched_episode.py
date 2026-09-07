"""Session 5, Priority 6: batched (n_envs>1) scripted pick-and-place + reset.

Genesis's entity API (get_pos/get_quat/get_AABB, inverse_kinematics, plan_path,
control_dofs_position/force, get_contacts) is unconditionally batched once a scene is
built with n_envs>1 -- confirmed empirically (a single non-batched IK call raises
"First dimension of `pos` must be equal to `scene.n_envs`", plan_path and dof-subset
+ batched control both work cleanly). What is NOT batched is the *control logic* in
sim_episode.py/grasp_demo.py/randomize.py -- every motion helper there assumes a
single environment. This module is the batched counterpart of that control logic,
not a new physics capability.

Batching axis: trials are grouped by their SHARED picked object (the natural grouping,
since a batched call needs one consistent grasp target/profile). Within a group,
position/yaw jitter and friction/mass are drawn INDEPENDENTLY per env (this is the
whole point -- N genuinely different domain-randomization instances stepped in
lockstep), but the object identity and place target are the same across the batch.
See evaluate.py's evaluate_candidate_batched for how a candidate's trial seeds are
split into per-object batched calls.

`quat_to_xyz` (extracting yaw from a quaternion) is NOT batch-friendly -- it's a
numba-jitted single-quaternion function (confirmed empirically: a (N,4) input raises
a numba typing error). Looped per-env below; negligible cost next to `scene.step()`.
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

from genesis.utils.geom import euler_to_quat, quat_to_xyz  # noqa: E402

from grasp_demo import PlaceTarget  # noqa: E402
from randomize import DomainRandomizationConfig, RandomizationConfig  # noqa: E402
from scene_config import FRANKA_QPOS, REACH_X, REACH_Y, TABLE_TOP_Z, YCB_LAYOUT, get_ycb_assets  # noqa: E402

from sim_episode import GraspProfile, GripperRuntime  # noqa: E402

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
OVERLAP_MARGIN = 0.02
DEFAULT_PLACE_CONTAINER = "024_bowl"


def _to_np(x) -> np.ndarray:
    return x.detach().cpu().numpy() if hasattr(x, "detach") else np.asarray(x)


# ---------------------------------------------------------------------------
# Batched reset (position/yaw jitter + dynamics DR, independent draws per env)
# ---------------------------------------------------------------------------


@dataclass
class BatchTask:
    pick_object: str
    place_target: PlaceTarget
    n_envs: int
    success_tol: float = 0.06


class BatchEnvRandomizer:
    """Batched counterpart of randomize.EnvRandomizer. One instance resets a whole
    batch (n_envs = number of trials in this object-group) to N independently
    domain-randomized instances of the SAME picked object in one call.
    """

    def __init__(self, bundle, n_envs: int, config: RandomizationConfig | None = None):
        self.bundle = bundle
        self.n_envs = n_envs
        self.cfg = config or RandomizationConfig()

        self._assets = get_ycb_assets()
        self.names = list(YCB_LAYOUT.keys())
        self.home = {n: np.asarray(YCB_LAYOUT[n]["pos"][:2], dtype=float) for n in self.names}
        self.home_yaw = {n: float(YCB_LAYOUT[n]["euler"][2]) for n in self.names}
        self.radius = {n: self._assets[n].radius_xy for n in self.names}
        self.rest_z = {n: self._assets[n].rest_z_offset for n in self.names}
        self.safe_jitter = self._compute_safe_jitter()
        self._base_mass: dict[str, np.ndarray] = {}

    def _compute_safe_jitter(self) -> dict[str, float]:
        safe: dict[str, float] = {}
        for a in self.names:
            gap = np.inf
            for b in self.names:
                if a == b:
                    continue
                center_dist = float(np.linalg.norm(self.home[a] - self.home[b]))
                clearance = center_dist - self.radius[a] - self.radius[b] - OVERLAP_MARGIN
                gap = min(gap, clearance)
            safe[a] = max(0.0, 0.5 * gap) if np.isfinite(gap) else self.cfg.pos_jitter
        return safe

    def reset(self, pick_object: str, seeds: list[int]) -> BatchTask:
        """`seeds`: one seed per env (len == self.n_envs), each independently driving
        that env's pose jitter + dynamics draw -- so this batch call reproduces
        exactly what N separate `EnvRandomizer.reset(seed=seeds[i])` calls (for the
        same `pick_object`) would have drawn, just executed in lockstep."""
        assert len(seeds) == self.n_envs
        rngs = [np.random.default_rng(s) for s in seeds]

        self._reset_robot()
        self._place_objects(rngs)
        if self.cfg.dr.enabled:
            self._randomize_dynamics(rngs)
        self._settle()
        return BatchTask(pick_object=pick_object, place_target=DEFAULT_PLACE_CONTAINER, n_envs=self.n_envs, success_tol=self.cfg.success_tol)

    def _franka_hold_qpos(self) -> np.ndarray:
        n_finger_dofs = self.bundle.franka.n_dofs - 7
        arm, fingers = np.asarray(FRANKA_QPOS[:7], dtype=float), np.asarray(FRANKA_QPOS[7:], dtype=float)
        return np.concatenate([arm, np.full(n_finger_dofs, fingers[-1])])

    def _reset_robot(self) -> None:
        hold = np.tile(self._franka_hold_qpos(), (self.n_envs, 1))
        self.bundle.franka.set_qpos(hold, zero_velocity=True)

    def _place_objects(self, rngs: list[np.random.Generator]) -> None:
        for name in self.names:
            jitter = min(self.cfg.pos_jitter, self.safe_jitter[name])
            xs, ys, quats = [], [], []
            for rng in rngs:
                dx, dy = rng.uniform(-jitter, jitter, size=2)
                x = float(np.clip(self.home[name][0] + dx, *REACH_X))
                y = float(np.clip(self.home[name][1] + dy, *REACH_Y))
                dyaw = float(rng.uniform(-self.cfg.yaw_jitter, self.cfg.yaw_jitter))
                yaw = self.home_yaw[name] + dyaw
                xs.append(x); ys.append(y)
                quats.append(euler_to_quat(np.array([0.0, 0.0, yaw])))
            z = TABLE_TOP_Z + self.rest_z[name] + 0.002
            pos_batched = np.stack([np.array(xs), np.array(ys), np.full(self.n_envs, z)], axis=1)  # (N,3)
            quat_batched = np.stack(quats, axis=0)  # (N,4)

            entity = self.bundle.ycb[name]
            entity.set_pos(pos_batched, relative=False, zero_velocity=True, skip_forward=True)
            entity.set_quat(quat_batched, relative=False, zero_velocity=True, skip_forward=False)

    def _randomize_dynamics(self, rngs: list[np.random.Generator]) -> None:
        dr = self.cfg.dr
        b = self.bundle
        lo, hi = dr.friction_ratio_range
        ratios = np.array([float(rng.uniform(lo, hi)) for rng in rngs])  # (N,)
        self._set_friction_ratio_batched(b.franka, ratios)
        for name in self.names:
            self._set_friction_ratio_batched(b.ycb[name], ratios)
        for table_entity in getattr(b, "table", []) or []:
            self._set_friction_ratio_batched(table_entity, ratios)

        mlo, mhi = dr.mass_ratio_range
        if not (mlo == 1.0 and mhi == 1.0):
            for name in self.names:
                base = self._object_base_mass(name)  # (n_links,)
                mass_ratios = np.array([float(rng.uniform(mlo, mhi)) for rng in rngs])  # (N,)
                shift = base[None, :] * (mass_ratios[:, None] - 1.0)  # (N, n_links)
                self._set_mass_shift_batched(b.ycb[name], shift)

    def _object_base_mass(self, name: str) -> np.ndarray:
        if name not in self._base_mass:
            entity = self.bundle.ycb[name]
            mass = np.asarray(_to_np(entity.get_links_inertial_mass()), dtype=np.float64)
            if mass.ndim > 1:
                mass = mass.reshape(-1, entity.n_links)[0]
            self._base_mass[name] = mass.reshape(-1)[: entity.n_links]
        return self._base_mass[name]

    def _set_friction_ratio_batched(self, entity, ratios: np.ndarray) -> None:
        n = entity.n_links
        payload = np.tile(ratios[:, None], (1, n)).astype(np.float32)  # (N, n_links)
        entity.set_friction_ratio(payload, links_idx_local=np.arange(n))

    def _set_mass_shift_batched(self, entity, shift_per_env_link: np.ndarray) -> None:
        entity.set_mass_shift(shift_per_env_link.astype(np.float32), links_idx_local=np.arange(entity.n_links))

    def _settle(self) -> None:
        hold = np.tile(self._franka_hold_qpos(), (self.n_envs, 1))
        for _ in range(self.cfg.settle_steps):
            self.bundle.franka.control_dofs_position(hold)
            self.bundle.scene.step()


# ---------------------------------------------------------------------------
# Batched grasp geometry helpers
# ---------------------------------------------------------------------------


def _topdown_quat_batched(yaw_deg: np.ndarray) -> np.ndarray:
    n = yaw_deg.shape[0]
    euler = np.zeros((n, 3))
    euler[:, 0] = 180.0
    euler[:, 2] = yaw_deg
    return euler_to_quat(euler)


def _obj_xy_yaw_batched(entity, n_envs: int) -> tuple[np.ndarray, np.ndarray]:
    pos = _to_np(entity.get_pos())  # (N,3)
    quat = _to_np(entity.get_quat())  # (N,4)
    yaw = np.array([float(quat_to_xyz(quat[i], degrees=True)[2]) for i in range(n_envs)])
    return pos, yaw


def _entity_aabb_batched(entity) -> np.ndarray:
    return _to_np(entity.get_AABB())  # (N,2,3)


def _grasp_hand_z_batched(entity, profile: GraspProfile, n_envs: int) -> np.ndarray:
    if profile.grasp_hand_z_override is not None:
        return np.full(n_envs, profile.grasp_hand_z_override)
    aabb = _entity_aabb_batched(entity)
    z_min, z_max = aabb[:, 0, 2], aabb[:, 1, 2]
    if not profile.center_align:
        return z_max + PALM_CLEARANCE
    center_z = 0.5 * (z_min + z_max)
    half_height = 0.5 * (z_max - z_min)
    fingertip_z = center_z - GRASP_CENTER_DROP_FRAC * half_height
    z_jaw_align = fingertip_z + profile.hand_to_fingertip
    z_top_clear = z_max + PALM_CLEARANCE
    return np.maximum(z_jaw_align, z_top_clear)


def _resolve_place_batched(bundle, place_target: PlaceTarget, n_envs: int) -> tuple[np.ndarray, np.ndarray, object]:
    if isinstance(place_target, str):
        ent = bundle.ycb[place_target]
        p = _to_np(ent.get_pos())  # (N,3)
        return p[:, :2], p[:, 2], ent
    x, y = place_target
    return np.tile(np.array([x, y]), (n_envs, 1)), np.full(n_envs, TABLE_TOP_Z), None


def check_success_batched(bundle, task: BatchTask, bowl_rim_margin: float = 0.01) -> np.ndarray:
    obj = bundle.ycb[task.pick_object]
    pick_pos = _to_np(obj.get_pos())  # (N,3)
    place_xy, place_ref_z, place_ent = _resolve_place_batched(bundle, task.place_target, task.n_envs)
    horizontal = np.linalg.norm(pick_pos[:, :2] - place_xy, axis=1)  # (N,)

    if place_ent is None:
        return (horizontal < task.success_tol) & (pick_pos[:, 2] > place_ref_z - 0.02)

    bowl_aabb = _entity_aabb_batched(place_ent)  # (N,2,3)
    rim_z = bowl_aabb[:, 1, 2]
    rim_radius = 0.5 * np.minimum(bowl_aabb[:, 1, 0] - bowl_aabb[:, 0, 0], bowl_aabb[:, 1, 1] - bowl_aabb[:, 0, 1])
    within_footprint = horizontal < np.minimum(task.success_tol, rim_radius)
    obj_bottom_z = _entity_aabb_batched(obj)[:, 0, 2]
    inside_bowl = obj_bottom_z < rim_z - bowl_rim_margin
    return within_footprint & inside_bowl


# ---------------------------------------------------------------------------
# Batched motion primitives (mirror sim_episode.py's _goto_*/_descend_vertical)
# ---------------------------------------------------------------------------


def _set_tail_batched(qpos, n_fingers: int, vec: np.ndarray, n_envs: int) -> None:
    tiled = np.tile(np.asarray(vec), (n_envs, 1))
    if hasattr(qpos, "detach"):
        qpos[:, -n_fingers:] = torch.as_tensor(tiled, dtype=qpos.dtype, device=qpos.device)
    else:
        qpos[:, -n_fingers:] = tiled


def _goto_plan_batched(bundle, rt: GripperRuntime, pos, quat, *, finger_vec, n_envs, num_waypoints=150, settle=20):
    hand = bundle.franka.get_link("hand")
    qpos = bundle.franka.inverse_kinematics(link=hand, pos=pos, quat=quat)
    _set_tail_batched(qpos, rt.n_fingers, finger_vec, n_envs)
    path = bundle.franka.plan_path(qpos_goal=qpos, num_waypoints=num_waypoints)
    for wp in path:
        bundle.franka.control_dofs_position(wp)
        bundle.scene.step()
    for _ in range(settle):
        bundle.franka.control_dofs_position(qpos)
        bundle.scene.step()
    return qpos


def _goto_direct_batched(bundle, rt: GripperRuntime, pos, quat, *, finger_cmd, n_envs, steps=120, close_force=None):
    hand = bundle.franka.get_link("hand")
    qpos = bundle.franka.inverse_kinematics(link=hand, pos=pos, quat=quat)
    arm = _to_np(qpos[:, :-rt.n_fingers])
    finger_pos_batched = np.tile(np.full(rt.n_fingers, finger_cmd), (n_envs, 1))
    force_batched = np.tile(np.full(rt.n_fingers, close_force), (n_envs, 1)) if close_force is not None else None
    for _ in range(steps):
        bundle.franka.control_dofs_position(arm, MOTORS_DOF)
        if force_batched is not None:
            bundle.franka.control_dofs_force(force_batched, rt.fingers_dof)
        else:
            bundle.franka.control_dofs_position(finger_pos_batched, rt.fingers_dof)
        bundle.scene.step()
    return qpos


def _goto_interp_batched(
    bundle, rt: GripperRuntime, pos, quat, *, finger_cmd, n_envs, close_force=None,
    max_dq=MOVE_MAX_DQ, min_steps=MOVE_MIN_STEPS, settle=MOVE_SETTLE_STEPS, tracker=None,
):
    hand = bundle.franka.get_link("hand")
    q_goal = bundle.franka.inverse_kinematics(link=hand, pos=pos, quat=quat)
    arm_goal = _to_np(q_goal[:, :-rt.n_fingers])  # (N,7)
    arm_start = _to_np(bundle.franka.get_dofs_position(MOTORS_DOF))  # (N,7)
    # Per-env step count would desync the batch (different envs finishing at different
    # times); use ONE shared step count sized for the largest per-env displacement, so
    # every env ramps at <= max_dq/step (some envs move slightly slower than their own
    # minimum, which only makes the move gentler, never rougher -- safe direction to
    # share a step count in).
    dist = float(np.max(np.abs(arm_goal - arm_start))) if arm_goal.size else 0.0
    n = max(min_steps, int(np.ceil(dist / max_dq))) if dist > 1e-9 else min_steps

    finger_pos_batched = np.tile(np.full(rt.n_fingers, finger_cmd), (n_envs, 1))
    force_batched = np.tile(np.full(rt.n_fingers, close_force), (n_envs, 1)) if close_force is not None else None

    def _cmd(arm):
        bundle.franka.control_dofs_position(arm, MOTORS_DOF)
        if force_batched is not None:
            bundle.franka.control_dofs_force(force_batched, rt.fingers_dof)
        else:
            bundle.franka.control_dofs_position(finger_pos_batched, rt.fingers_dof)
        bundle.scene.step()
        if tracker is not None:
            tracker.sample()

    for i in range(1, n + 1):
        _cmd(arm_start + (arm_goal - arm_start) * (i / n))
    for _ in range(settle):
        _cmd(arm_goal)
    return q_goal


def _descend_vertical_batched(bundle, rt: GripperRuntime, xy, z_from, z_to: np.ndarray, quat, *, finger_vec, n_envs, steps=80, settle=15):
    # xy: (x_per_env, y_per_env), each (N,) -- per-env approach column, since each
    # env's object sits at a different jittered xy. z_from is a scalar (pregrasp
    # height is the same phase start for all envs); z_to is per-env (each env's
    # object AABB gives a different grasp height).
    x_per_env, y_per_env = xy
    qpos = None
    for t in np.linspace(0.0, 1.0, steps):
        z = z_from + (z_to - z_from) * t  # (N,)
        pos = np.stack([x_per_env, y_per_env, z], axis=1)
        hand = bundle.franka.get_link("hand")
        qpos = bundle.franka.inverse_kinematics(link=hand, pos=pos, quat=quat)
        _set_tail_batched(qpos, rt.n_fingers, finger_vec, n_envs)
        bundle.franka.control_dofs_position(qpos)
        bundle.scene.step()
    for _ in range(settle):
        bundle.franka.control_dofs_position(qpos)
        bundle.scene.step()
    return qpos


def _settle_batched(bundle, rt: GripperRuntime, n_envs: int, steps: int) -> None:
    arm, fingers = np.array(FRANKA_QPOS[:7]), np.array(FRANKA_QPOS[7:])
    hold = np.tile(np.concatenate([arm, np.full(rt.n_fingers, fingers[-1])]), (n_envs, 1))
    for _ in range(steps):
        bundle.franka.control_dofs_position(hold)
        bundle.scene.step()


class _BatchMetricsTracker:
    """Per-env counterpart of sim_episode._MetricsTracker -- (N,) arrays throughout."""

    def __init__(self, bundle, pick_entity, n_envs: int):
        self.bundle = bundle
        self.pick_entity = pick_entity
        self.n_envs = n_envs
        self.peak_force = np.zeros(n_envs)
        self.n_steps = 0
        self.n_contact_steps = np.zeros(n_envs)
        self.max_slip = np.zeros(n_envs)
        self._ref_xy = None

    def sample(self) -> None:
        self.n_steps += 1
        contacts = self.pick_entity.get_contacts(with_entity=self.bundle.franka)
        force_b = contacts.get("force_b")  # (N, n_contacts, 3)
        valid = contacts.get("valid_mask")  # (N, n_contacts)
        if force_b is not None:
            force_b = _to_np(force_b)
            mags = np.linalg.norm(force_b, axis=-1)  # (N, n_contacts)
            if valid is not None:
                valid = _to_np(valid).astype(bool)
                mags = np.where(valid, mags, 0.0)
                any_contact = valid.any(axis=1)
            else:
                any_contact = mags.sum(axis=1) > 0
            per_env_peak = mags.max(axis=1) if mags.size else np.zeros(self.n_envs)
            self.peak_force = np.maximum(self.peak_force, per_env_peak)
            self.n_contact_steps += any_contact.astype(float)

        hand_pos = _to_np(self.bundle.franka.get_link("hand").get_pos())[:, :2]  # (N,2)
        obj_pos = _to_np(self.pick_entity.get_pos())[:, :2]  # (N,2)
        rel_xy = obj_pos - hand_pos
        if self._ref_xy is None:
            self._ref_xy = rel_xy
        slip = np.linalg.norm(rel_xy - self._ref_xy, axis=1)
        self.max_slip = np.maximum(self.max_slip, slip)

    def finalize(self) -> tuple[np.ndarray, np.ndarray, np.ndarray, int]:
        uptime = (self.n_contact_steps / self.n_steps) if self.n_steps else np.zeros(self.n_envs)
        return self.peak_force, uptime, self.max_slip, self.n_steps


@dataclass
class BatchEpisodeMetrics:
    success: np.ndarray  # (N,) bool
    peak_contact_force: np.ndarray  # (N,) N
    contact_uptime_frac: np.ndarray  # (N,)
    max_slip: np.ndarray  # (N,) m
    n_metric_steps: int


def run_pick_place_batched(bundle, rt: GripperRuntime, task: BatchTask, profile: GraspProfile) -> BatchEpisodeMetrics:
    n_envs = task.n_envs
    pick_entity = bundle.ycb[task.pick_object]
    tracker = _BatchMetricsTracker(bundle, pick_entity, n_envs)

    _settle_batched(bundle, rt, n_envs, 60)

    obj_pos, obj_yaw = _obj_xy_yaw_batched(pick_entity, n_envs)  # (N,3), (N,)
    grasp_quat = _topdown_quat_batched(obj_yaw + profile.yaw_offset)  # (N,4)

    pregrasp = obj_pos.copy()
    pregrasp[:, 2] += PREGRASP_CLEARANCE
    _goto_plan_batched(bundle, rt, pregrasp, grasp_quat, finger_vec=rt.open_vec(), n_envs=n_envs)

    grasp_z = _grasp_hand_z_batched(pick_entity, profile, n_envs)  # (N,)
    # xy shared across the descent phase (approach column is per-env via obj_pos, but
    # _descend_vertical_batched takes a single (x,y) pair -- generalize to per-env xy):
    _descend_vertical_batched(
        bundle, rt, (obj_pos[:, 0], obj_pos[:, 1]), pregrasp[:, 2], grasp_z, grasp_quat,
        finger_vec=rt.open_vec(), n_envs=n_envs,
    )
    grasp = np.stack([obj_pos[:, 0], obj_pos[:, 1], grasp_z], axis=1)

    _goto_direct_batched(bundle, rt, grasp, grasp_quat, finger_cmd=0.0, n_envs=n_envs, steps=100, close_force=profile.close_force)

    lift = grasp.copy()
    lift[:, 2] = LIFT_HAND_Z
    _goto_interp_batched(bundle, rt, lift, grasp_quat, finger_cmd=0.0, n_envs=n_envs, close_force=profile.close_force, tracker=tracker)

    place_xy, place_ref_z, _ = _resolve_place_batched(bundle, task.place_target, n_envs)
    above = np.concatenate([place_xy, (place_ref_z + PLACE_HAND_Z_ABOVE_TARGET)[:, None]], axis=1)
    _goto_interp_batched(bundle, rt, above, grasp_quat, finger_cmd=0.0, n_envs=n_envs, close_force=profile.close_force, tracker=tracker)

    _goto_direct_batched(bundle, rt, above, grasp_quat, finger_cmd=float(rt.finger_open_travel), n_envs=n_envs, steps=80)

    retreat = np.concatenate([place_xy, np.full((n_envs, 1), RETREAT_HAND_Z)], axis=1)
    _goto_direct_batched(bundle, rt, retreat, grasp_quat, finger_cmd=float(rt.finger_open_travel), n_envs=n_envs, steps=80)
    _settle_batched(bundle, rt, n_envs, 60)

    success = check_success_batched(bundle, task)
    peak_force, uptime, max_slip, n_steps = tracker.finalize()
    return BatchEpisodeMetrics(success=success, peak_contact_force=peak_force, contact_uptime_frac=uptime, max_slip=max_slip, n_metric_steps=n_steps)
