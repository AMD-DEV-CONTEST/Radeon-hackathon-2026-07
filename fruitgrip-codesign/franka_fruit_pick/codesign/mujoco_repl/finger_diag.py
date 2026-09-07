"""Diagnostic (not part of the frozen pipeline): per-finger contact-onset timing.

Session 7's confirmation eval found the 3-finger winner underperforming the
2-finger baseline in MuJoCo -- the opposite direction from Genesis. The working
hypothesis (cross_simulator_findings.md S5) was that the winner's failures are
partial/delayed multi-finger contact: fingers not engaging simultaneously, so a
"3 contacts resist rotation" advantage never actually materializes. That
hypothesis was inferred from aggregate uptime/slip numbers, not measured directly
-- this module adds the direct measurement (per-finger, per-step contact state)
so it can be checked, and the equivalent instrumentation is added Genesis-side
(finger_contact_diag.py) for a same-methodology comparison.

Deliberately a parallel/new function, not an edit to controller.run_pick_place:
this is instrumentation-only (adds observation, changes no control decision), and
keeping it out of the frozen eval path means the already-validated
confirmation_eval_mj.py results are untouched by this diagnostic.
"""
from __future__ import annotations

import numpy as np
import mujoco

from controller import (
    MjSceneHandles, _grasp_hand_z, _interp_move, _set_finger_positions, _step,
    PREGRASP_CLEARANCE, SAFE_APPROACH_Z, LIFT_HAND_Z, PLACE_HAND_Z_ABOVE_TARGET, RETREAT_HAND_Z,
)


class PerFingerContactTracker:
    """Records, per finger BODY, the step index of first contact with the object
    (None if never), plus total contact-steps per finger -- everything needed to
    answer "did the fingers engage together, or sequentially/asymmetrically?"
    Sampled every step from the START of the close phase through end of transport
    (broader window than ContactTracker's lift+transport-only, since onset itself
    typically happens during close)."""

    def __init__(self, model, data, obj_body_id: int, n_fingers: int):
        self.model = model
        self.data = data
        self.obj_body_id = obj_body_id
        finger_names = ["left_finger", "right_finger"] if n_fingers == 2 else [f"finger_{i}" for i in range(n_fingers)]
        self.finger_body_ids = [mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, n) for n in finger_names]
        self.finger_names = finger_names
        self.onset_step: dict[str, int | None] = {n: None for n in finger_names}
        self.contact_steps: dict[str, int] = {n: 0 for n in finger_names}
        self.step_idx = 0

    def sample(self) -> None:
        geom_bodyid = self.model.geom_bodyid
        touching_now = set()
        for i in range(self.data.ncon):
            c = self.data.contact[i]
            b1, b2 = geom_bodyid[c.geom1], geom_bodyid[c.geom2]
            if self.obj_body_id not in (b1, b2):
                continue
            other = b2 if b1 == self.obj_body_id else b1
            if other in self.finger_body_ids:
                fi = self.finger_body_ids.index(other)
                touching_now.add(self.finger_names[fi])
        for n in touching_now:
            self.contact_steps[n] += 1
            if self.onset_step[n] is None:
                self.onset_step[n] = self.step_idx
        self.step_idx += 1

    def summary(self) -> dict:
        onsets = [v for v in self.onset_step.values() if v is not None]
        n_engaged = len(onsets)
        spread = (max(onsets) - min(onsets)) if len(onsets) >= 2 else (0 if onsets else None)
        return {
            "onset_step": dict(self.onset_step),
            "contact_steps": dict(self.contact_steps),
            "n_fingers_ever_engaged": n_engaged,
            "n_fingers_total": len(self.finger_names),
            "onset_spread_steps": spread,
        }


