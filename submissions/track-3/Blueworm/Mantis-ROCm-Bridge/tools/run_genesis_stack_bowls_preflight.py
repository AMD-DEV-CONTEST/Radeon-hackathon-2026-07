#!/usr/bin/env python3
"""Run deterministic reset and Mantis IK preflight for ``stack_bowls_three``.

This is a pre-G1 check, not a task-success rollout.  It never moves a bowl
after reset and records every failed IK probe before returning non-zero.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import math
import platform
from pathlib import Path
from typing import Any

from mantis_rocm_bridge.camera_mounts import genesis_wrist_mounts
from mantis_rocm_bridge.contracts import load_json, validate_contract_pair
from mantis_rocm_bridge.genesis_smoke import BACKENDS, resolve_backend, sha256_file
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


def _parse_seeds(raw: str) -> list[int]:
    try:
        seeds = [int(item.strip()) for item in raw.split(",") if item.strip()]
    except ValueError as exc:
        raise argparse.ArgumentTypeError("seeds must be comma-separated integers") from exc
    if not seeds:
        raise argparse.ArgumentTypeError("at least one seed is required")
    if len(seeds) != len(set(seeds)):
        raise argparse.ArgumentTypeError("seeds must be unique")
    return seeds


def _quat_error(left: list[float], right: list[float]) -> float:
    direct = math.sqrt(sum((a - b) ** 2 for a, b in zip(left, right)))
    antipodal = math.sqrt(sum((a + b) ** 2 for a, b in zip(left, right)))
    return min(direct, antipodal)


def _dof_indices(robot: Any, side: str) -> list[int]:
    result: list[int] = []
    for name in arm_dof_names(side):
        indices = _vector(robot.get_joint(name).dofs_idx_local)
        if len(indices) != 1:
            raise RuntimeError(f"expected one DOF for {name}, got {indices}")
        result.append(int(indices[0]))
    return result


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
    parser.add_argument(
        "--cameras",
        type=Path,
        default=ROOT / "configs/camera-extrinsics-v1.json",
    )
    parser.add_argument("--ops-root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--backend", choices=BACKENDS, required=True)
    parser.add_argument("--seeds", type=_parse_seeds, default=_parse_seeds("0,1,42,20260722"))
    parser.add_argument("--settle-steps", type=int, default=10)
    args = parser.parse_args()
    if args.settle_steps < 1:
        parser.error("--settle-steps must be positive")

    bowl_urdf = args.bowl_asset_root / "urdf/robotwin_002_bowl_model3.urdf"
    bowl_manifest_path = args.bowl_asset_root / "manifest.json"
    for path in (args.mantis_urdf, bowl_urdf, bowl_manifest_path):
        if not path.is_file():
            parser.error(f"required asset file does not exist: {path}")

    port = load_json(args.port)
    source_task = load_json(args.source_task)
    task = load_json(args.task)
    cameras = load_json(args.cameras)
    scene_contract = load_json(args.scene_contract)
    bowl_manifest = load_json(bowl_manifest_path)
    validate_contract_pair(port, task, source_task)
    validate_genesis_scene_contract(scene_contract, source_task, port)
    if bowl_manifest.get("distribution_allowed") is not True:
        raise RuntimeError("bowl materialization is not licensed for distribution")
    if scene_contract.get("scene_id") != "mantis_stack_bowls_three_genesis_v1":
        raise RuntimeError("unexpected Genesis scene contract")

    reset_by_seed = {
        str(seed): [pose.as_dict() for pose in sample_source_reset_poses(seed=seed)]
        for seed in args.seeds
    }
    first_seed = args.seeds[0]
    first_reset = sample_source_reset_poses(seed=first_seed)
    base = scene_contract["world"]["mantis_base"]
    tcp = scene_contract["tcp"]
    ik_contract = scene_contract["ik_gate"]
    mounts = genesis_wrist_mounts(cameras)
    run_dir = args.ops_root / args.run_id
    begun = False
    receipt_written = False

    try:
        begin_run(
            args.ops_root,
            args.run_id,
            {
                "phase": "genesis_stack_bowls_pre_g1_reset_and_ik",
                "backend": args.backend,
                "seeds": args.seeds,
                "port_config_sha256": sha256_file(args.port),
                "source_task_contract_sha256": sha256_file(args.source_task),
                "target_task_contract_sha256": sha256_file(args.task),
                "scene_contract_sha256": sha256_file(args.scene_contract),
                "mantis_urdf_sha256": sha256_file(args.mantis_urdf),
                "bowl_urdf_sha256": sha256_file(bowl_urdf),
                "bowl_manifest_sha256": sha256_file(bowl_manifest_path),
                "camera_contract_sha256": sha256_file(args.cameras),
            },
        )
        begun = True

        import genesis as gs
        import numpy as np

        gs.init(backend=resolve_backend(gs, args.backend), seed=first_seed, logging_level="warning")
        scene = gs.Scene(
            sim_options=gs.options.SimOptions(dt=float(scene_contract["control"]["physics_dt_s"])),
            show_viewer=False,
        )
        scene.add_entity(
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
            for pose in first_reset
        ]

        env = cameras["mounts"]["env_cam"]
        env_position = np.asarray(env["position_xyz_m"], dtype=float)
        env_forward = np.asarray(env["forward_xyz"], dtype=float)
        scene.add_camera(
            res=(320, 240),
            pos=tuple(env_position),
            lookat=tuple(env_position + env_forward),
            fov=37.0,
            near=0.1,
            far=100.0,
            GUI=False,
        )
        attached: dict[str, str] = {}
        for name in ("left_wrist_cam", "right_wrist_cam"):
            camera = scene.add_camera(
                res=(424, 240),
                pos=(0.0, 0.0, 1.0),
                lookat=(0.0, 0.0, 0.0),
                fov=37.0,
                near=0.1,
                far=100.0,
                GUI=False,
            )
            parent = mounts[name]["parent"]
            camera.attach(robot.get_link(parent), np.asarray(mounts[name]["offset_T"], dtype=float))
            attached[name] = parent

        scene.build()
        initial_positions = [_vector(bowl.get_pos()) for bowl in bowls]
        requested_positions = [list(pose.position_xyz_m) for pose in first_reset]
        reset_readback_max_error = max(
            abs(actual - expected)
            for actual_row, expected_row in zip(initial_positions, requested_positions)
            for actual, expected in zip(actual_row, expected_row)
        )
        actual_base_position = _vector(robot.get_pos())
        actual_base_quaternion = _vector(robot.get_quat())
        base_position_error = max(
            abs(actual - expected)
            for actual, expected in zip(actual_base_position, base["position_xyz_m"])
        )
        base_quaternion_error = _quat_error(actual_base_quaternion, base["quaternion_wxyz"])

        for _ in range(args.settle_steps):
            scene.step()
        settled_positions = [_vector(bowl.get_pos()) for bowl in bowls]
        table_contact_pass = all(
            all(math.isfinite(value) for value in position) and 0.70 < position[2] < 0.77
            for position in settled_positions
        )

        neutral_qpos = np.asarray(_vector(robot.get_qpos()), dtype=float)
        arm_indices = {side: _dof_indices(robot, side) for side in ("left", "right")}
        orientation = np.asarray(tcp["orientation_wxyz"], dtype=float)
        probes: list[dict[str, object]] = []

        probe_specs: list[tuple[str, str, list[float]]] = []
        grasp_z = float(ik_contract["bowl_tcp_z_m"])
        retreat_y = float(ik_contract["pregrasp_retreat_y_m"])
        for seed in args.seeds:
            for pose in sample_source_reset_poses(seed=seed):
                x, y, _ = pose.position_xyz_m
                side = arm_for_bowl_x(x)
                probe_specs.append(
                    (f"seed_{seed}_{pose.name}_pregrasp", side, [x, y - retreat_y, grasp_z])
                )
                probe_specs.append(
                    (f"seed_{seed}_{pose.name}_grasp", side, [x, y, grasp_z])
                )
        target_x, target_y = scene_contract["world"]["target_xy_m"]
        for z in ik_contract["stack_target_z_m"]:
            for side in ("left", "right"):
                probe_specs.append((f"stack_z_{float(z):.3f}_{side}", side, [target_x, target_y, z]))

        position_tolerance = float(ik_contract["position_tolerance_m"])
        rotation_tolerance = float(ik_contract["rotation_tolerance_rad"])
        for name, side, target_position in probe_specs:
            robot.set_qpos(neutral_qpos)
            indices = arm_indices[side]
            qpos, error = robot.inverse_kinematics(
                robot.get_link(tcp[side]["link"]),
                pos=np.asarray(target_position, dtype=float),
                quat=orientation,
                local_point=np.asarray(tcp[side]["local_point_xyz_m"], dtype=float),
                init_qpos=neutral_qpos,
                respect_joint_limit=bool(ik_contract["respect_joint_limits"]),
                max_samples=int(ik_contract["max_samples"]),
                max_solver_iters=int(ik_contract["max_solver_iters"]),
                dofs_idx_local=indices,
                return_error=True,
            )
            error_vector = _vector(error)
            position_error = math.sqrt(sum(value * value for value in error_vector[:3]))
            rotation_error = math.sqrt(sum(value * value for value in error_vector[3:]))
            qpos_vector = _vector(qpos)
            finite = all(math.isfinite(value) for value in error_vector + qpos_vector)
            passed = (
                finite
                and position_error <= position_tolerance
                and rotation_error <= rotation_tolerance
            )
            probes.append(
                {
                    "name": name,
                    "side": side,
                    "target_tcp_position_xyz_m": target_position,
                    "target_tcp_quaternion_wxyz": orientation.tolist(),
                    "position_error_m": position_error,
                    "rotation_error_rad": rotation_error,
                    "arm_qpos_rad": [qpos_vector[index] for index in indices],
                    "finite": finite,
                    "pass": passed,
                }
            )

        reset_gate_pass = reset_readback_max_error <= 1e-6 and table_contact_pass
        base_pose_gate_pass = base_position_error <= 1e-6 and base_quaternion_error <= 1e-6
        ik_gate_pass = all(bool(probe["pass"]) for probe in probes)
        pre_g1_gate_pass = reset_gate_pass and base_pose_gate_pass and ik_gate_pass
        receipt = {
            "schema_version": 1,
            "gate": "pre_G1_deterministic_reset_and_ik",
            "pre_g1_gate_pass": pre_g1_gate_pass,
            "task_success_claim": False,
            "contact_execution_claim": False,
            "backend_requested": args.backend,
            "backend_active": str(gs.backend),
            "device": str(gs.device),
            "genesis_version": importlib.metadata.version("genesis-world"),
            "python_version": platform.python_version(),
            "seeds": args.seeds,
            "reset_poses_by_seed": reset_by_seed,
            "runtime_seed": first_seed,
            "requested_initial_positions": requested_positions,
            "actual_initial_positions": initial_positions,
            "settled_positions": settled_positions,
            "reset_readback_max_abs_error_m": reset_readback_max_error,
            "table_contact_pass": table_contact_pass,
            "reset_gate_pass": reset_gate_pass,
            "requested_base_position_xyz_m": base["position_xyz_m"],
            "actual_base_position_xyz_m": actual_base_position,
            "requested_base_quaternion_wxyz": base["quaternion_wxyz"],
            "actual_base_quaternion_wxyz": actual_base_quaternion,
            "base_position_max_abs_error_m": base_position_error,
            "base_quaternion_l2_sign_invariant_error": base_quaternion_error,
            "base_pose_gate_pass": base_pose_gate_pass,
            "ik_position_tolerance_m": position_tolerance,
            "ik_rotation_tolerance_rad": rotation_tolerance,
            "ik_probes": probes,
            "ik_probe_count": len(probes),
            "ik_reference_seed_coverage": args.seeds,
            "ik_gate_pass": ik_gate_pass,
            "attached_wrist_cameras": attached,
            "port_config_sha256": sha256_file(args.port),
            "source_task_contract_sha256": sha256_file(args.source_task),
            "target_task_contract_sha256": sha256_file(args.task),
            "scene_contract_sha256": sha256_file(args.scene_contract),
            "mantis_urdf_sha256": sha256_file(args.mantis_urdf),
            "bowl_urdf_sha256": sha256_file(bowl_urdf),
            "bowl_manifest_sha256": sha256_file(bowl_manifest_path),
            "camera_contract_sha256": sha256_file(args.cameras),
            "evidence_boundary": (
                "pre-G1 proves deterministic reset and independent IK targets only; "
                "G1 still requires one complete safe episode with real contact execution"
            ),
        }
        receipt_path = run_dir / "receipt.json"
        receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        receipt_written = True
        receipt_hash = sha256_file(receipt_path)
        if not pre_g1_gate_pass:
            failed = [probe["name"] for probe in probes if not probe["pass"]]
            finish_run(
                args.ops_root,
                args.run_id,
                "failed",
                {
                    "receipt_sha256": receipt_hash,
                    "failed_ik_probes": failed,
                    "reset_gate_pass": reset_gate_pass,
                    "base_pose_gate_pass": base_pose_gate_pass,
                },
            )
            print(json.dumps(receipt, indent=2, sort_keys=True))
            return 2
        finish_run(
            args.ops_root,
            args.run_id,
            "completed",
            {"receipt_sha256": receipt_hash},
        )
        print(json.dumps(receipt, indent=2, sort_keys=True))
        return 0
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
