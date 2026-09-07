"""Session 7: MuJoCo port of sim_episode.py's scripted pick-and-place controller.

Mirrors the Genesis version's phase structure (settle -> pregrasp -> descend ->
grasp -> lift -> transport -> release -> retreat -> settle -> check_success)
exactly, including the AABB-based grasp-height formula (_grasp_hand_z) and the
per-finger direct position/force control (bypassing the tendon actuator, matching
gripper_gen.py's own documented reason Genesis does the same).

Documented deviations from the Genesis version (both are controller-implementation
choices, not physics, and neither was chosen to make results agree with Genesis --
see cross_simulator_findings.md):
  1. Pregrasp clearance is 0.10m here vs Genesis's 0.18m -- this MuJoCo IK solver
     (damped least-squares, no motion planner) converges to sub-mm accuracy at 0.10m
     clearance but has a genuine position/orientation conflict at 0.18m for a strict
     top-down grasp (confirmed: position-only IK converges to ~1e-16 error at the
     same point, so this is a real kinematic margin difference between IK approaches,
     not a solver bug -- see ik.py's docstring).
  2. The pregrasp approach uses straight joint-space interpolation, not Genesis's
     collision-aware path planner (`plan_path()`, no MuJoCo equivalent used here).
"""
from __future__ import annotations

import numpy as np
import mujoco

from ik import solve_ik

PREGRASP_CLEARANCE = 0.10  # m -- see module docstring, deviation #1
SAFE_APPROACH_Z = 1.0  # m, world frame -- intermediate waypoint height for the 2-stage approach (see run_pick_place)
LIFT_HAND_Z = 0.75 + 0.30
RETREAT_HAND_Z = 0.75 + 0.35
PLACE_HAND_Z_ABOVE_TARGET = 0.16
GRASP_CENTER_DROP_FRAC = 0.45
PALM_CLEARANCE = 0.02
HAND_TO_FINGERTIP = 0.105  # co-adapted per design below via hand_to_fingertip_z
MOVE_MAX_DQ = 0.006
MOVE_MIN_STEPS = 40
MOVE_SETTLE_STEPS = 15


class MjSceneHandles:
    def __init__(self, model, n_fingers: int):
        self.model = model
        self.n_fingers = n_fingers
        self.hand_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, "hand")
        self.finger_joint_ids = [mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, f"finger_joint{i+1}") for i in range(n_fingers)]
        self.finger_dof_adr = [model.jnt_dofadr[j] for j in self.finger_joint_ids]
        self.finger_qpos_adr = [model.jnt_qposadr[j] for j in self.finger_joint_ids]
        self.finger_act_ids = [mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_ACTUATOR, f"finger_joint{i+1}_pos") for i in range(n_fingers)]
        self.arm_act_ids = list(range(7))  # actuator1..7 are indices 0..6 by construction order


def _entity_aabb(model, data, body_id: int) -> tuple[np.ndarray, np.ndarray]:
    """World-frame AABB of a body's mesh geoms (min, max).

    NOT geom_rbound (bounding-SPHERE radius applied in all 3 axes) -- that badly
    over-estimates a tight AABB for any non-spherical mesh (confirmed: inflated the
    lemon's true ~6cm size to ~10.7cm). Also NOT "rotate the local bbox's 8 corners,
    then take min/max" -- MuJoCo's mesh compiler re-orients mesh vertices into their
    principal-inertia frame internally, so a mesh's local bounding box is not
    generally world/body-axis-aligned; rotating just its 8 corners into world space
    and re-bounding overestimates the true AABB the same way rotating any box and
    re-bounding it does (confirmed: this approach gave the lemon a ~10.4x10.5x8.0cm
    world AABB, even larger than the geom_rbound version). Instead, transform ALL of
    the mesh's vertices (not just 8 local-box corners) into world space and take
    min/max directly -- more points but geometrically exact regardless of the mesh's
    internal local-frame orientation, matching what Genesis's get_AABB() provides.
    """
    geom_ids = [i for i in range(model.ngeom) if model.geom_bodyid[i] == body_id]
    mins, maxs = [], []
    for g in geom_ids:
        mesh_id = model.geom_dataid[g]
        if mesh_id < 0:
            c, r = data.geom_xpos[g], model.geom_rbound[g]
            mins.append(c - r)
            maxs.append(c + r)
            continue
        vstart = model.mesh_vertadr[mesh_id]
        vcount = model.mesh_vertnum[mesh_id]
        local_verts = model.mesh_vert[vstart:vstart + vcount]  # (N,3), mesh-local frame
        xmat = data.geom_xmat[g].reshape(3, 3)
        world_verts = local_verts @ xmat.T + data.geom_xpos[g]
        mins.append(world_verts.min(axis=0))
        maxs.append(world_verts.max(axis=0))
    return np.min(mins, axis=0), np.max(maxs, axis=0)