def run_pick_place_diag(
    model, data, *, obj_name: str, place_body_name: str, n_fingers: int, aperture: float,
    hand_to_fingertip: float, close_force: float, yaw_offset_deg: float, center_align: bool,
    success_tol: float = 0.06,
) -> dict:
    """Exact phase sequence and control calls as controller.run_pick_place -- only
    addition is sampling a PerFingerContactTracker from the close phase onward
    (controller.run_pick_place's own ContactTracker only samples lift+transport)."""
    handles = MjSceneHandles(model, n_fingers)
    obj_body_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, obj_name)
    place_body_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, place_body_name)

    home = np.array([0.0, -0.3, 0.0, -2.0, 0.0, 1.7, 0.79])
    open_travel = max(aperture / 2 - 0.002, 0.002)

    def settle(steps: int) -> None:
        for _ in range(steps):
            _set_finger_positions(data, handles, open_travel)
            _step(model, data, handles, home)

    settle(60)

    obj_pos = data.xpos[obj_body_id].copy()
    obj_quat = data.xquat[obj_body_id].copy()
    obj_yaw = float(np.arctan2(2 * (obj_quat[0] * obj_quat[3] + obj_quat[1] * obj_quat[2]), 1 - 2 * (obj_quat[2] ** 2 + obj_quat[3] ** 2)))
    grasp_yaw = obj_yaw + np.radians(yaw_offset_deg)
    half_yaw = grasp_yaw / 2
    grasp_quat = np.array([0.0, np.cos(half_yaw), np.sin(half_yaw), 0.0])

    safe_pos = np.array([obj_pos[0], obj_pos[1], SAFE_APPROACH_Z])
    _interp_move(model, data, handles, safe_pos, grasp_quat, finger_cmd=open_travel, n_steps=80)

    pregrasp_pos = obj_pos + np.array([0, 0, PREGRASP_CLEARANCE])
    _interp_move(model, data, handles, pregrasp_pos, grasp_quat, finger_cmd=open_travel, n_steps=60)

    grasp_z = _grasp_hand_z(model, data, obj_body_id, center_align=center_align, hand_to_fingertip=hand_to_fingertip)
    grasp_pos = np.array([obj_pos[0], obj_pos[1], grasp_z])
    _interp_move(model, data, handles, grasp_pos, grasp_quat, finger_cmd=open_travel, n_steps=60)

    finger_tracker = PerFingerContactTracker(model, data, obj_body_id, n_fingers)
    _interp_move(model, data, handles, grasp_pos, grasp_quat, close_force=close_force, n_steps=80, tracker=finger_tracker)

    lift_pos = np.array([grasp_pos[0], grasp_pos[1], LIFT_HAND_Z])
    _interp_move(model, data, handles, lift_pos, grasp_quat, close_force=close_force, tracker=finger_tracker)

    place_pos = data.xpos[place_body_id].copy()
    above_pos = np.array([place_pos[0], place_pos[1], place_pos[2] + PLACE_HAND_Z_ABOVE_TARGET])
    _interp_move(model, data, handles, above_pos, grasp_quat, close_force=close_force, tracker=finger_tracker)

    _interp_move(model, data, handles, above_pos, grasp_quat, finger_cmd=open_travel, n_steps=50)

    retreat_pos = np.array([place_pos[0], place_pos[1], RETREAT_HAND_Z])
    _interp_move(model, data, handles, retreat_pos, grasp_quat, finger_cmd=open_travel, n_steps=50)
    settle(60)

    from controller import _entity_aabb
    final_obj_pos = data.xpos[obj_body_id].copy()
    horiz = float(np.linalg.norm(final_obj_pos[:2] - place_pos[:2]))
    bowl_aabb_min, bowl_aabb_max = _entity_aabb(model, data, place_body_id)
    rim_z = bowl_aabb_max[2]
    rim_radius = 0.5 * min(bowl_aabb_max[0] - bowl_aabb_min[0], bowl_aabb_max[1] - bowl_aabb_min[1])
    within_footprint = horiz < min(success_tol, rim_radius)
    obj_aabb_min, _ = _entity_aabb(model, data, obj_body_id)
    inside_bowl = obj_aabb_min[2] < rim_z - 0.01
    success = bool(within_footprint and inside_bowl)

    result = {"success": success}
    result.update(finger_tracker.summary())
    return result
