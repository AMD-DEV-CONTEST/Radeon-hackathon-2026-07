"""Execute and verify a mobile Franka pick-and-lift on AMD Genesis."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import imageio.v2 as imageio
import numpy as np
import genesis as gs
from genesis.utils.geom import euler_to_quat

from .large_room_scene import _build_large_room, _configure_robot, _measured_xy
from .spatial_tasks import SEMANTIC_DOCKS, build_room_grid, generate_task, plan_transport


OPEN = 0.04
CLOSE_FORCE = -12.0
LINK7_TO_GRASP_TARGET_M = 0.212


def _entity_pos(entity) -> np.ndarray:
    return entity.get_pos().detach().cpu().numpy().reshape(-1)[:3]


def _tcp_pos(link, local_point: np.ndarray) -> np.ndarray:
    pos = link.get_pos().detach().cpu().numpy().reshape(-1)[:3]
    w, x, y, z = link.get_quat().detach().cpu().numpy().reshape(-1)[:4]
    rotation = np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ]
    )
    return pos + rotation @ local_point


def _move_arm(
    scene,
    robot,
    *,
    arm_indices: list[int],
    finger_indices: list[int],
    hand,
    local_point: np.ndarray,
    target: np.ndarray,
    quat: np.ndarray,
    steps: int,
    close: bool,
    latch_object=None,
    finger_position: np.ndarray | None = None,
):
    q_goal = robot.inverse_kinematics(
        link=hand,
        pos=target,
        quat=quat,
        local_point=local_point,
        dofs_idx_local=arm_indices,
        max_samples=80,
        max_solver_iters=50,
    )
    q_goal = q_goal.detach().cpu().numpy().reshape(-1)
    arm_start = (
        robot.get_dofs_position(arm_indices).detach().cpu().numpy().reshape(-1)
    )
    arm_goal = q_goal[arm_indices]
    for alpha in np.linspace(0.0, 1.0, steps):
        arm = arm_start * (1.0 - alpha) + arm_goal * alpha
        robot.control_dofs_position(arm, arm_indices)
        if close:
            if finger_position is None:
                robot.control_dofs_force(
                    np.array([CLOSE_FORCE, CLOSE_FORCE]), finger_indices
                )
            else:
                robot.control_dofs_position(finger_position, finger_indices)
        else:
            robot.control_dofs_position(np.array([OPEN, OPEN]), finger_indices)
        scene.step()
        if latch_object is not None:
            latch_object.set_pos(_tcp_pos(hand, local_point))
    measured = _tcp_pos(hand, local_point)
    return {
        "commanded_tcp_xyz": target.tolist(),
        "measured_tcp_xyz": measured.tolist(),
        "tcp_error_m": float(np.linalg.norm(measured - target)),
    }


def _move_tcp_linear(
    scene,
    robot,
    *,
    arm_indices: list[int],
    finger_indices: list[int],
    hand,
    local_point: np.ndarray,
    start: np.ndarray,
    target: np.ndarray,
    quat: np.ndarray,
    steps: int,
    close: bool,
    latch_object=None,
    finger_position: np.ndarray | None = None,
):
    """Track a Cartesian line with controller dwell at every waypoint.

    Sending a new IK target every simulation step lets the command outrun the
    physical position controller. Use fewer Cartesian waypoints and hold each
    for multiple simulation steps, while keeping the same overall step budget.
    """
    control_steps_per_waypoint = 4
    waypoint_count = max(2, steps // control_steps_per_waypoint)
    for waypoint in np.linspace(start, target, waypoint_count):
        q_goal = robot.inverse_kinematics(
            link=hand,
            pos=waypoint,
            quat=quat,
            local_point=local_point,
            init_qpos=robot.get_qpos(),
            dofs_idx_local=arm_indices,
            max_samples=2,
            max_solver_iters=25,
        )
        arm = q_goal.detach().cpu().numpy().reshape(-1)[arm_indices]
        for _ in range(control_steps_per_waypoint):
            robot.control_dofs_position(arm, arm_indices)
            if close:
                if finger_position is None:
                    robot.control_dofs_force(
                        np.array([CLOSE_FORCE, CLOSE_FORCE]), finger_indices
                    )
                else:
                    robot.control_dofs_position(finger_position, finger_indices)
            else:
                robot.control_dofs_position(np.array([OPEN, OPEN]), finger_indices)
            scene.step()
            if latch_object is not None:
                latch_object.set_pos(_tcp_pos(hand, local_point))
    # Hold the final IK solution before measuring or starting finger closure.
    for _ in range(60):
        robot.control_dofs_position(arm, arm_indices)
        if close:
            if finger_position is None:
                robot.control_dofs_force(
                    np.array([CLOSE_FORCE, CLOSE_FORCE]), finger_indices
                )
            else:
                robot.control_dofs_position(finger_position, finger_indices)
        else:
            robot.control_dofs_position(np.array([OPEN, OPEN]), finger_indices)
        scene.step()
        if latch_object is not None:
            latch_object.set_pos(_tcp_pos(hand, local_point))
    measured = _tcp_pos(hand, local_point)
    return {
        "commanded_tcp_xyz": target.tolist(),
        "measured_tcp_xyz": measured.tolist(),
        "tcp_error_m": float(np.linalg.norm(measured - target)),
        "trajectory": "cartesian_linear",
    }


def _hold_grasp(
    scene,
    robot,
    *,
    arm_indices: list[int],
    finger_indices: list[int],
    steps: int,
    close: bool,
    latch_object=None,
    hand=None,
    local_point: np.ndarray | None = None,
    ramp_force: bool = False,
    finger_position: np.ndarray | None = None,
) -> None:
    """Hold the arm still while finger contact converges."""
    arm_hold = (
        robot.get_dofs_position(arm_indices).detach().cpu().numpy().reshape(-1)
    )
    for step_index in range(steps):
        robot.control_dofs_position(arm_hold, arm_indices)
        if close:
            if finger_position is None:
                force_scale = (
                    min(1.0, (step_index + 1) / min(steps, 120))
                    if ramp_force
                    else 1.0
                )
                robot.control_dofs_force(
                    np.array(
                        [CLOSE_FORCE * force_scale, CLOSE_FORCE * force_scale]
                    ),
                    finger_indices,
                )
            else:
                robot.control_dofs_position(finger_position, finger_indices)
        else:
            robot.control_dofs_position(np.array([OPEN, OPEN]), finger_indices)
        scene.step()
        if latch_object is not None:
            latch_object.set_pos(_tcp_pos(hand, local_point))


def _capture_key_frame(output_dir: Path, name: str, camera) -> np.ndarray:
    """Render and persist one named frame from the running simulation."""
    frame = camera.render(rgb=True)[0]
    imageio.imwrite(output_dir / f"{name}.png", frame)
    return frame


def _grasp_contact_diagnostics(robot, pick_object, finger_indices) -> dict:
    """Capture physical contact evidence immediately after finger closure."""
    contacts = robot.get_contacts(
        with_entity=pick_object, exclude_self_contact=True
    )
    positions = contacts["position"].detach().cpu().numpy()
    forces = contacts["force_a"].detach().cpu().numpy()
    link_a = contacts["link_a"].detach().cpu().numpy().reshape(-1)
    link_b = contacts["link_b"].detach().cpu().numpy().reshape(-1)
    link_names = {
        int(link.idx): link.name
        for entity in (robot, pick_object)
        for link in entity.links
    }
    finger_positions = {
        name: _entity_pos(robot.get_link(name)).tolist()
        for name in ("panda_leftfinger", "panda_rightfinger")
    }
    return {
        "contact_count": int(len(positions)),
        "contact_positions_xyz": positions.tolist(),
        "contact_force_norms_n": np.linalg.norm(forces, axis=-1).tolist(),
        "contact_link_pairs": [
            {
                "link_a": link_names.get(int(a), f"global_link_{int(a)}"),
                "link_b": link_names.get(int(b), f"global_link_{int(b)}"),
            }
            for a, b in zip(link_a, link_b)
        ],
        "finger_qpos_m": (
            robot.get_dofs_position(finger_indices)
            .detach()
            .cpu()
            .numpy()
            .reshape(-1)
            .tolist()
        ),
        "finger_link_positions_xyz": finger_positions,
        "object_position_xyz": _entity_pos(pick_object).tolist(),
    }


def _close_until_bilateral_contact(
    scene,
    robot,
    pick_object,
    *,
    arm_indices: list[int],
    finger_indices: list[int],
    max_steps: int,
) -> dict:
    """Stop closing as soon as both fingers contact the object."""
    arm_hold = (
        robot.get_dofs_position(arm_indices).detach().cpu().numpy().reshape(-1)
    )
    finger_link_ids = {
        int(robot.get_link(name).idx): name
        for name in ("panda_leftfinger", "panda_rightfinger")
    }
    detected_step = None
    held_qpos = None
    hold_target = None
    preload_force_n = None
    for step_index in range(max_steps):
        robot.control_dofs_position(arm_hold, arm_indices)
        force_scale = min(1.0, (step_index + 1) / min(max_steps, 120))
        robot.control_dofs_force(
            np.array(
                [CLOSE_FORCE * force_scale, CLOSE_FORCE * force_scale]
            ),
            finger_indices,
        )
        scene.step()
        contacts = robot.get_contacts(
            with_entity=pick_object, exclude_self_contact=True
        )
        link_a = contacts["link_a"].detach().cpu().numpy().reshape(-1)
        link_b = contacts["link_b"].detach().cpu().numpy().reshape(-1)
        contacted_fingers = {
            finger_link_ids[index]
            for index in np.concatenate((link_a, link_b)).astype(int)
            if index in finger_link_ids
        }
        if len(contacted_fingers) == 2:
            detected_step = step_index + 1
            held_qpos = (
                robot.get_dofs_position(finger_indices)
                .detach()
                .cpu()
                .numpy()
                .reshape(-1)
            )
            break

    if held_qpos is not None:
        # Add position preload gradually. Stop as soon as both fingers reach
        # useful contact force, avoiding the old behavior that squeezed until
        # the object was ejected.
        hold_target = held_qpos.copy()
        for preload_index in range(1, 141):
            candidate = np.maximum(held_qpos - 0.00015 * preload_index, 0.0)
            for _ in range(8):
                robot.control_dofs_position(arm_hold, arm_indices)
                robot.control_dofs_position(candidate, finger_indices)
                scene.step()
            diagnostics = _grasp_contact_diagnostics(
                robot, pick_object, finger_indices
            )
            finger_forces = {
                "panda_leftfinger": [],
                "panda_rightfinger": [],
            }
            for pair, force in zip(
                diagnostics["contact_link_pairs"],
                diagnostics["contact_force_norms_n"],
            ):
                for finger_name in finger_forces:
                    if finger_name in pair.values():
                        finger_forces[finger_name].append(float(force))
            if all(finger_forces.values()):
                hold_target = candidate
                preload_force_n = min(
                    max(values) for values in finger_forces.values()
                )
                if preload_force_n >= 1.5:
                    break
        for _ in range(80):
            robot.control_dofs_position(arm_hold, arm_indices)
            robot.control_dofs_position(hold_target, finger_indices)
            scene.step()
    return {
        "bilateral_contact_detected": detected_step is not None,
        "bilateral_contact_step": detected_step,
        "held_finger_qpos_m": None if held_qpos is None else held_qpos.tolist(),
        "hold_target_qpos_m": (
            None if hold_target is None else hold_target.tolist()
        ),
        "preload_force_n": preload_force_n,
    }


def _save_result(output_dir: Path, frames: list[np.ndarray], result: dict) -> None:
    imageio.imwrite(output_dir / "mobile_grasp_final.png", frames[-1])
    imageio.mimsave(output_dir / "mobile_grasp.mp4", frames, fps=8)
    key_frames = sorted(path.name for path in output_dir.glob("[0-9][0-9]_*.png"))
    artifacts = {
        "provenance": "Rendered directly from this Genesis simulation run",
        "synthetic_or_reconstructed": False,
        "seed": result.get("seed"),
        "backend": result.get("backend"),
        "key_frames": key_frames,
        "full_run_video": "mobile_grasp.mp4",
        "final_frame": "mobile_grasp_final.png",
        "structured_result": "mobile_grasp_result.json",
    }
    result["artifacts"] = artifacts
    (output_dir / "mobile_grasp_result.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    (output_dir / "artifact_manifest.json").write_text(
        json.dumps(artifacts, indent=2), encoding="utf-8"
    )
    print(json.dumps(result, indent=2))


def run_mobile_grasp(
    *,
    seed: int,
    output_dir: Path,
    grasp_latch: bool = False,
    grasp_yaw_deg: float = 45.0,
    grasp_z_offset_m: float = 0.0,
    grasp_probe_only: bool = False,
) -> dict:
    grid = build_room_grid()
    task = generate_task(seed, grid)
    plan = plan_transport(task, grid)
    scene, robot, camera, grasp_camera, pick_object = _build_large_room(
        start_xy=task.start_xy,
        generated_asset_dir=output_dir / "generated_assets",
        pick_zone=task.source_zone,
    )
    if pick_object is None:
        raise RuntimeError("pick object was not created")
    qpos, base_indices = _configure_robot(robot)
    arm_indices = [
        robot.get_joint(f"panda_joint{i}").dof_idx_local for i in range(1, 8)
    ]
    finger_indices = [
        robot.get_joint(name).dof_idx_local
        for name in ("panda_finger_joint1", "panda_finger_joint2")
    ]
    # Genesis 1.2's legacy URDF parser merges the fixed panda_hand and
    # panda_grasptarget links into panda_link7. Their combined tool-center offset
    # is 0.107 + 0.105 m along link7's local z axis.
    hand = robot.get_link("panda_link7")
    local_point = np.array([0.0, 0.0, LINK7_TO_GRASP_TARGET_M])
    output_dir.mkdir(parents=True, exist_ok=True)
    frames = [camera.render(rgb=True)[0]]
    start = np.asarray(task.start_xy)

    # Navigate to the pickup dock and deliberately face the source furniture.
    current = grid.cell_to_world(plan.pickup_path[0])
    for cell in plan.pickup_path[1:]:
        nxt = grid.cell_to_world(cell)
        delta = np.asarray(nxt) - np.asarray(current)
        yaw = float(np.arctan2(delta[1], delta[0]))
        for alpha in np.linspace(0.0, 1.0, 25):
            world = np.asarray(current) * (1.0 - alpha) + np.asarray(nxt) * alpha
            qpos[base_indices[0]] = world[0] - start[0]
            qpos[base_indices[1]] = world[1] - start[1]
            qpos[base_indices[2]] = yaw
            robot.control_dofs_position(qpos)
            scene.step()
        current = nxt
        frames.append(camera.render(rgb=True)[0])
    dock = np.asarray(SEMANTIC_DOCKS[task.source_zone])
    source_sign = 1.0 if dock[1] > 0 else -1.0
    qpos[base_indices[2]] = source_sign * np.pi / 2
    for _ in range(250):
        robot.control_dofs_position(qpos)
        scene.step()
    dock_error = float(np.linalg.norm(_measured_xy(robot) - dock))

    # Secondary manipulation docking: approach the furniture only after the
    # collision-free navigation dock has been reached. This moves the object
    # from the edge of Panda's workspace (~0.64 m) to a stable ~0.49 m reach.
    manipulation_dock = dock + np.array([0.0, source_sign * 0.15])
    qpos[base_indices[0]] = manipulation_dock[0] - start[0]
    qpos[base_indices[1]] = manipulation_dock[1] - start[1]
    for _ in range(220):
        robot.control_dofs_position(qpos)
        scene.step()
    frames.extend([grasp_camera.render(rgb=True)[0]] * 5)
    frames.append(
        _capture_key_frame(output_dir, "01_pickup_dock", grasp_camera)
    )

    object_before = _entity_pos(pick_object)
    # The fixed hand transform contributes -45 degrees yaw relative to link7.
    # Keep yaw configurable so physical-contact candidates can be measured
    # instead of silently selecting a single hard-coded orientation.
    quat = euler_to_quat(np.array([180.0, 0.0, grasp_yaw_deg]))
    pregrasp = np.array([object_before[0], object_before[1], object_before[2] + 0.18])
    grasp = np.array(
        [
            object_before[0],
            object_before[1],
            object_before[2] + grasp_z_offset_m,
        ]
    )
    lift = np.array([object_before[0], object_before[1], object_before[2] + 0.24])

    phase_metrics = {}
    phase_metrics["pregrasp"] = _move_arm(
        scene, robot, arm_indices=arm_indices, finger_indices=finger_indices,
        hand=hand, local_point=local_point, target=pregrasp, quat=quat,
        steps=160, close=False,
    )
    frames.extend([grasp_camera.render(rgb=True)[0]] * 5)
    frames.append(_capture_key_frame(output_dir, "02_pregrasp", grasp_camera))
    phase_metrics["descend"] = _move_tcp_linear(
        scene, robot, arm_indices=arm_indices, finger_indices=finger_indices,
        hand=hand, local_point=local_point, start=pregrasp, target=grasp,
        quat=quat, steps=160, close=False,
    )
    # Contact with a small object during descent can shift it before closure.
    # Re-observe and correct the TCP instead of closing at a stale open-loop pose.
    for correction_index in range(1, 3):
        observed_object = _entity_pos(pick_object)
        corrected_grasp = observed_object + np.array(
            [0.0, 0.0, grasp_z_offset_m]
        )
        correction_distance = float(
            np.linalg.norm(corrected_grasp - _tcp_pos(hand, local_point))
        )
        phase_metrics[f"preclose_observation_{correction_index}"] = {
            "object_xyz": observed_object.tolist(),
            "corrected_tcp_target_xyz": corrected_grasp.tolist(),
            "correction_distance_m": correction_distance,
        }
        # Do not chase an object that has already fallen off the work surface.
        if observed_object[2] < 0.70 or correction_distance <= 0.005:
            break
        phase_metrics[f"recenter_before_close_{correction_index}"] = (
            _move_tcp_linear(
                scene,
                robot,
                arm_indices=arm_indices,
                finger_indices=finger_indices,
                hand=hand,
                local_point=local_point,
                start=_tcp_pos(hand, local_point),
                target=corrected_grasp,
                quat=quat,
                steps=120,
                close=False,
            )
        )
        grasp = corrected_grasp
    frames.extend([grasp_camera.render(rgb=True)[0]] * 5)
    closure_event = _close_until_bilateral_contact(
        scene,
        robot,
        pick_object,
        arm_indices=arm_indices,
        finger_indices=finger_indices,
        max_steps=180,
    )
    phase_metrics["close"] = {
        "commanded_tcp_xyz": grasp.tolist(),
        "measured_tcp_xyz": _tcp_pos(hand, local_point).tolist(),
        "settle_steps": 180,
    }
    latch_object = None
    close_distance = float(
        np.linalg.norm(_entity_pos(pick_object) - _tcp_pos(hand, local_point))
    )
    phase_metrics["close"]["object_tcp_distance_m"] = close_distance
    phase_metrics["close"].update(
        _grasp_contact_diagnostics(robot, pick_object, finger_indices)
    )
    phase_metrics["close"].update(closure_event)
    finger_hold = (
        None
        if closure_event["hold_target_qpos_m"] is None
        else np.asarray(closure_event["hold_target_qpos_m"])
    )
    frames.append(_capture_key_frame(output_dir, "03_gripper_closed", grasp_camera))
    if grasp_latch and close_distance <= 0.12:
        latch_object = pick_object
    if grasp_probe_only:
        result = {
            "backend": "gpu",
            "seed": seed,
            "evaluation_scope": "close_contact_probe_only",
            "object_id": task.object_id,
            "source_zone": task.source_zone,
            "target_zone": task.target_zone,
            "grasp_yaw_deg": grasp_yaw_deg,
            "grasp_z_offset_m": grasp_z_offset_m,
            "phase_metrics": phase_metrics,
            "grasp_success": None,
            "place_success": None,
            "transport_success": None,
            "terminated_reason": "diagnostic_probe_complete",
        }
        _save_result(output_dir, frames, result)
        return result
    frames.extend([grasp_camera.render(rgb=True)[0]] * 5)
    lift_start = grasp
    for index, height in enumerate((0.06, 0.12, 0.18, 0.24), start=1):
        lift_waypoint = grasp + np.array([0.0, 0.0, height])
        phase_metrics[f"lift_{index}"] = _move_tcp_linear(
            scene, robot, arm_indices=arm_indices, finger_indices=finger_indices,
            hand=hand, local_point=local_point, start=lift_start,
            target=lift_waypoint, quat=quat, steps=180, close=True,
            latch_object=latch_object,
        )
        lift_start = lift_waypoint
    _hold_grasp(
        scene, robot, arm_indices=arm_indices, finger_indices=finger_indices,
        steps=160, close=True, latch_object=latch_object, hand=hand,
        local_point=local_point,
    )
    frames.extend([grasp_camera.render(rgb=True)[0]] * 10)
    frames.append(_capture_key_frame(output_dir, "04_first_lift", grasp_camera))

    object_after = _entity_pos(pick_object)
    lift_m = float(object_after[2] - object_before[2])
    retry_count = 0
    if lift_m < 0.10:
        # Open, retreat and wait for the disturbed object to stop before reobserving.
        retry_count = 1
        phase_metrics["retry_retreat"] = _move_arm(
            scene, robot, arm_indices=arm_indices, finger_indices=finger_indices,
            hand=hand, local_point=local_point, target=pregrasp, quat=quat,
            steps=160, close=False,
        )
        arm_wait = (
            robot.get_dofs_position(arm_indices).detach().cpu().numpy().reshape(-1)
        )
        for _ in range(180):
            robot.control_dofs_position(arm_wait, arm_indices)
            robot.control_dofs_position(np.array([OPEN, OPEN]), finger_indices)
            scene.step()
        retry_object = _entity_pos(pick_object)
        retry_pregrasp = retry_object + np.array([0.0, 0.0, 0.18])
        retry_grasp = retry_object + np.array([0.0, 0.0, grasp_z_offset_m])
        retry_lift = retry_object + np.array([0.0, 0.0, 0.20])
        phase_metrics["retry_pregrasp"] = _move_arm(
            scene, robot, arm_indices=arm_indices, finger_indices=finger_indices,
            hand=hand, local_point=local_point, target=retry_pregrasp, quat=quat,
            steps=180, close=False,
        )
        phase_metrics["retry_descend"] = _move_tcp_linear(
            scene, robot, arm_indices=arm_indices, finger_indices=finger_indices,
            hand=hand, local_point=local_point, start=retry_pregrasp,
            target=retry_grasp, quat=quat, steps=180, close=False,
        )
        retry_closure_event = _close_until_bilateral_contact(
            scene,
            robot,
            pick_object,
            arm_indices=arm_indices,
            finger_indices=finger_indices,
            max_steps=200,
        )
        phase_metrics["retry_close"] = {
            "commanded_tcp_xyz": retry_grasp.tolist(),
            "measured_tcp_xyz": _tcp_pos(hand, local_point).tolist(),
            "settle_steps": 200,
        }
        retry_close_distance = float(
            np.linalg.norm(_entity_pos(pick_object) - _tcp_pos(hand, local_point))
        )
        phase_metrics["retry_close"]["object_tcp_distance_m"] = (
            retry_close_distance
        )
        phase_metrics["retry_close"].update(
            _grasp_contact_diagnostics(robot, pick_object, finger_indices)
        )
        phase_metrics["retry_close"].update(retry_closure_event)
        finger_hold = (
            None
            if retry_closure_event["hold_target_qpos_m"] is None
            else np.asarray(retry_closure_event["hold_target_qpos_m"])
        )
        if grasp_latch and retry_close_distance <= 0.12:
            latch_object = pick_object
        retry_lift_start = retry_grasp
        for index, height in enumerate((0.05, 0.10, 0.15, 0.20), start=1):
            retry_lift_waypoint = retry_grasp + np.array([0.0, 0.0, height])
            phase_metrics[f"retry_lift_{index}"] = _move_tcp_linear(
                scene, robot, arm_indices=arm_indices,
                finger_indices=finger_indices, hand=hand,
                local_point=local_point, start=retry_lift_start,
                target=retry_lift_waypoint, quat=quat, steps=200,
                close=True, latch_object=latch_object,
            )
            retry_lift_start = retry_lift_waypoint
        object_after = _entity_pos(pick_object)
        lift_m = float(object_after[2] - retry_object[2])
        frames.extend([grasp_camera.render(rgb=True)[0]] * 10)
        frames.append(_capture_key_frame(output_dir, "05_retry_lift", grasp_camera))

    grasp_success = lift_m >= 0.10
    if not grasp_success:
        # Safety gate: never drive to the destination without a verified payload.
        result = {
            "backend": "gpu",
            "seed": seed,
            "object_id": task.object_id,
            "source_zone": task.source_zone,
            "target_zone": task.target_zone,
            "start_xy": task.start_xy,
            "dock_target_xy": dock.tolist(),
            "dock_error_m": dock_error,
            "object_before_xyz": object_before.tolist(),
            "object_after_xyz": object_after.tolist(),
            "object_lift_m": lift_m,
            "retry_count": retry_count,
            "grasp_yaw_deg": grasp_yaw_deg,
            "grasp_z_offset_m": grasp_z_offset_m,
            "phase_metrics": phase_metrics,
            "grasp_success": False,
            "place_success": False,
            "transport_success": False,
            "terminated_reason": "grasp_not_verified",
        }
        _save_result(output_dir, frames, result)
        return result

    # Retract the grasped object toward the mobile base before driving.
    carry = np.array(
        [manipulation_dock[0], manipulation_dock[1] + source_sign * 0.30, 1.12]
    )
    retract_start = _tcp_pos(hand, local_point)
    retract_vertical = np.array(
        [retract_start[0], retract_start[1], max(retract_start[2], carry[2])]
    )
    phase_metrics["retract_vertical"] = _move_tcp_linear(
        scene, robot, arm_indices=arm_indices, finger_indices=finger_indices,
        hand=hand, local_point=local_point, start=retract_start,
        target=retract_vertical, quat=quat, steps=160, close=True,
        latch_object=latch_object,
    )
    phase_metrics["retract"] = _move_tcp_linear(
        scene, robot, arm_indices=arm_indices, finger_indices=finger_indices,
        hand=hand, local_point=local_point, start=retract_vertical,
        target=carry, quat=quat, steps=320, close=True,
        latch_object=latch_object,
    )
    object_carried = _entity_pos(pick_object)
    frames.extend([grasp_camera.render(rgb=True)[0]] * 8)
    frames.append(_capture_key_frame(output_dir, "06_retracted_carry", grasp_camera))
    carried_distance = float(
        np.linalg.norm(object_carried - _tcp_pos(hand, local_point))
    )
    if carried_distance > 0.25:
        result = {
            "backend": "gpu",
            "seed": seed,
            "object_id": task.object_id,
            "source_zone": task.source_zone,
            "target_zone": task.target_zone,
            "start_xy": task.start_xy,
            "dock_target_xy": dock.tolist(),
            "dock_error_m": dock_error,
            "object_before_xyz": object_before.tolist(),
            "object_after_xyz": object_after.tolist(),
            "object_lift_m": lift_m,
            "retry_count": retry_count,
            "grasp_yaw_deg": grasp_yaw_deg,
            "grasp_z_offset_m": grasp_z_offset_m,
            "object_carried_xyz": object_carried.tolist(),
            "phase_metrics": phase_metrics,
            "grasp_success": True,
            "place_success": False,
            "transport_success": False,
            "terminated_reason": "payload_lost_during_retract",
        }
        _save_result(output_dir, frames, result)
        return result

    # Carry the object along the second A* leg while holding arm pose and grip force.
    arm_hold = (
        robot.get_dofs_position(arm_indices).detach().cpu().numpy().reshape(-1)
    )
    # Back out from the furniture to the navigation dock before following A*.
    retreat_base = np.array(
        [dock[0] - start[0], dock[1] - start[1], source_sign * np.pi / 2]
    )
    for _ in range(300):
        robot.control_dofs_position(retreat_base, base_indices)
        robot.control_dofs_position(arm_hold, arm_indices)
        robot.control_dofs_force(
            np.array([CLOSE_FORCE, CLOSE_FORCE]), finger_indices
        )
        scene.step()
        if latch_object is not None:
            latch_object.set_pos(_tcp_pos(hand, local_point))
    current = grid.cell_to_world(plan.delivery_path[0])
    yaw_current = source_sign * np.pi / 2
    payload_lost = False
    for cell in plan.delivery_path[1:]:
        nxt = grid.cell_to_world(cell)
        delta = np.asarray(nxt) - np.asarray(current)
        yaw_target = float(np.arctan2(delta[1], delta[0]))
        yaw_delta = float(
            np.arctan2(
                np.sin(yaw_target - yaw_current),
                np.cos(yaw_target - yaw_current),
            )
        )
        for alpha in np.linspace(0.0, 1.0, 80):
            world = np.asarray(current) * (1.0 - alpha) + np.asarray(nxt) * alpha
            base_command = np.array(
                [
                    world[0] - start[0],
                    world[1] - start[1],
                    yaw_current + yaw_delta * alpha,
                ]
            )
            robot.control_dofs_position(base_command, base_indices)
            robot.control_dofs_position(arm_hold, arm_indices)
            robot.control_dofs_force(
                np.array([CLOSE_FORCE, CLOSE_FORCE]), finger_indices
            )
            scene.step()
            if latch_object is not None:
                latch_object.set_pos(_tcp_pos(hand, local_point))
        current = nxt
        yaw_current = yaw_target
        frames.append(camera.render(rgb=True)[0])
        payload_distance = float(
            np.linalg.norm(_entity_pos(pick_object) - _tcp_pos(hand, local_point))
        )
        if payload_distance > 0.25:
            payload_lost = True
            break

    if payload_lost:
        result = {
            "backend": "gpu",
            "seed": seed,
            "object_id": task.object_id,
            "source_zone": task.source_zone,
            "target_zone": task.target_zone,
            "start_xy": task.start_xy,
            "dock_target_xy": dock.tolist(),
            "dock_error_m": dock_error,
            "object_before_xyz": object_before.tolist(),
            "object_after_xyz": object_after.tolist(),
            "object_lift_m": lift_m,
            "retry_count": retry_count,
            "grasp_yaw_deg": grasp_yaw_deg,
            "grasp_z_offset_m": grasp_z_offset_m,
            "object_carried_xyz": object_carried.tolist(),
            "object_lost_xyz": _entity_pos(pick_object).tolist(),
            "phase_metrics": phase_metrics,
            "grasp_success": True,
            "place_success": False,
            "transport_success": False,
            "terminated_reason": "payload_lost_during_transport",
        }
        _save_result(output_dir, frames, result)
        return result

    delivery_dock = np.asarray(SEMANTIC_DOCKS[task.target_zone])
    delivery_sign = 1.0 if delivery_dock[1] > 0 else -1.0
    base_command = np.array(
        [
            delivery_dock[0] - start[0],
            delivery_dock[1] - start[1],
            delivery_sign * np.pi / 2,
        ]
    )
    for _ in range(250):
        robot.control_dofs_position(base_command, base_indices)
        robot.control_dofs_position(arm_hold, arm_indices)
        robot.control_dofs_force(
            np.array([CLOSE_FORCE, CLOSE_FORCE]), finger_indices
        )
        scene.step()
        if latch_object is not None:
            latch_object.set_pos(_tcp_pos(hand, local_point))
    delivery_dock_error = float(
        np.linalg.norm(_measured_xy(robot) - delivery_dock)
    )
    manipulation_delivery = delivery_dock + np.array(
        [0.0, delivery_sign * 0.15]
    )
    delivery_approach = np.array(
        [
            manipulation_delivery[0] - start[0],
            manipulation_delivery[1] - start[1],
            delivery_sign * np.pi / 2,
        ]
    )
    for _ in range(220):
        robot.control_dofs_position(delivery_approach, base_indices)
        robot.control_dofs_position(arm_hold, arm_indices)
        robot.control_dofs_force(
            np.array([CLOSE_FORCE, CLOSE_FORCE]), finger_indices
        )
        scene.step()
        if latch_object is not None:
            latch_object.set_pos(_tcp_pos(hand, local_point))
    frames.extend([camera.render(rgb=True)[0]] * 6)
    frames.append(_capture_key_frame(output_dir, "07_delivery_dock", camera))

    # Lower the grasp target onto the destination surface, then release.
    place_xy = np.array(
        [delivery_dock[0], delivery_dock[1] + delivery_sign * 0.58]
    )
    place_above = np.array([place_xy[0], place_xy[1], 0.72])
    place = np.array([place_xy[0], place_xy[1], 0.51])
    phase_metrics["place_above"] = _move_arm(
        scene, robot, arm_indices=arm_indices, finger_indices=finger_indices,
        hand=hand, local_point=local_point, target=place_above, quat=quat,
        steps=180, close=True, latch_object=latch_object,
    )
    phase_metrics["place"] = _move_arm(
        scene, robot, arm_indices=arm_indices, finger_indices=finger_indices,
        hand=hand, local_point=local_point, target=place, quat=quat,
        steps=120, close=True, latch_object=latch_object,
    )
    arm_release = (
        robot.get_dofs_position(arm_indices).detach().cpu().numpy().reshape(-1)
    )
    for _ in range(120):
        robot.control_dofs_position(arm_release, arm_indices)
        robot.control_dofs_position(np.array([OPEN, OPEN]), finger_indices)
        scene.step()
    object_placed = _entity_pos(pick_object)
    frames.extend([camera.render(rgb=True)[0]] * 12)
    frames.append(_capture_key_frame(output_dir, "08_final_place", camera))

    place_xy_error = float(np.linalg.norm(object_placed[:2] - place_xy))
    released_drop_m = float(object_carried[2] - object_placed[2])
    place_success = place_xy_error <= 0.20 and released_drop_m >= 0.10
    result = {
        "backend": "gpu",
        "seed": seed,
        "object_id": task.object_id,
        "source_zone": task.source_zone,
        "target_zone": task.target_zone,
        "start_xy": task.start_xy,
        "dock_target_xy": dock.tolist(),
        "dock_error_m": dock_error,
        "delivery_dock_error_m": delivery_dock_error,
        "object_before_xyz": object_before.tolist(),
        "object_after_xyz": object_after.tolist(),
        "object_lift_m": lift_m,
        "retry_count": retry_count,
        "grasp_yaw_deg": grasp_yaw_deg,
        "grasp_z_offset_m": grasp_z_offset_m,
        "grasp_mode": "verified_latch" if grasp_latch else "physical_contact",
        "object_carried_xyz": object_carried.tolist(),
        "object_placed_xyz": object_placed.tolist(),
        "place_target_xy": place_xy.tolist(),
        "place_xy_error_m": place_xy_error,
        "released_drop_m": released_drop_m,
        "phase_metrics": phase_metrics,
        "grasp_success": grasp_success,
        "place_success": place_success,
        "transport_success": grasp_success and place_success,
    }
    _save_result(output_dir, frames, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Run mobile pick-and-lift")
    parser.add_argument("--seed", type=int, default=20260729)
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/mobile-grasp"))
    parser.add_argument(
        "--grasp-latch",
        action="store_true",
        help="Use a disclosed task-level grasp constraint after close-pose verification",
    )
    parser.add_argument(
        "--grasp-yaw-deg",
        type=float,
        default=45.0,
        help="Link-7 yaw candidate used by the physical grasp controller",
    )
    parser.add_argument(
        "--grasp-z-offset-m",
        type=float,
        default=0.0,
        help="Vertical TCP offset from the observed object centre",
    )
    parser.add_argument(
        "--grasp-probe-only",
        action="store_true",
        help="Stop after recording physical finger-contact diagnostics",
    )
    args = parser.parse_args()
    gs.init(backend=gs.gpu, seed=0)
    run_mobile_grasp(
        seed=args.seed,
        output_dir=args.output_dir,
        grasp_latch=args.grasp_latch,
        grasp_yaw_deg=args.grasp_yaw_deg,
        grasp_z_offset_m=args.grasp_z_offset_m,
        grasp_probe_only=args.grasp_probe_only,
    )


if __name__ == "__main__":
    main()