def _grasp_hand_z(model, data, body_id: int, *, center_align: bool, hand_to_fingertip: float) -> float:
    """Documented controller-implementation deviation #3 (see module docstring):
    Genesis's non-center-align branch (sim_episode._grasp_hand_z, elongated objects
    like the banana) returns `z_max + PALM_CLEARANCE` as the HAND target directly,
    with no `hand_to_fingertip` term -- unlike its own center-align branch, which
    adds that offset via `z_jaw_align`. Ported verbatim, this commanded the
    fingertip to ~10cm BELOW the object's top surface -- for the banana (only
    ~3.8cm above the table), that lands ~6cm INTO the table, and MuJoCo's stiff
    contact model blocks the descent outright (confirmed via contact trace:
    "left_finger/right_finger <-> table" during descend). A first fix attempt
    (adding hand_to_fingertip on top of z_max+PALM_CLEARANCE) overshot the other
    way -- it puts the FINGERTIP only PALM_CLEARANCE above the object's top, i.e.
    hovering just above it rather than descending far enough to actually bracket
    its cross-section, so the close phase grips empty air (confirmed: 0N contact
    force, finger qpos closes to ~0 with the banana untouched). Both branches now
    use the SAME "dip partway from center" fingertip target the center-align branch
    already used (GRASP_CENTER_DROP_FRAC=0.45 of half-height below the object's
    vertical center) -- physically, wanting the fingertips to bracket the object's
    cross-section near its middle rather than its very top is not specific to round
    objects, and this is the target that was already validated (lemon/plum: 100%
    contact uptime, sub-cm slip). `center_align` continues to affect nothing else
    here -- Genesis's own use of it is confined to this height formula (its
    yaw_offset/XY handling is orientation-only, ported separately in run_pick_place).
    """
    aabb_min, aabb_max = _entity_aabb(model, data, body_id)
    z_min, z_max = aabb_min[2], aabb_max[2]
    center_z = 0.5 * (z_min + z_max)
    half_height = 0.5 * (z_max - z_min)
    fingertip_z = center_z - GRASP_CENTER_DROP_FRAC * half_height
    z_jaw_align = fingertip_z + hand_to_fingertip
    z_top_clear = z_max + PALM_CLEARANCE
    return max(z_jaw_align, z_top_clear)


def _set_finger_positions(data, handles: MjSceneHandles, target: float) -> None:
    # qfrc_applied persists across mj_step calls until explicitly zeroed -- if a prior
    # phase used _set_finger_force (e.g. the -12N grasp-close force), that force stays
    # applied forever unless cleared here, fighting this position command indefinitely
    # (confirmed: this is why "release" never actually opened the fingers -- the
    # grasp's closing force was still active the whole time).
    _clear_finger_force(data, handles)
    for act_id in handles.finger_act_ids:
        data.ctrl[act_id] = target


def _set_finger_force(data, handles: MjSceneHandles, force: float) -> None:
    # Hold the position-actuator target at the CURRENT joint position (not e.g. 0/
    # closed) so it contributes ~zero additional force and the injected qfrc_applied
    # is the dominant driver -- mirrors Genesis's control_dofs_force, which replaces
    # position control outright rather than adding a second force source on top.
    for dof_adr, qpos_adr, act_id in zip(handles.finger_dof_adr, handles.finger_qpos_adr, handles.finger_act_ids):
        data.qfrc_applied[dof_adr] = force
        data.ctrl[act_id] = data.qpos[qpos_adr]


