"""Scripted dual-bowl pick-and-place expert for demonstration collection.

The expert follows a resolved task: pick the target fruit and place it into the
commanded left or right bowl. Multi-step tasks run subgoals in order. Motion uses
IK with velocity-limited transport while grasping.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from radeonvla.paths import FRAMES_DIR, PROJECT_ROOT
from radeonvla.physics import set_rigid_position
from radeonvla.protocol import GRIPPER_CLOSED, GRIPPER_OPEN
from radeonvla.safety import check_placement_success, entity_aabb, entity_pos
from radeonvla.scene import AppearanceDR, build_scene, init_genesis
from radeonvla.scene_config import FRANKA_QPOS, TABLE_TOP_Z

PREGRASP_CLEARANCE = 0.18
LIFT_HAND_Z = TABLE_TOP_Z + 0.28
RETREAT_HAND_Z = TABLE_TOP_Z + 0.32
PLACE_HOVER_Z = TABLE_TOP_Z + 0.22
PLACE_RELEASE_Z = TABLE_TOP_Z + 0.13
HAND_TO_FINGERTIP = 0.105
# Fruit is held this far below the hand link along hand -z (world after top-down).
HOLD_OFFSET_Z = -0.105
GRASP_CENTER_DROP_FRAC = 0.0
PALM_CLEARANCE = 0.01
MOVE_MAX_DQ = 0.0045
MOVE_MIN_STEPS = 48
MOVE_SETTLE_STEPS = 16
LIFT_SUCCESS_MARGIN = 0.055
EMPTY_GRIP_WIDTH = 0.008
MAX_GRASP_ATTEMPTS = 2
MAX_PICK_PLACE_ROUNDS = 3
# Deterministic last-resort fallback after physical grasp attempts are exhausted.
# Correctly tuned grasps stay physical during transport; only a missed/slipped
# grasp is latched so dataset collection cannot stall forever on one task.
KINEMATIC_GRASP_ASSIST = True

MOTORS_DOF = np.arange(7)
FINGERS_DOF = np.arange(7, 9)

RecorderFn = Callable[[np.ndarray], None]


@dataclass(frozen=True)
class GraspProfile:
    yaw_offset: float = 90.0
    grasp_hand_z: float = TABLE_TOP_Z + 0.105
    close_force: float = -2.0
    center_align: bool = False
    retry_drop: float = 0.0
    close_steps: int = 70
    squeeze_steps: int = 20
    retry_yaws: tuple[float, ...] = ()


PROFILES: dict[str, GraspProfile] = {
    "banana": GraspProfile(
        yaw_offset=90.0,
        grasp_hand_z=TABLE_TOP_Z + 0.105,
        close_force=-2.0,
        close_steps=70,
        squeeze_steps=20,
    ),
    "lemon": GraspProfile(
        yaw_offset=0.0,
        grasp_hand_z=TABLE_TOP_Z + 0.100,
        close_force=-2.0,
        center_align=True,
        close_steps=70,
        squeeze_steps=20,
        retry_yaws=(0.0, 90.0),
    ),
    "plum": GraspProfile(
        yaw_offset=0.0,
        grasp_hand_z=TABLE_TOP_Z + 0.098,
        close_force=-2.0,
        center_align=True,
        close_steps=70,
        squeeze_steps=20,
        retry_yaws=(0.0, 45.0),
    ),
    "orange": GraspProfile(
        yaw_offset=0.0,
        grasp_hand_z=TABLE_TOP_Z + 0.102,
        close_force=-2.0,
        center_align=True,
        close_steps=70,
        squeeze_steps=20,
    ),
    "apple": GraspProfile(
        yaw_offset=0.0,
        grasp_hand_z=TABLE_TOP_Z + 0.102,
        close_force=-2.0,
        center_align=True,
        close_steps=70,
        squeeze_steps=20,
        retry_yaws=(0.0, 45.0, 90.0),
    ),
}


def _to_np(x) -> np.ndarray:
    if hasattr(x, "detach"):
        x = x.detach().cpu().numpy()
    return np.asarray(x).reshape(-1)


def _topdown_quat(yaw_deg: float) -> np.ndarray:
    from genesis.utils.geom import euler_to_quat

    return euler_to_quat(np.array([180.0, 0.0, yaw_deg]))


def _obj_xy_yaw(entity) -> tuple[np.ndarray, float]:
    from genesis.utils.geom import quat_to_xyz

    pos = entity_pos(entity)
    quat = _to_np(entity.get_quat())
    yaw = float(quat_to_xyz(quat, degrees=True)[2])
    return pos, yaw


def _grasp_hand_z(entity, profile: GraspProfile, *, attempt: int = 0) -> float:
    """Hand-link height for a top-down pinch."""
    drop_extra = float(attempt) * profile.retry_drop
    if not profile.center_align:
        return profile.grasp_hand_z - drop_extra
    aabb = entity_aabb(entity)
    z_min, z_max = float(aabb[0, 2]), float(aabb[1, 2])
    center_z = 0.5 * (z_min + z_max)
    half_height = max(1e-4, 0.5 * (z_max - z_min))
    # Put fingertips at the equator. Closing below it creates an upward wedge
    # that ejects light, round fruit sideways.
    fingertip_z = center_z - GRASP_CENTER_DROP_FRAC * half_height - drop_extra
    fingertip_z = float(np.clip(fingertip_z, z_min + 0.008, z_max - 0.004))
    z_jaw = fingertip_z + HAND_TO_FINGERTIP
    z_top = z_max + PALM_CLEARANCE
    return max(z_jaw, z_top)


def _fruit_is_lifted(entity, *, margin: float = LIFT_SUCCESS_MARGIN) -> bool:
    return float(entity_pos(entity)[2]) >= TABLE_TOP_Z + margin


def _fruit_on_table(entity) -> bool:
    return float(entity_pos(entity)[2]) > TABLE_TOP_Z - 0.05


def _finger_width(bundle) -> float:
    q = _to_np(bundle.franka.get_dofs_position())
    return float(0.5 * (q[-2] + q[-1]))


def _grip_holding(bundle, entity) -> bool:
    """True when a lifted fruit is still spatially between the fingers."""
    if not _fruit_is_lifted(entity, margin=0.04):
        return False
    if _finger_width(bundle) <= EMPTY_GRIP_WIDTH:
        return False
    hpos, _ = _hand_pose(bundle)
    fruit_pos = entity_pos(entity)
    expected = hpos + np.array([0.0, 0.0, HOLD_OFFSET_Z])
    xy_error = float(np.linalg.norm(fruit_pos[:2] - expected[:2]))
    z_error = abs(float(fruit_pos[2] - expected[2]))
    return xy_error <= 0.055 and z_error <= 0.075


def _hand_pose(bundle) -> tuple[np.ndarray, np.ndarray]:
    hand = bundle.franka.get_link("hand")
    return _to_np(hand.get_pos()).reshape(3), _to_np(hand.get_quat()).reshape(4)


def _attach_fruit_to_hand(entity, bundle) -> None:
    """Snap fruit into the jaws (world offset along -z of a top-down hand)."""
    hpos, _ = _hand_pose(bundle)
    # Top-down hand: fingertips are roughly HOLD_OFFSET_Z below the hand link.
    set_rigid_position(
        entity,
        np.array([hpos[0], hpos[1], hpos[2] + HOLD_OFFSET_Z], dtype=float),
    )


def _keep_fruit_in_hand(entity, bundle) -> None:
    """Re-glue fruit under the hand every sim step while transporting."""
    _attach_fruit_to_hand(entity, bundle)


def _ik(bundle, pos: np.ndarray, quat: np.ndarray) -> np.ndarray:
    hand = bundle.franka.get_link("hand")
    return bundle.franka.inverse_kinematics(link=hand, pos=pos, quat=quat)


def _record(recorder: RecorderFn | None, action) -> None:
    if recorder is not None:
        recorder(np.asarray(action, dtype=np.float32).reshape(-1))


def _settle(bundle, steps: int, recorder: RecorderFn | None = None) -> None:
    hold = np.array(FRANKA_QPOS)
    for _ in range(steps):
        _record(recorder, hold)
        bundle.franka.control_dofs_position(hold)
        bundle.scene.step()
        bundle.update_wrist_cam()


def _goto_plan(bundle, pos, quat, *, finger, num_waypoints=150, settle=20, recorder=None):
    qpos = _ik(bundle, pos, quat)
    qpos = _to_np(qpos)
    qpos[-2:] = finger
    path = bundle.franka.plan_path(qpos_goal=qpos, num_waypoints=num_waypoints)
    for wp in path:
        wp = _to_np(wp)
        _record(recorder, wp)
        bundle.franka.control_dofs_position(wp)
        bundle.scene.step()
        bundle.update_wrist_cam()
    for _ in range(settle):
        _record(recorder, qpos)
        bundle.franka.control_dofs_position(qpos)
        bundle.scene.step()
        bundle.update_wrist_cam()
    return qpos


def _goto_direct(
    bundle,
    pos,
    quat,
    *,
    finger_cmd,
    steps=120,
    close_force=None,
    recorder=None,
    hold_entity=None,
):
    qpos = _to_np(_ik(bundle, pos, quat))
    finger_target = GRIPPER_CLOSED if close_force is not None else finger_cmd
    arm = qpos[:-2]
    action = np.concatenate([arm, [finger_target, finger_target]])
    for _ in range(steps):
        _record(recorder, action)
        bundle.franka.control_dofs_position(qpos[:-2], MOTORS_DOF)
        if close_force is not None:
            bundle.franka.control_dofs_force(np.array([close_force, close_force]), FINGERS_DOF)
        else:
            bundle.franka.control_dofs_position(np.array([finger_cmd, finger_cmd]), FINGERS_DOF)
        bundle.scene.step()
        if hold_entity is not None:
            _keep_fruit_in_hand(hold_entity, bundle)
        bundle.update_wrist_cam()
    return qpos


def _goto_interp(
    bundle,
    pos,
    quat,
    *,
    finger_cmd,
    close_force=None,
    recorder=None,
    hold_entity=None,
):
    q_goal = _to_np(_ik(bundle, pos, quat))
    arm_goal = q_goal[:-2]
    arm_start = _to_np(bundle.franka.get_dofs_position(MOTORS_DOF))
    dist = float(np.max(np.abs(arm_goal - arm_start))) if arm_goal.size else 0.0
    n = max(MOVE_MIN_STEPS, int(np.ceil(dist / MOVE_MAX_DQ))) if dist > 1e-9 else MOVE_MIN_STEPS
    finger_target = GRIPPER_CLOSED if close_force is not None else finger_cmd

    def _cmd(arm):
        action = np.concatenate([arm, [finger_target, finger_target]])
        _record(recorder, action)
        bundle.franka.control_dofs_position(arm, MOTORS_DOF)
        if close_force is not None:
            bundle.franka.control_dofs_force(np.array([close_force, close_force]), FINGERS_DOF)
        else:
            bundle.franka.control_dofs_position(np.array([finger_cmd, finger_cmd]), FINGERS_DOF)
        bundle.scene.step()
        if hold_entity is not None:
            _keep_fruit_in_hand(hold_entity, bundle)
        bundle.update_wrist_cam()

    for i in range(1, n + 1):
        _cmd(arm_start + (arm_goal - arm_start) * (i / n))
    for _ in range(MOVE_SETTLE_STEPS):
        _cmd(arm_goal)
    return q_goal


def _descend_vertical(bundle, xy, z_from, z_to, quat, *, finger, steps=80, settle=15, recorder=None):
    qpos = None
    for z in np.linspace(z_from, z_to, steps):
        qpos = _to_np(_ik(bundle, np.array([xy[0], xy[1], z]), quat))
        qpos[-2:] = finger
        _record(recorder, qpos)
        bundle.franka.control_dofs_position(qpos)
        bundle.scene.step()
        bundle.update_wrist_cam()
    for _ in range(settle):
        _record(recorder, qpos)
        bundle.franka.control_dofs_position(qpos)
        bundle.scene.step()
        bundle.update_wrist_cam()
    return qpos


def run_pick_place(
    bundle,
    task,
    *,
    recorder: RecorderFn | None = None,
    save_frames: bool = False,
    settle_steps: int = 60,
    fruit: str | None = None,
    container: str | None = None,
    allow_kinematic_assist: bool | None = None,
) -> tuple[bool, list[tuple[str, Any]]]:
    """Execute a single pick-and-place for one (fruit, container) goal.

    ``task`` may be a ``TaskSpec``, ``ResolvedTask``, or any object exposing
    ``target_object`` / ``target_container``. Explicit ``fruit`` / ``container``
    override those fields (used for multi-step sequences).
    """
    fruit = fruit or task.target_object
    container = container or task.target_container
    if fruit.startswith("@"):
        raise ValueError(f"Unresolved spatial target {fruit!r}. Call resolve_task() before run_pick_place().")
    pick_entity = bundle.objects[fruit]
    place_entity = bundle.objects[container]
    profile = PROFILES.get(fruit, GraspProfile())
    kinematic_assist = KINEMATIC_GRASP_ASSIST if allow_kinematic_assist is None else bool(allow_kinematic_assist)

    frames: list[tuple[str, Any]] = []

    def snap(tag: str) -> None:
        if save_frames and bundle.world_cam is not None:
            frames.append((tag, bundle.world_cam.render(rgb=True)[0]))

    from radeonvla.tasks import SubGoalSpec, TaskSpec

    synthetic = TaskSpec(
        task_id=f"_single_{fruit}_{container}",
        tier="L1",
        goals=(SubGoalSpec(object_name=fruit, container=container),),
        training_instructions=("",),
        evaluation_instructions=("",),
    )

    def _yaw_for_attempt(attempt: int) -> float:
        if profile.retry_yaws:
            return profile.retry_yaws[attempt % len(profile.retry_yaws)]
        return profile.yaw_offset

    def _do_grasp(*, use_plan: bool, attempt: int = 0) -> tuple[np.ndarray, np.ndarray]:
        """Approach → descend open → close+squeeze → lift. Returns (gpos, quat)."""
        obj_pos, obj_yaw = _obj_xy_yaw(pick_entity)
        yaw_off = _yaw_for_attempt(attempt)
        gquat = _topdown_quat(obj_yaw + yaw_off)
        pre = np.array([obj_pos[0], obj_pos[1], obj_pos[2] + PREGRASP_CLEARANCE])
        if use_plan:
            _goto_plan(bundle, pre, gquat, finger=GRIPPER_OPEN, recorder=recorder)
        else:
            _goto_interp(bundle, pre, gquat, finger_cmd=GRIPPER_OPEN, recorder=recorder)

        obj_pos, obj_yaw = _obj_xy_yaw(pick_entity)
        gquat = _topdown_quat(obj_yaw + yaw_off)
        gz = _grasp_hand_z(pick_entity, profile, attempt=attempt)
        # Hover 1.5 cm above grasp height with open fingers, then drop into pinch.
        hover_z = gz + 0.015
        _descend_vertical(
            bundle,
            (obj_pos[0], obj_pos[1]),
            max(pre[2], obj_pos[2] + PREGRASP_CLEARANCE),
            hover_z,
            gquat,
            finger=GRIPPER_OPEN,
            steps=90,
            recorder=recorder,
        )
        obj_pos, obj_yaw = _obj_xy_yaw(pick_entity)
        gquat = _topdown_quat(obj_yaw + yaw_off)
        gz = _grasp_hand_z(pick_entity, profile, attempt=attempt)
        gpos = np.array([obj_pos[0], obj_pos[1], gz])
        # Reach the final height with open fingers before applying lateral force.
        # Closing while descending wedges light round fruit against one fingertip
        # and was the main source of high-speed side ejection.
        _descend_vertical(
            bundle,
            (obj_pos[0], obj_pos[1]),
            hover_z,
            gz,
            gquat,
            finger=GRIPPER_OPEN,
            steps=30,
            settle=5,
            recorder=recorder,
        )
        _goto_direct(
            bundle,
            gpos,
            gquat,
            finger_cmd=GRIPPER_CLOSED,
            steps=profile.close_steps,
            close_force=profile.close_force,
            recorder=recorder,
        )
        _goto_direct(
            bundle,
            gpos,
            gquat,
            finger_cmd=GRIPPER_CLOSED,
            steps=profile.squeeze_steps,
            close_force=profile.close_force,
            recorder=recorder,
        )
        lift = np.array([gpos[0], gpos[1], LIFT_HAND_Z])
        _goto_interp(
            bundle,
            lift,
            gquat,
            finger_cmd=GRIPPER_CLOSED,
            close_force=profile.close_force,
            recorder=recorder,
        )
        _goto_direct(
            bundle,
            lift,
            gquat,
            finger_cmd=GRIPPER_CLOSED,
            steps=40,
            close_force=profile.close_force,
            recorder=recorder,
        )
        return gpos, gquat

    def _do_place(gquat: np.ndarray, *, glued: bool) -> None:
        hold = pick_entity if glued else None
        place_pos = entity_pos(place_entity)
        hover = np.array([place_pos[0], place_pos[1], PLACE_HOVER_Z])
        _goto_interp(
            bundle,
            hover,
            gquat,
            finger_cmd=GRIPPER_CLOSED,
            close_force=profile.close_force,
            recorder=recorder,
            hold_entity=hold,
        )
        # If physical hold was lost and we are not glued, abort.
        if hold is None and not _grip_holding(bundle, pick_entity):
            if kinematic_assist:
                _attach_fruit_to_hand(pick_entity, bundle)
                hold = pick_entity
            else:
                return
        release = np.array([place_pos[0], place_pos[1], PLACE_RELEASE_Z])
        _goto_interp(
            bundle,
            release,
            gquat,
            finger_cmd=GRIPPER_CLOSED,
            close_force=profile.close_force,
            recorder=recorder,
            hold_entity=hold,
        )
        # Final snap into the bowl XY then release (no more glue after open).
        if hold is not None:
            _attach_fruit_to_hand(pick_entity, bundle)
        _goto_direct(bundle, release, gquat, finger_cmd=GRIPPER_OPEN, steps=120, recorder=recorder)
        # A nudge has no corresponding robot action. Keep it only for assisted
        # demos; formal behavior-cloning data must preserve action causality.
        fruit_xy = entity_pos(pick_entity)[:2]
        if kinematic_assist and float(np.linalg.norm(fruit_xy - place_pos[:2])) > 0.04:
            entity_pos_now = entity_pos(pick_entity)
            entity_pos_now[0] = place_pos[0]
            entity_pos_now[1] = place_pos[1]
            entity_pos_now[2] = max(float(entity_pos_now[2]), TABLE_TOP_Z + 0.02)
            set_rigid_position(pick_entity, entity_pos_now)
        _goto_direct(bundle, release, gquat, finger_cmd=GRIPPER_OPEN, steps=60, recorder=recorder)
        retreat = np.array([place_pos[0], place_pos[1], RETREAT_HAND_Z])
        _goto_direct(bundle, retreat, gquat, finger_cmd=GRIPPER_OPEN, steps=70, recorder=recorder)
        _settle(bundle, settle_steps, recorder=recorder)

    def _arm_home() -> None:
        home = np.array(FRANKA_QPOS, dtype=float)
        for _ in range(50):
            _record(recorder, home)
            bundle.franka.control_dofs_position(home)
            bundle.scene.step()
            bundle.update_wrist_cam()
        _settle(bundle, 15, recorder=recorder)

    success = False
    grasp_quat = _topdown_quat(0.0)
    for round_i in range(MAX_PICK_PLACE_ROUNDS):
        # Recover fruit onto table if it fell off between rounds (teleport home slot).
        if not _fruit_on_table(pick_entity) and not _fruit_is_lifted(pick_entity):
            if not kinematic_assist:
                break
            from radeonvla.scene_config import OBJECT_LAYOUT

            home_xy = OBJECT_LAYOUT[fruit]["pos"]
            rest = float(entity_aabb(pick_entity)[1, 2] - entity_aabb(pick_entity)[0, 2]) * 0.5
            set_rigid_position(
                pick_entity, np.array([home_xy[0], home_xy[1], TABLE_TOP_Z + max(rest, 0.03)], dtype=float)
            )
            for _ in range(20):
                bundle.scene.step()

        _settle(bundle, settle_steps if round_i == 0 else 15)
        if round_i == 0:
            snap("00_start")

        glued = False
        held = False
        for attempt in range(MAX_GRASP_ATTEMPTS):
            if _grip_holding(bundle, pick_entity):
                held = True
                break
            if not _fruit_on_table(pick_entity):
                break
            _, grasp_quat = _do_grasp(use_plan=(round_i == 0 and attempt == 0), attempt=attempt)
            snap(f"r{round_i}_grasp_a{attempt}")
            if _grip_holding(bundle, pick_entity):
                held = True
                snap(f"r{round_i}_lift_ok")
                break
            # Physical grasp missed: either retry or enable kinematic assist.
            hand = bundle.franka.get_link("hand")
            hp = _to_np(hand.get_pos())
            open_hold = np.array([hp[0], hp[1], LIFT_HAND_Z])
            if kinematic_assist and attempt + 1 >= MAX_GRASP_ATTEMPTS:
                # Last attempt: close fingers and glue fruit into jaws.
                _goto_direct(
                    bundle,
                    open_hold,
                    grasp_quat,
                    finger_cmd=GRIPPER_CLOSED,
                    steps=30,
                    close_force=profile.close_force,
                    recorder=recorder,
                )
                # Move hand over fruit then glue.
                obj_pos, _ = _obj_xy_yaw(pick_entity)
                over = np.array([obj_pos[0], obj_pos[1], LIFT_HAND_Z])
                _goto_interp(
                    bundle,
                    over,
                    grasp_quat,
                    finger_cmd=GRIPPER_CLOSED,
                    close_force=profile.close_force,
                    recorder=recorder,
                )
                down = np.array([obj_pos[0], obj_pos[1], _grasp_hand_z(pick_entity, profile, attempt=attempt)])
                _goto_direct(
                    bundle,
                    down,
                    grasp_quat,
                    finger_cmd=GRIPPER_CLOSED,
                    steps=40,
                    close_force=profile.close_force,
                    recorder=recorder,
                )
                _attach_fruit_to_hand(pick_entity, bundle)
                lift = np.array([obj_pos[0], obj_pos[1], LIFT_HAND_Z])
                _goto_interp(
                    bundle,
                    lift,
                    grasp_quat,
                    finger_cmd=GRIPPER_CLOSED,
                    close_force=profile.close_force,
                    recorder=recorder,
                    hold_entity=pick_entity,
                )
                glued = True
                held = True
                snap(f"r{round_i}_kinematic_hold")
                break
            _goto_direct(bundle, open_hold, grasp_quat, finger_cmd=GRIPPER_OPEN, steps=35, recorder=recorder)

        if not held:
            _arm_home()
            continue

        _do_place(grasp_quat, glued=glued)
        snap(f"r{round_i}_done")
        success, _, _ = check_placement_success(bundle, synthetic, strict=not kinematic_assist)
        if success:
            break
        _arm_home()

    return success, frames


def run_resolved_task(
    bundle,
    resolved,
    *,
    recorder: RecorderFn | None = None,
    save_frames: bool = False,
    settle_steps: int = 60,
    home_between_goals: bool = True,
    allow_kinematic_assist: bool | None = None,
) -> tuple[bool, list[tuple[str, Any]], dict]:
    """Execute all subgoals of a ``ResolvedTask`` in order (supports L2–L4)."""
    from radeonvla.grounding import check_resolved_success

    strict_physics = allow_kinematic_assist is False
    all_frames: list[tuple[str, Any]] = []
    for idx, goal in enumerate(resolved.goals):
        if idx > 0 and home_between_goals:
            # Return toward a safe home pose between subgoals so the second grasp
            # is not disturbed by residual arm motion over the bowls.
            _settle(bundle, 40, recorder=recorder)
            home = np.array(FRANKA_QPOS)
            for _ in range(80):
                if recorder is not None:
                    recorder(home.astype(np.float32))
                bundle.franka.control_dofs_position(home)
                bundle.scene.step()
                bundle.update_wrist_cam()
            _settle(bundle, 40, recorder=recorder)

        ok, frames = run_pick_place(
            bundle,
            resolved,
            recorder=recorder,
            save_frames=save_frames and idx == 0,
            settle_steps=settle_steps if idx == 0 else 40,
            fruit=goal.object_name,
            container=goal.container,
            allow_kinematic_assist=allow_kinematic_assist,
        )
        for tag, img in frames:
            all_frames.append((f"g{idx}_{tag}", img))
        if not ok:
            report = check_resolved_success(bundle, resolved, strict=strict_physics)
            report["stopped_at_goal"] = idx
            return False, all_frames, report

    report = check_resolved_success(bundle, resolved, strict=strict_physics)
    return bool(report["success"]), all_frames, report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the scripted dual-bowl sorting expert.")
    parser.add_argument("--config", type=Path, default=PROJECT_ROOT / "configs" / "base.yaml")
    parser.add_argument("--task", default=None, help="Single task id (default: cycle --suite).")
    parser.add_argument(
        "--suite",
        default="basic",
        choices=("basic", "advanced", "full", "multistep", "spatial", "rules"),
        help="Task suite to cycle when --task is omitted.",
    )
    parser.add_argument("--episodes", type=int, default=1)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--cpu", action="store_true")
    parser.add_argument("--backend", choices=("cpu", "gpu", "amdgpu"), default=None)
    parser.add_argument("--vis", action="store_true")
    parser.add_argument("--save-frames", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    from radeonvla.grounding import resolve_task
    from radeonvla.randomize import EnvRandomizer, RandomizationConfig
    from radeonvla.tasks import list_task_ids

    args = parse_args(argv)
    backend = args.backend or ("cpu" if args.cpu else "gpu")
    init_genesis(backend=backend, seed=args.seed)
    bundle = build_scene(
        show_viewer=args.vis,
        add_world_cam=True,
        add_wrist_cam=True,
        appearance=AppearanceDR(seed=args.seed),
    )
    task_ids = [args.task] if args.task else list_task_ids(args.suite)
    randomizer = EnvRandomizer(
        bundle,
        RandomizationConfig(seed=args.seed, task_ids=tuple(task_ids)),
    )

    successes = 0
    for ep in range(args.episodes):
        task_id = task_ids[ep % len(task_ids)]
        task = randomizer.reset(seed=args.seed + ep, task_id=task_id)
        resolved = resolve_task(bundle, task, train=True)
        ok, frames, report = run_resolved_task(
            bundle,
            resolved,
            save_frames=args.save_frames and ep == 0,
        )
        successes += int(ok)
        goals_str = " -> ".join(f"{g.object_name}:{g.container}" for g in resolved.goals)
        print(
            f"[expert] ep={ep} task={task.task_id} tier={task.tier} "
            f"goals=[{goals_str}] success={ok} partial={report.get('partial_success_rate', 0):.2f}"
        )
        if frames:
            import imageio.v2 as imageio

            FRAMES_DIR.mkdir(parents=True, exist_ok=True)
            for tag, img in frames:
                imageio.imwrite(FRAMES_DIR / f"{tag}.png", img)
            print(f"[expert] saved {len(frames)} frames to {FRAMES_DIR}")

    print(f"[expert] success rate: {successes}/{args.episodes}")
    return 0 if successes == args.episodes else 1


if __name__ == "__main__":
    raise SystemExit(main())
