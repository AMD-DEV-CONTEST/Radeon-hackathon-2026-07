#!/usr/bin/env python3
"""Run one guarded Mantis bowl contact/grasp/lift smoke in Genesis.

The probe preserves the earliest failure stage and never claims a complete
``stack_bowls_three`` episode.  Bowl motion is caused only by simulated contact;
objects are never teleported after reset.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import math
from pathlib import Path
from typing import Any

from mantis_rocm_bridge.contracts import load_json, validate_contract_pair
from mantis_rocm_bridge.genesis_smoke import BACKENDS, physical_pose, resolve_backend, sha256_file
from mantis_rocm_bridge.ops import begin_run, finish_run
from mantis_rocm_bridge.stack_bowls_env import (
    arm_dof_names,
    arm_for_bowl_x,
    sample_source_reset_poses,
    validate_genesis_scene_contract,
)


ROOT = Path(__file__).resolve().parents[1]


def _vector(value: Any) -> list[float]:
    if hasattr(value, "detach"):
        value = value.detach()
    if hasattr(value, "cpu"):
        value = value.cpu()
    if hasattr(value, "numpy"):
        value = value.numpy()
    import numpy as np

    return np.asarray(value, dtype=float).reshape(-1).tolist()


def _dof_indices(robot: Any, names: list[str]) -> list[int]:
    result: list[int] = []
    for name in names:
        indices = _vector(robot.get_joint(name).dofs_idx_local)
        if len(indices) != 1:
            raise RuntimeError(f"expected one DOF for {name}, got {indices}")
        result.append(int(indices[0]))
    return result


def _max_error(actual: list[float], target: list[float], indices: list[int]) -> float:
    return max(abs(actual[index] - target[index]) for index in indices)


def _contact_count(contact_info: Any) -> int:
    """Count Genesis contact rows, not keys in its returned dictionary."""

    if not isinstance(contact_info, dict) or "geom_a" not in contact_info:
        raise RuntimeError("Genesis get_contacts returned an unexpected structure")
    geom_a = contact_info["geom_a"]
    if not hasattr(geom_a, "shape") or len(geom_a.shape) < 1:
        raise RuntimeError("Genesis contact geom_a has no row dimension")
    return int(geom_a.shape[-1] if len(geom_a.shape) > 1 else geom_a.shape[0])


def _record_contact_pairs(
    contact_info: Any,
    geom_labels: dict[int, str],
    histogram: dict[str, int],
) -> None:
    """Accumulate contacted geometry pairs using Genesis' global geom indices."""

    for geom_a, geom_b in zip(
        _vector(contact_info["geom_a"]),
        _vector(contact_info["geom_b"]),
    ):
        index_a = int(geom_a)
        index_b = int(geom_b)
        label_a = geom_labels.get(index_a, f"geom:{index_a}")
        label_b = geom_labels.get(index_b, f"geom:{index_b}")
        pair = " <> ".join(sorted((label_a, label_b)))
        histogram[pair] = histogram.get(pair, 0) + 1