def _clear_finger_force(data, handles: MjSceneHandles) -> None:
    for dof_adr in handles.finger_dof_adr:
        data.qfrc_applied[dof_adr] = 0.0


def _step(model, data, handles: MjSceneHandles, arm_target: np.ndarray | None) -> None:
    if arm_target is not None:
        data.ctrl[:7] = arm_target
    mujoco.mj_step(model, data)


def _interp_move(model, data, handles: MjSceneHandles, target_pos, target_quat, *, finger_cmd=None, close_force=None,
                  n_steps=MOVE_MIN_STEPS, settle=MOVE_SETTLE_STEPS, tracker=None) -> None:
    q_goal = solve_ik(model, data.qpos.copy(), handles.hand_id, np.asarray(target_pos), np.asarray(target_quat))
    arm_goal = q_goal[:7]
    arm_start = data.qpos[:7].copy()
    dist = float(np.max(np.abs(arm_goal - arm_start))) if arm_goal.size else 0.0
    n = max(n_steps, int(np.ceil(dist / MOVE_MAX_DQ))) if dist > 1e-9 else n_steps

    for i in range(1, n + 1):
        arm_cmd = arm_start + (arm_goal - arm_start) * (i / n)
        if close_force is not None:
            _set_finger_force(data, handles, close_force)
        elif finger_cmd is not None:
            _set_finger_positions(data, handles, finger_cmd)
        _step(model, data, handles, arm_cmd)
        if tracker is not None:
            tracker.sample()
    for _ in range(settle):
        if close_force is not None:
            _set_finger_force(data, handles, close_force)
        elif finger_cmd is not None:
            _set_finger_positions(data, handles, finger_cmd)
        _step(model, data, handles, arm_goal)
        if tracker is not None:
            tracker.sample()


class ContactTracker:
    def __init__(self, model, data, obj_body_id: int, hand_body_id: int, n_fingers: int):
        self.model = model
        self.data = data
        self.obj_body_id = obj_body_id
        # Mirrors gripper_gen.GripperParams.body_names() exactly: 2-finger designs
        # keep the stock left_finger/right_finger names, N>2 uses finger_0..N-1.
        finger_names = ["left_finger", "right_finger"] if n_fingers == 2 else [f"finger_{i}" for i in range(n_fingers)]
        self.finger_body_ids = {mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, n) for n in finger_names}
        self.finger_body_ids.discard(-1)
        self.hand_body_id = hand_body_id
        self.peak_force = 0.0
        self.n_steps = 0
        self.n_contact_steps = 0
        self.max_slip = 0.0
        self._ref_xy = None

    def sample(self) -> None:
        self.n_steps += 1
        contact_now = False
        result = np.zeros(6)
        geom_bodyid = self.model.geom_bodyid
        for i in range(self.data.ncon):
            c = self.data.contact[i]
            b1, b2 = geom_bodyid[c.geom1], geom_bodyid[c.geom2]
            if self.obj_body_id in (b1, b2) and ((b1 in self.finger_body_ids) or (b2 in self.finger_body_ids)):
                mujoco.mj_contactForce(self.model, self.data, i, result)
                mag = float(np.linalg.norm(result[:3]))
                self.peak_force = max(self.peak_force, mag)
                contact_now = True
        if contact_now:
            self.n_contact_steps += 1

        hand_xy = self.data.xpos[self.hand_body_id][:2]
        obj_xy = self.data.xpos[self.obj_body_id][:2]
        rel = obj_xy - hand_xy
        if self._ref_xy is None:
            self._ref_xy = rel.copy()
        self.max_slip = max(self.max_slip, float(np.linalg.norm(rel - self._ref_xy)))

    def finalize(self) -> tuple[float, float, float]:
        uptime = (self.n_contact_steps / self.n_steps) if self.n_steps else 0.0
        return self.peak_force, uptime, self.max_slip


