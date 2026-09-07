"""Diagnostic (not part of the frozen pipeline): per-finger contact-onset timing,
Genesis side. Companion to mujoco_repl/finger_diag.py -- same measurement, same
methodology, so the two are directly comparable.

Reuses sim_episode.py's existing helpers (_settle, _obj_xy_yaw, _topdown_quat,
_goto_plan, _grasp_hand_z, _descend_vertical, _goto_interp, check_success) as-is,
and does NOT modify sim_episode.py -- this is instrumentation added in a new file
alongside the frozen controller, not an edit to it. The only phase without built-in
tracker support is the close phase (`_goto_direct` takes no tracker argument), so
`_goto_direct_diag` below duplicates its control logic exactly (same
control_dofs_position/force + scene.step() calls) and adds per-step sampling --
no control decision changes, only added observation.

get_contacts()'s returned 'link_a'/'link_b' (global link indices) is what makes
per-finger attribution possible: each finger's link idx (bundle.franka.get_link(name).idx)
is checked against both sides of every object<->franka contact pair.
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT.parent) not in sys.path:
    sys.path.insert(0, str(_ROOT.parent))
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import numpy as np  # noqa: E402
import torch  # noqa: E402

from sim_episode import (  # noqa: E402
    GripperRuntime, MOTORS_DOF, PREGRASP_CLEARANCE, LIFT_HAND_Z, PLACE_HAND_Z_ABOVE_TARGET, RETREAT_HAND_Z,
    GraspProfile, EpisodeMetrics, _settle, _obj_xy_yaw, _topdown_quat, _goto_plan, _grasp_hand_z,
    _descend_vertical, _goto_interp, _to_numpy,
)
from grasp_demo import TaskSpec, _resolve_place, check_success  # noqa: E402


class PerFingerContactTracker:
    """Genesis-side counterpart to finger_diag.PerFingerContactTracker -- same
    fields, same semantics, so results are directly comparable across engines."""

    def __init__(self, bundle, pick_entity, finger_names: list[str]):
        self.bundle = bundle
        self.pick_entity = pick_entity
        self.finger_names = finger_names
        self.finger_link_idx = {n: bundle.franka.get_link(n).idx for n in finger_names}
        self.onset_step: dict[str, int | None] = {n: None for n in finger_names}
        self.contact_steps: dict[str, int] = {n: 0 for n in finger_names}
        self.step_idx = 0

    def sample(self) -> None:
        contacts = self.pick_entity.get_contacts(with_entity=self.bundle.franka)
        link_a, link_b = contacts.get("link_a"), contacts.get("link_b")
        touching_now = set()
        if link_a is not None and len(link_a) > 0:
            la = link_a.detach().cpu().numpy() if hasattr(link_a, "detach") else np.asarray(link_a)
            lb = link_b.detach().cpu().numpy() if hasattr(link_b, "detach") else np.asarray(link_b)
            for n, idx in self.finger_link_idx.items():
                if np.any(la == idx) or np.any(lb == idx):
                    touching_now.add(n)
        for n in touching_now:
            self.contact_steps[n] += 1
            if self.onset_step[n] is None:
                self.onset_step[n] = self.step_idx
        self.step_idx += 1

    def summary(self) -> dict:
        onsets = [v for v in self.onset_step.values() if v is not None]
        spread = (max(onsets) - min(onsets)) if len(onsets) >= 2 else (0 if onsets else None)
        return {
            "onset_step": dict(self.onset_step),
            "contact_steps": dict(self.contact_steps),
            "n_fingers_ever_engaged": len(onsets),
            "n_fingers_total": len(self.finger_names),
            "onset_spread_steps": spread,
        }


def _goto_direct_diag(bundle, rt: GripperRuntime, pos, quat, *, finger_cmd, steps=120, close_force=None, tracker=None):
    """Exact duplicate of sim_episode._goto_direct's control logic, + tracker.sample()
    per step -- see module docstring."""
    from grasp_demo import _ik

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
        if tracker is not None:
            tracker.sample()
    return qpos


def run_pick_place_diag(
    bundle, rt: GripperRuntime, task: TaskSpec, profile: GraspProfile, finger_names: list[str],
) -> dict:
    pick_entity = bundle.ycb[task.pick_object]
    tracker = PerFingerContactTracker(bundle, pick_entity, finger_names)

    _settle(bundle, rt, 60)

    obj_pos, obj_yaw = _obj_xy_yaw(pick_entity)
    grasp_quat = _topdown_quat(obj_yaw + profile.yaw_offset)

    pregrasp = np.array([obj_pos[0], obj_pos[1], obj_pos[2] + PREGRASP_CLEARANCE])
    _goto_plan(bundle, rt, pregrasp, grasp_quat, finger_vec=rt.open_vec())

    grasp_z = _grasp_hand_z(pick_entity, profile)
    _descend_vertical(bundle, rt, (obj_pos[0], obj_pos[1]), pregrasp[2], grasp_z, grasp_quat, finger_vec=rt.open_vec())
    grasp = np.array([obj_pos[0], obj_pos[1], grasp_z])

    _goto_direct_diag(bundle, rt, grasp, grasp_quat, finger_cmd=0.0, steps=100, close_force=profile.close_force, tracker=tracker)

    lift = np.array([grasp[0], grasp[1], LIFT_HAND_Z])
    _goto_interp(bundle, rt, lift, grasp_quat, finger_cmd=0.0, close_force=profile.close_force, tracker=tracker)

    place_xy, place_ref_z, _ = _resolve_place(bundle, task.place_target)
    above = np.array([place_xy[0], place_xy[1], place_ref_z + PLACE_HAND_Z_ABOVE_TARGET])
    _goto_interp(bundle, rt, above, grasp_quat, finger_cmd=0.0, close_force=profile.close_force, tracker=tracker)

    _goto_direct_diag(bundle, rt, above, grasp_quat, finger_cmd=float(rt.finger_open_travel), steps=80)

    retreat = np.array([place_xy[0], place_xy[1], RETREAT_HAND_Z])
    _goto_direct_diag(bundle, rt, retreat, grasp_quat, finger_cmd=float(rt.finger_open_travel), steps=80)
    _settle(bundle, rt, 60)

    success = check_success(bundle, task)
    result = {"success": bool(success)}
    result.update(tracker.summary())
    return result