def _tcp_world_position(link: Any, local_point: Any) -> list[float]:
    """Transform a link-local TCP point to world coordinates from readback state."""

    import numpy as np

    position = np.asarray(_vector(link.get_pos()), dtype=float)
    quaternion = np.asarray(_vector(link.get_quat()), dtype=float)
    point = np.asarray(local_point, dtype=float)
    vector = quaternion[1:]
    twice_cross = 2.0 * np.cross(vector, point)
    rotated = point + quaternion[0] * twice_cross + np.cross(vector, twice_cross)
    return (position + rotated).tolist()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mantis_urdf", type=Path)
    parser.add_argument("bowl_asset_root", type=Path)
    parser.add_argument(
        "--scene-contract",
        type=Path,
        default=ROOT / "configs/stack-bowls-genesis-v1.json",
    )
    parser.add_argument("--port", type=Path, default=ROOT / "configs/mantis-port-config.json")
    parser.add_argument(
        "--source-task",
        type=Path,
        default=ROOT / "configs/source-task-stack-bowls-three.json",
    )
    parser.add_argument("--task", type=Path, default=ROOT / "configs/task-pack-v1.json")
    parser.add_argument("--ops-root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--backend", choices=BACKENDS, required=True)
    args = parser.parse_args()

    bowl_urdf = args.bowl_asset_root / "urdf/robotwin_002_bowl_model3.urdf"
    bowl_manifest_path = args.bowl_asset_root / "manifest.json"
    for path in (args.mantis_urdf, bowl_urdf, bowl_manifest_path):
        if not path.is_file():
            parser.error(f"required asset file does not exist: {path}")

    port = load_json(args.port)
    source_task = load_json(args.source_task)
    task = load_json(args.task)
    scene_contract = load_json(args.scene_contract)
    bowl_manifest = load_json(bowl_manifest_path)
    validate_contract_pair(port, task, source_task)
    validate_genesis_scene_contract(scene_contract, source_task, port)
    if bowl_manifest.get("distribution_allowed") is not True:
        raise RuntimeError("bowl materialization is not licensed for distribution")

    contact_contract = scene_contract["contact_probe"]
    if contact_contract.get("claim_boundary") != (
        "single-bowl contact smoke only; not a complete episode or G1"
    ):
        raise RuntimeError("contact probe claim boundary changed")
    seed = int(contact_contract["seed"])
    reset = sample_source_reset_poses(seed=seed)
    selected_pose = next(pose for pose in reset if pose.name == contact_contract["bowl"])
    side = arm_for_bowl_x(selected_pose.position_xyz_m[0])
    base = scene_contract["world"]["mantis_base"]
    tcp = scene_contract["tcp"]
    ik = scene_contract["ik_gate"]
    run_dir = args.ops_root / args.run_id
    begun = False
    receipt_written = False

    try:
        begin_run(
            args.ops_root,
            args.run_id,
            {
                "phase": "genesis_single_bowl_contact_probe",
                "protocol_version": contact_contract["protocol_version"],
                "seed": seed,
                "bowl": selected_pose.name,
                "side": side,
                "backend": args.backend,
                "scene_contract_sha256": sha256_file(args.scene_contract),
                "port_config_sha256": sha256_file(args.port),
                "mantis_urdf_sha256": sha256_file(args.mantis_urdf),
                "bowl_urdf_sha256": sha256_file(bowl_urdf),
            },
        )
        begun = True
        import genesis as gs
        import numpy as np

        dt = float(scene_contract["control"]["physics_dt_s"])
        gs.init(backend=resolve_backend(gs, args.backend), seed=seed, logging_level="warning")
        scene = gs.Scene(sim_options=gs.options.SimOptions(dt=dt), show_viewer=False)
        table = scene.add_entity(
            gs.morphs.Plane(
                pos=(0.0, 0.0, float(scene_contract["world"]["table_plane_z_m"])),
                fixed=True,
            )
        )
        robot = scene.add_entity(
            gs.morphs.URDF(
                file=str(args.mantis_urdf.resolve()),
                pos=tuple(base["position_xyz_m"]),
                quat=tuple(base["quaternion_wxyz"]),
                fixed=True,
            )
        )
        bowls = [
            scene.add_entity(
                gs.morphs.URDF(
                    file=str(bowl_urdf.resolve()),
                    pos=pose.position_xyz_m,
                    quat=pose.quaternion_wxyz,
                    fixed=False,
                    merge_fixed_links=False,
                    recompute_inertia=False,
                    file_meshes_are_zup=True,
                ),
                name=pose.name,
            )
            for pose in reset
        ]
        selected_bowl = bowls[[pose.name for pose in reset].index(selected_pose.name)]
        scene.build()

        geom_labels = {
            int(geom.idx): f"mantis:{geom.link.name}" for geom in robot.geoms
        }
        geom_labels.update(
            {int(geom.idx): f"table:{geom.link.name}" for geom in table.geoms}
        )
        geom_labels.update(
            {int(geom.idx): f"bowl1:{geom.link.name}" for geom in selected_bowl.geoms}
        )
        selected_bowl.set_friction(float(contact_contract["bowl_friction_coefficient"]))
        finger_geom_labels: list[str] = []
        finger_link_prefix = f"{side}_clamp"
        for geom in robot.geoms:
            if geom.link.name.startswith(finger_link_prefix):
                geom.set_friction(float(contact_contract["finger_friction_coefficient"]))
                finger_geom_labels.append(geom_labels[int(geom.idx)])
        if not finger_geom_labels:
            raise RuntimeError(f"no Genesis finger geoms found for {side}")

        physical_names = port["target"]["physical_joint_order"]
        all_indices = _dof_indices(robot, physical_names)
        side_arm_indices = _dof_indices(robot, arm_dof_names(side))
        side_gripper_names = list(
            port["assets"]["virtual_gripper_mapping"]["coefficients"][f"{side}_gripper_joint"]
        )
        side_gripper_indices = _dof_indices(robot, side_gripper_names)
        arm_index_set = set(all_indices) - set(
            _dof_indices(robot, port["assets"]["physical_gripper_joint_order"])
        )
        gripper_index_set = set(all_indices) - arm_index_set
        kp = [
            float(contact_contract["arm_kp"] if index in arm_index_set else contact_contract["gripper_kp"])
            for index in all_indices
        ]
        kv = [
            float(contact_contract["arm_kv"] if index in arm_index_set else contact_contract["gripper_kv"])
            for index in all_indices
        ]
        lower_force = [
            -float(
                contact_contract["arm_force_limit"]
                if index in arm_index_set
                else contact_contract["gripper_force_limit"]
            )
            for index in all_indices
        ]
        upper_force = [-value for value in lower_force]
        robot.set_dofs_kp(kp, dofs_idx_local=all_indices)
        robot.set_dofs_kv(kv, dofs_idx_local=all_indices)
        robot.set_dofs_force_range(lower_force, upper_force, dofs_idx_local=all_indices)

        open_qpos = np.asarray(physical_pose(port, 1.0), dtype=float)
        closed_qpos = np.asarray(physical_pose(port, 0.0), dtype=float)
        robot.set_qpos(open_qpos)
        robot.control_dofs_position(open_qpos, dofs_idx_local=all_indices)
        for _ in range(25):
            scene.step()

        target_x, target_y, _ = selected_pose.position_xyz_m
        grasp_position = np.asarray(
            [
                target_x,
                target_y + float(contact_contract["grasp_center_y_offset_m"]),
                float(contact_contract["grasp_tcp_z_m"]),
            ]
        )
        pregrasp_position = grasp_position.copy()
        pregrasp_position[2] += float(contact_contract["pregrasp_retreat_z_m"])
        front_clearance_position = np.asarray(
            [
                target_x,
                float(contact_contract["transit_front_y_m"]),
                float(contact_contract["transit_clearance_z_m"]),
            ]
        )
        rim_clearance_position = np.asarray(
            [
                target_x,
                grasp_position[1],
                float(contact_contract["transit_clearance_z_m"]),
            ]
        )
        lift_position = grasp_position.copy()
        lift_position[2] += float(contact_contract["lift_distance_m"])
        vertical_lift_position = grasp_position.copy()
        vertical_lift_position[2] += float(contact_contract["vertical_lift_distance_m"])
        orientation = np.asarray(contact_contract["orientation_wxyz"], dtype=float)
        transit_orientation = np.asarray(
            contact_contract["transit_orientation_wxyz"], dtype=float
        )
        pregrasp_orientation = np.asarray(
            contact_contract["pregrasp_orientation_wxyz"], dtype=float
        )
        lift_orientation = np.asarray(contact_contract["lift_orientation_wxyz"], dtype=float)
        link = robot.get_link(tcp[side]["link"])
        local_point = np.asarray(tcp[side]["local_point_xyz_m"], dtype=float)
        tcp_world_position_by_stage = {
            "initial": _tcp_world_position(link, local_point)
        }

        def solve(target: Any, initial: Any, target_orientation: Any = orientation) -> np.ndarray:
            attempts: list[tuple[float, float, np.ndarray, list[float]]] = []
            for candidate_initial in (initial, open_qpos):
                qpos, error = robot.inverse_kinematics(
                    link,
                    pos=target,
                    quat=target_orientation,
                    local_point=local_point,
                    init_qpos=candidate_initial,
                    respect_joint_limit=True,
                    max_samples=int(ik["max_samples"]),
                    max_solver_iters=int(ik["max_solver_iters"]),
                    dofs_idx_local=side_arm_indices,
                    return_error=True,
                )
                error_vector = _vector(error)
                position_error = math.sqrt(sum(value * value for value in error_vector[:3]))
                rotation_error = math.sqrt(sum(value * value for value in error_vector[3:]))
                attempts.append(
                    (position_error, rotation_error, np.asarray(_vector(qpos), dtype=float), error_vector)
                )
                if position_error <= float(ik["position_tolerance_m"]) and rotation_error <= float(
                    ik["rotation_tolerance_rad"]
                ):
                    return attempts[-1][2]
            best = min(attempts, key=lambda attempt: (attempt[0], attempt[1]))
            raise RuntimeError(f"IK error exceeds tolerance after fallback: {best[3]}")

        front_clearance_qpos = solve(front_clearance_position, open_qpos, transit_orientation)
        rim_clearance_qpos = solve(
            rim_clearance_position, front_clearance_qpos, transit_orientation
        )
        pregrasp_qpos = solve(
            pregrasp_position, rim_clearance_qpos, pregrasp_orientation
        )
        grasp_qpos = solve(grasp_position, pregrasp_qpos)
        vertical_lift_qpos = solve(vertical_lift_position, grasp_qpos)
        lift_tilt_qpos = solve(vertical_lift_position, vertical_lift_qpos, lift_orientation)
        lift_qpos = solve(lift_position, lift_tilt_qpos, lift_orientation)
        for index in side_gripper_indices:
            front_clearance_qpos[index] = open_qpos[index]
            rim_clearance_qpos[index] = open_qpos[index]
            pregrasp_qpos[index] = open_qpos[index]
            grasp_qpos[index] = open_qpos[index]
            vertical_lift_qpos[index] = closed_qpos[index]
            lift_tilt_qpos[index] = closed_qpos[index]
            lift_qpos[index] = closed_qpos[index]

        sample_interval = int(contact_contract["contact_sample_interval_steps"])
        contact_counts: dict[str, list[int]] = {
            stage: []
            for stage in (
                "front_clearance",
                "rim_clearance",
                "pregrasp",
                "approach",
                "close",
                "hold",
                "lift_vertical",
                "lift_tilt",
                "lift",
            )
        }
        contact_pair_rows_by_stage: dict[str, dict[str, int]] = {
            stage: {} for stage in contact_counts
        }
        table_contact_pair_rows_by_stage: dict[str, dict[str, int]] = {
            stage: {} for stage in contact_counts
        }
        table_contacts: dict[str, list[int]] = {stage: [] for stage in contact_counts}
        final_arm_tracking_error: dict[str, float] = {}
        final_gripper_tracking_error: dict[str, float] = {}
        bowl_position_by_stage = {"initial": _vector(selected_bowl.get_pos())}

        def command_segment(
            stage: str,
            target: np.ndarray,
            minimum_duration_s: float,
            sample_contact: bool,
        ) -> None:
            start = np.asarray(_vector(robot.get_qpos()), dtype=float)
            velocity_limits = np.ones(len(start), dtype=float)
            for index in gripper_index_set:
                velocity_limits[index] = 0.0376
            duration = max(
                float(minimum_duration_s),
                max(abs(target[index] - start[index]) / velocity_limits[index] for index in all_indices),
            )
            steps = max(1, int(math.ceil(duration / dt)))
            for step in range(1, steps + 1):
                alpha = step / steps
                command = start + alpha * (target - start)
                robot.control_dofs_position(command, dofs_idx_local=all_indices)
                scene.step()
                if sample_contact and (step % sample_interval == 0 or step == steps):
                    bowl_contact_info = robot.get_contacts(with_entity=selected_bowl)
                    contact_counts[stage].append(_contact_count(bowl_contact_info))
                    _record_contact_pairs(
                        bowl_contact_info,
                        geom_labels,
                        contact_pair_rows_by_stage[stage],
                    )
                    table_contact_info = robot.get_contacts(with_entity=table)
                    table_contacts[stage].append(_contact_count(table_contact_info))
                    _record_contact_pairs(
                        table_contact_info,
                        geom_labels,
                        table_contact_pair_rows_by_stage[stage],
                    )
            required = int(contact_contract["waypoint_settle_consecutive_steps"])
            settle_steps = max(
                1,
                int(math.ceil(float(contact_contract["waypoint_settle_timeout_s"]) / dt)),
            )
            consecutive = 0
            for settle_step in range(1, settle_steps + 1):
                robot.control_dofs_position(target, dofs_idx_local=all_indices)
                scene.step()
                if sample_contact and (
                    settle_step % sample_interval == 0 or settle_step == settle_steps
                ):
                    bowl_contact_info = robot.get_contacts(with_entity=selected_bowl)
                    contact_counts[stage].append(_contact_count(bowl_contact_info))
                    _record_contact_pairs(
                        bowl_contact_info,
                        geom_labels,
                        contact_pair_rows_by_stage[stage],
                    )
                    table_contact_info = robot.get_contacts(with_entity=table)
                    table_contacts[stage].append(_contact_count(table_contact_info))
                    _record_contact_pairs(
                        table_contact_info,
                        geom_labels,
                        table_contact_pair_rows_by_stage[stage],
                    )
                actual = _vector(robot.get_qpos())
                arm_error = _max_error(actual, target.tolist(), side_arm_indices)
                gripper_error = _max_error(actual, target.tolist(), side_gripper_indices)
                if arm_error <= float(contact_contract["maximum_arm_tracking_error_rad"]):
                    consecutive += 1
                    if consecutive >= required:
                        break
                else:
                    consecutive = 0
            actual = _vector(robot.get_qpos())
            final_arm_tracking_error[stage] = _max_error(
                actual, target.tolist(), side_arm_indices
            )
            final_gripper_tracking_error[stage] = _max_error(
                actual, target.tolist(), side_gripper_indices
            )
            tcp_world_position_by_stage[stage] = _tcp_world_position(link, local_point)
            bowl_position_by_stage[stage] = _vector(selected_bowl.get_pos())

        command_segment(
            "front_clearance",
            front_clearance_qpos,
            float(contact_contract["minimum_segment_duration_s"]),
            True,
        )
        command_segment(
            "rim_clearance",
            rim_clearance_qpos,
            float(contact_contract["minimum_segment_duration_s"]),
            True,
        )
        command_segment(
            "pregrasp",
            pregrasp_qpos,
            float(contact_contract["minimum_segment_duration_s"]),
            True,
        )
        command_segment(
            "approach",
            grasp_qpos,
            float(contact_contract["minimum_segment_duration_s"]),
            True,
        )
        bowl_z_before_close = float(_vector(selected_bowl.get_pos())[2])
        close_target = grasp_qpos.copy()
        for index in side_gripper_indices:
            close_target[index] = closed_qpos[index]
        command_segment(
            "close",
            close_target,
            float(contact_contract["gripper_close_duration_s"]),
            True,
        )
        hold_steps = max(1, int(math.ceil(float(contact_contract["post_close_hold_s"]) / dt)))
        for step in range(1, hold_steps + 1):
            robot.control_dofs_position(close_target, dofs_idx_local=all_indices)
            scene.step()
            if step % sample_interval == 0 or step == hold_steps:
                bowl_contact_info = robot.get_contacts(with_entity=selected_bowl)
                contact_counts["hold"].append(_contact_count(bowl_contact_info))
                _record_contact_pairs(
                    bowl_contact_info,
                    geom_labels,
                    contact_pair_rows_by_stage["hold"],
                )
                table_contact_info = robot.get_contacts(with_entity=table)
                table_contacts["hold"].append(_contact_count(table_contact_info))
                _record_contact_pairs(
                    table_contact_info,
                    geom_labels,
                    table_contact_pair_rows_by_stage["hold"],
                )
        final_arm_tracking_error["hold"] = _max_error(
            _vector(robot.get_qpos()), close_target.tolist(), side_arm_indices
        )
        final_gripper_tracking_error["hold"] = _max_error(
            _vector(robot.get_qpos()), close_target.tolist(), side_gripper_indices
        )
        tcp_world_position_by_stage["hold"] = _tcp_world_position(link, local_point)
        bowl_position_by_stage["hold"] = _vector(selected_bowl.get_pos())
        bowl_z_after_close = float(_vector(selected_bowl.get_pos())[2])

        lift_target = lift_qpos.copy()
        for index in side_gripper_indices:
            lift_target[index] = closed_qpos[index]
        command_segment(
            "lift_vertical",
            vertical_lift_qpos,
            float(contact_contract["vertical_lift_duration_s"]),
            True,
        )
        command_segment(
            "lift_tilt",
            lift_tilt_qpos,
            float(contact_contract["lift_tilt_duration_s"]),
            True,
        )
        command_segment(
            "lift",
            lift_target,
            float(contact_contract["lift_segment_duration_s"]),
            True,
        )
        bowl_position_after_lift = _vector(selected_bowl.get_pos())
        bowl_z_after_lift = float(bowl_position_after_lift[2])

        navigation_stages = ("front_clearance", "rim_clearance", "pregrasp")
        navigation_contact_failure_stage = next(
            (
                stage
                for stage in navigation_stages
                if max(contact_counts[stage], default=0) > 0
            ),
            None,
        )
        all_table_contacts = [count for values in table_contacts.values() for count in values]
        stage_order = (
            "front_clearance",
            "rim_clearance",
            "pregrasp",
            "approach",
            "close",
            "hold",
            "lift_vertical",
            "lift_tilt",
            "lift",
        )
        table_contact_failure_stage = next(
            (
                stage
                for stage in stage_order
                if max(table_contacts[stage], default=0) > 0
            ),
            None,
        )
        required_link = f"mantis:{side}_{contact_contract['required_contact_link_substring']}"

        def finger_contact(stage: str) -> bool:
            return any(required_link in pair for pair in contact_pair_rows_by_stage[stage])

        contact_observed = any(finger_contact(stage) for stage in ("approach", "close", "hold"))
        contact_held_after_close = finger_contact("hold")
        lift_delta = bowl_z_after_lift - bowl_z_before_close
        lift_pass = lift_delta >= float(contact_contract["minimum_lift_delta_m"])
        tracking_limit = float(contact_contract["maximum_arm_tracking_error_rad"])
        tracking_failure_stage = next(
            (
                stage
                for stage in (*navigation_stages, "lift_vertical", "lift_tilt", "lift")
                if final_arm_tracking_error.get(stage, math.inf) > tracking_limit
            ),
            None,
        )
        tracking_pass = tracking_failure_stage is None
        gripper_tracking_pass = max(
            (final_gripper_tracking_error[stage] for stage in navigation_stages),
            default=0.0,
        ) <= float(contact_contract["maximum_gripper_tracking_error_m"])
        table_collision_free = max(all_table_contacts, default=0) == 0
        finite = all(
            math.isfinite(value)
            for value in bowl_position_after_lift
            + [bowl_z_before_close, bowl_z_after_close, bowl_z_after_lift, lift_delta]
        )
        if table_contact_failure_stage is not None:
            failure_stage = f"safety_{table_contact_failure_stage}"
        elif tracking_failure_stage is not None:
            failure_stage = tracking_failure_stage
        elif navigation_contact_failure_stage is not None:
            failure_stage = navigation_contact_failure_stage
        elif not contact_observed:
            failure_stage = "contact"
        elif not gripper_tracking_pass:
            failure_stage = "grasp"
        elif not contact_held_after_close:
            failure_stage = "grasp"
        elif not lift_pass:
            failure_stage = "transport"
        elif not table_collision_free:
            failure_stage = "safety"
        elif not finite:
            failure_stage = "physics_divergence"
        else:
            failure_stage = None
        probe_pass = failure_stage is None

        receipt = {
            "schema_version": 1,
            "protocol_version": contact_contract["protocol_version"],
            "probe_pass": probe_pass,
            "failure_stage": failure_stage,
            "task_success_claim": False,
            "g1_claim": False,
            "backend_requested": args.backend,
            "backend_active": str(gs.backend),
            "device": str(gs.device),
            "genesis_version": importlib.metadata.version("genesis-world"),
            "seed": seed,
            "bowl": selected_pose.name,
            "side": side,
            "reset_position_xyz_m": list(selected_pose.position_xyz_m),
            "grasp_tcp_position_xyz_m": grasp_position.tolist(),
            "front_clearance_tcp_position_xyz_m": front_clearance_position.tolist(),
            "rim_clearance_tcp_position_xyz_m": rim_clearance_position.tolist(),
            "pregrasp_tcp_position_xyz_m": pregrasp_position.tolist(),
            "grasp_mode": contact_contract["grasp_mode"],
            "grasp_orientation_wxyz": orientation.tolist(),
            "transit_orientation_wxyz": transit_orientation.tolist(),
            "pregrasp_orientation_wxyz": pregrasp_orientation.tolist(),
            "lift_orientation_wxyz": lift_orientation.tolist(),
            "vertical_lift_tcp_position_xyz_m": vertical_lift_position.tolist(),
            "bowl_z_before_close_m": bowl_z_before_close,
            "bowl_z_after_close_m": bowl_z_after_close,
            "bowl_position_after_lift_m": bowl_position_after_lift,
            "lift_delta_m": lift_delta,
            "minimum_lift_delta_m": contact_contract["minimum_lift_delta_m"],
            "contact_counts": contact_counts,
            "contact_pair_rows_by_stage": contact_pair_rows_by_stage,
            "table_contact_pair_rows_by_stage": table_contact_pair_rows_by_stage,
            "bowl_position_by_stage_m": bowl_position_by_stage,
            "contact_observed": contact_observed,
            "contact_held_after_close": contact_held_after_close,
            "navigation_contact_failure_stage": navigation_contact_failure_stage,
            "table_contact_counts": table_contacts,
            "table_contact_failure_stage": table_contact_failure_stage,
            "tcp_world_position_by_stage_m": tcp_world_position_by_stage,
            "table_collision_free": table_collision_free,
            "final_arm_tracking_error_rad_by_stage": final_arm_tracking_error,
            "final_gripper_tracking_error_m_by_stage": final_gripper_tracking_error,
            "tracking_pass": tracking_pass,
            "gripper_tracking_pass": gripper_tracking_pass,
            "gripper_tracking_scope": contact_contract["gripper_tracking_scope"],
            "friction": {
                "bowl_coefficient": contact_contract["bowl_friction_coefficient"],
                "finger_coefficient": contact_contract["finger_friction_coefficient"],
                "finger_geoms": sorted(finger_geom_labels),
                "semantics": contact_contract["friction_semantics"],
            },
            "finite": finite,
            "scene_contract_sha256": sha256_file(args.scene_contract),
            "port_config_sha256": sha256_file(args.port),
            "mantis_urdf_sha256": sha256_file(args.mantis_urdf),
            "bowl_urdf_sha256": sha256_file(bowl_urdf),
            "bowl_manifest_sha256": sha256_file(bowl_manifest_path),
            "evidence_boundary": contact_contract["claim_boundary"],
        }
        receipt_path = run_dir / "receipt.json"
        receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        receipt_written = True
        receipt_hash = sha256_file(receipt_path)
        finish_run(
            args.ops_root,
            args.run_id,
            "completed" if probe_pass else "failed",
            {
                "receipt_sha256": receipt_hash,
                "failure_stage": failure_stage,
                "lift_delta_m": lift_delta,
            },
        )
        print(json.dumps(receipt, indent=2, sort_keys=True))
        return 0 if probe_pass else 2
    except Exception as exc:
        if begun and not receipt_written:
            finish_run(
                args.ops_root,
                args.run_id,
                "failed",
                {"error_type": type(exc).__name__, "message": str(exc)},
            )
        raise


if __name__ == "__main__":
    raise SystemExit(main())