def run_pick_place(
    model, data, *, obj_name: str, place_body_name: str, n_fingers: int, aperture: float,
    hand_to_fingertip: float, close_force: float, yaw_offset_deg: float, center_align: bool,
    success_tol: float = 0.06,
) -> dict:
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
    # Top-down grasp orientation: quaternion for extrinsic-XYZ euler (180deg, 0, yaw),
    # matching grasp_demo._topdown_quat's euler_to_quat([180, 0, yaw_deg]) exactly --
    # derived via quaternion composition qz(yaw) * qx(180) and cross-checked against
    # the known yaw=0 case ([0,1,0,0], confirmed against recorded Genesis trajectory
    # data in session 6's demo3d work).
    half_yaw = grasp_yaw / 2
    grasp_quat = np.array([0.0, np.cos(half_yaw), np.sin(half_yaw), 0.0])

    # Approach in two stages -- move to the target XY at a SAFE, consistently-high
    # altitude first, then descend onto the pregrasp point -- rather than one direct
    # joint-space interpolation from home to pregrasp. A single straight interpolation
    # swept the arm's mid-links through the tabletop (confirmed via contact trace:
    # "table <-> link4/link5" during what should be a clear-air approach), since
    # joint-space linearity doesn't guarantee Cartesian clearance the way Genesis's
    # collision-aware plan_path() does. This is the standard "lift/traverse/descend"
    # substitute for full motion planning, not a physics or task change.
    safe_pos = np.array([obj_pos[0], obj_pos[1], SAFE_APPROACH_Z])
    _interp_move(model, data, handles, safe_pos, grasp_quat, finger_cmd=open_travel, n_steps=80)

    pregrasp_pos = obj_pos + np.array([0, 0, PREGRASP_CLEARANCE])
    _interp_move(model, data, handles, pregrasp_pos, grasp_quat, finger_cmd=open_travel, n_steps=60)

    grasp_z = _grasp_hand_z(model, data, obj_body_id, center_align=center_align, hand_to_fingertip=hand_to_fingertip)
    grasp_pos = np.array([obj_pos[0], obj_pos[1], grasp_z])
    _interp_move(model, data, handles, grasp_pos, grasp_quat, finger_cmd=open_travel, n_steps=60)

    _interp_move(model, data, handles, grasp_pos, grasp_quat, close_force=close_force, n_steps=80)

    tracker = ContactTracker(model, data, obj_body_id, handles.hand_id, n_fingers)
    lift_pos = np.array([grasp_pos[0], grasp_pos[1], LIFT_HAND_Z])
    _interp_move(model, data, handles, lift_pos, grasp_quat, close_force=close_force, tracker=tracker)

    place_pos = data.xpos[place_body_id].copy()
    above_pos = np.array([place_pos[0], place_pos[1], place_pos[2] + PLACE_HAND_Z_ABOVE_TARGET])
    _interp_move(model, data, handles, above_pos, grasp_quat, close_force=close_force, tracker=tracker)

    _interp_move(model, data, handles, above_pos, grasp_quat, finger_cmd=open_travel, n_steps=50)

    retreat_pos = np.array([place_pos[0], place_pos[1], RETREAT_HAND_Z])
    _interp_move(model, data, handles, retreat_pos, grasp_quat, finger_cmd=open_travel, n_steps=50)
    settle(60)

    peak_force, uptime, max_slip = tracker.finalize()

    final_obj_pos = data.xpos[obj_body_id].copy()
    horiz = float(np.linalg.norm(final_obj_pos[:2] - place_pos[:2]))
    bowl_aabb_min, bowl_aabb_max = _entity_aabb(model, data, place_body_id)
    rim_z = bowl_aabb_max[2]
    rim_radius = 0.5 * min(bowl_aabb_max[0] - bowl_aabb_min[0], bowl_aabb_max[1] - bowl_aabb_min[1])
    within_footprint = horiz < min(success_tol, rim_radius)
    obj_aabb_min, _ = _entity_aabb(model, data, obj_body_id)
    inside_bowl = obj_aabb_min[2] < rim_z - 0.01
    success = bool(within_footprint and inside_bowl)

    return {"success": success, "peak_contact_force": peak_force, "contact_uptime_frac": uptime, "max_slip": max_slip}
