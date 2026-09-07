"""Session 8, Part B: test the contact-geometry-alignment hypothesis directly.

ycb_generalization_findings.md S3 noticed a pattern but explicitly flagged it
as unconfirmed: winner-favored objects (round/curved: tomato_soup_can,
tennis_ball, pear) vs baseline-favored objects (flat-faced: rubik's cube,
large_clamp, scissors) -- hypothesized as a contact-area/alignment effect
(curved fingers meet round surfaces flush, meet flat surfaces at a
point/edge). This module tests that directly rather than leaving it as a
read-off-the-data guess.

What Genesis's contact API actually exposes (checked before building this,
per the brief's own "first step" instruction): get_contacts() returns
position, normal, force per contact -- NOT a contact-area field. Like most
rigid-body simulators (MuJoCo included, see cross_simulator_findings.md),
Genesis uses point contacts, not finite contact patches, so literal "contact
area" isn't available. Two proxies built from what IS available:
  1. n_contact_points: how many simultaneous discrete contact points exist
     between a given finger and the object, at a sampled instant -- multiple
     nearby points approximate a patch; a single point is a true point/edge
     contact.
  2. normal_spread: the circular spread (1 - mean resultant length of the
     unit contact normals) across those points -- low spread means the
     normals all point the same way (flush contact against a locally flat
     region); high spread means they disagree (contact wrapping around an
     edge or corner, or several unrelated small contacts).
Both are reported as proxies, not literal area/alignment, throughout.
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

from sim_episode import (  # noqa: E402
    GripperRuntime, MOTORS_DOF, PREGRASP_CLEARANCE, LIFT_HAND_Z, PLACE_HAND_Z_ABOVE_TARGET, RETREAT_HAND_Z,
    GraspProfile, _settle, _obj_xy_yaw, _topdown_quat, _goto_plan, _grasp_hand_z, _descend_vertical, _goto_interp, _to_numpy,
)
from grasp_demo import TaskSpec, _resolve_place, check_success, _ik  # noqa: E402


def _sample_contact_geometry(bundle, pick_entity, finger_link_idx: dict[str, int]) -> dict:
    """Snapshot per-finger contact point count + normal spread, right now."""
    contacts = pick_entity.get_contacts(with_entity=bundle.franka)
    link_a, link_b = contacts.get("link_a"), contacts.get("link_b")
    normals = contacts.get("normal")
    if link_a is None or len(link_a) == 0:
        return {n: {"n_points": 0, "normal_spread": None} for n in finger_link_idx}

    la = link_a.detach().cpu().numpy() if hasattr(link_a, "detach") else np.asarray(link_a)
    lb = link_b.detach().cpu().numpy() if hasattr(link_b, "detach") else np.asarray(link_b)
    nrm = normals.detach().cpu().numpy() if hasattr(normals, "detach") else np.asarray(normals)

    out = {}
    for name, idx in finger_link_idx.items():
        mask = (la == idx) | (lb == idx)
        pts_normals = nrm[mask]
        n_points = int(mask.sum())
        if n_points == 0:
            out[name] = {"n_points": 0, "normal_spread": None}
            continue
        unit = pts_normals / (np.linalg.norm(pts_normals, axis=-1, keepdims=True) + 1e-9)
        mean_vec = unit.mean(axis=0)
        resultant_length = float(np.linalg.norm(mean_vec))  # 1.0 = all parallel, 0.0 = maximally scattered
        out[name] = {"n_points": n_points, "normal_spread": 1.0 - resultant_length}
    return out


def _goto_direct_sampling(bundle, rt: GripperRuntime, pos, quat, *, finger_cmd, steps=120, close_force=None,
                           pick_entity=None, finger_link_idx=None, geometry_samples=None):
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
        if geometry_samples is not None:
            geometry_samples.append(_sample_contact_geometry(bundle, pick_entity, finger_link_idx))
    return qpos


def run_pick_place_geometry(bundle, rt: GripperRuntime, task: TaskSpec, profile: GraspProfile, finger_names: list[str]) -> dict:
    pick_entity = bundle.ycb[task.pick_object]
    finger_link_idx = {n: bundle.franka.get_link(n).idx for n in finger_names}

    _settle(bundle, rt, 60)

    obj_pos, obj_yaw = _obj_xy_yaw(pick_entity)
    grasp_quat = _topdown_quat(obj_yaw + profile.yaw_offset)

    pregrasp = np.array([obj_pos[0], obj_pos[1], obj_pos[2] + PREGRASP_CLEARANCE])
    _goto_plan(bundle, rt, pregrasp, grasp_quat, finger_vec=rt.open_vec())

    grasp_z = _grasp_hand_z(pick_entity, profile)
    _descend_vertical(bundle, rt, (obj_pos[0], obj_pos[1]), pregrasp[2], grasp_z, grasp_quat, finger_vec=rt.open_vec())
    grasp = np.array([obj_pos[0], obj_pos[1], grasp_z])

    # Sample contact geometry densely during the CLOSE phase (this is where a
    # flush-vs-point-contact difference should be most visible -- the grip is
    # actively forming) and the start of LIFT (first load-bearing moment).
    geometry_samples: list[dict] = []
    _goto_direct_sampling(
        bundle, rt, grasp, grasp_quat, finger_cmd=0.0, steps=100, close_force=profile.close_force,
        pick_entity=pick_entity, finger_link_idx=finger_link_idx, geometry_samples=geometry_samples,
    )

    lift = np.array([grasp[0], grasp[1], LIFT_HAND_Z])
    _goto_interp(bundle, rt, lift, grasp_quat, finger_cmd=0.0, close_force=profile.close_force)

    place_xy, place_ref_z, _ = _resolve_place(bundle, task.place_target)
    above = np.array([place_xy[0], place_xy[1], place_ref_z + PLACE_HAND_Z_ABOVE_TARGET])
    _goto_interp(bundle, rt, above, grasp_quat, finger_cmd=0.0, close_force=profile.close_force)

    _goto_direct_sampling(bundle, rt, above, grasp_quat, finger_cmd=float(rt.finger_open_travel), steps=80)

    retreat = np.array([place_xy[0], place_xy[1], RETREAT_HAND_Z])
    _goto_direct_sampling(bundle, rt, retreat, grasp_quat, finger_cmd=float(rt.finger_open_travel), steps=80)
    _settle(bundle, rt, 60)

    success = check_success(bundle, task)

    # Aggregate over the close-phase samples where at least one finger touched:
    # mean n_points and mean normal_spread per finger, over steps with contact.
    per_finger_points = {n: [] for n in finger_names}
    per_finger_spread = {n: [] for n in finger_names}
    for snap in geometry_samples:
        for n in finger_names:
            if snap[n]["n_points"] > 0:
                per_finger_points[n].append(snap[n]["n_points"])
                per_finger_spread[n].append(snap[n]["normal_spread"])

    mean_points = float(np.mean([v for lst in per_finger_points.values() for v in lst])) if any(per_finger_points.values()) else 0.0
    mean_spread = float(np.mean([v for lst in per_finger_spread.values() for v in lst])) if any(per_finger_spread.values()) else None
    frac_steps_with_contact = float(np.mean([any(snap[n]["n_points"] > 0 for n in finger_names) for snap in geometry_samples])) if geometry_samples else 0.0

    return {
        "success": bool(success), "mean_contact_points": mean_points,
        "mean_normal_spread": mean_spread, "frac_close_steps_with_contact": frac_steps_with_contact,
    }
