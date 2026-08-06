#!/usr/bin/env python3
"""Probe two-arm opposed whole-bowl grasp IK without object contact."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import math
from pathlib import Path
from typing import Any

from mantis_rocm_bridge.contracts import load_json
from mantis_rocm_bridge.genesis_smoke import physical_pose, resolve_backend, sha256_file
from mantis_rocm_bridge.ops import begin_run, finish_run
from mantis_rocm_bridge.stack_bowls_env import (
    arm_dof_names,
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mantis_urdf", type=Path)
    parser.add_argument("--scene-contract", type=Path, default=ROOT / "configs/stack-bowls-genesis-v1.json")
    parser.add_argument("--port", type=Path, default=ROOT / "configs/mantis-port-config.json")
    parser.add_argument("--source-task", type=Path, default=ROOT / "configs/source-task-stack-bowls-three.json")
    parser.add_argument("--ops-root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--backend", choices=("cpu", "cuda", "amdgpu"), required=True)
    args = parser.parse_args()

    port = load_json(args.port)
    source_task = load_json(args.source_task)
    scene_contract = load_json(args.scene_contract)
    validate_genesis_scene_contract(scene_contract, source_task, port)
    ik = scene_contract["ik_gate"]
    contact = scene_contract["contact_probe"]
    selected = next(
        pose
        for pose in sample_source_reset_poses(seed=int(contact["seed"]))
        if pose.name == contact["bowl"]
    )
    half_spans_m = [0.125, 0.13, 0.135, 0.14]
    z_values_m = [0.75, 0.77, 0.79, 0.80, 0.81, 0.83, 0.85]
    orientations = {
        "left": [1.0, 0.0, 0.0, 0.0],
        "right": [0.0, 0.0, 0.0, 1.0],
    }
    run_dir = args.ops_root / args.run_id
    begun = False
    receipt_written = False

    try:
        begin_run(
            args.ops_root,
            args.run_id,
            {
                "phase": "genesis_bimanual_bowl_ik_grid",
                "backend": args.backend,
                "scene_contract_sha256": sha256_file(args.scene_contract),
                "port_config_sha256": sha256_file(args.port),
                "mantis_urdf_sha256": sha256_file(args.mantis_urdf),
            },
        )
        begun = True
        import genesis as gs
        import numpy as np

        gs.init(backend=resolve_backend(gs, args.backend), seed=int(contact["seed"]), logging_level="warning")
        scene = gs.Scene(
            sim_options=gs.options.SimOptions(dt=float(scene_contract["control"]["physics_dt_s"])),
            show_viewer=False,
        )
        base = scene_contract["world"]["mantis_base"]
        robot = scene.add_entity(
            gs.morphs.URDF(
                file=str(args.mantis_urdf.resolve()),
                pos=tuple(base["position_xyz_m"]),
                quat=tuple(base["quaternion_wxyz"]),
                fixed=True,
            )
        )
        scene.build()
        closed_qpos = np.asarray(physical_pose(port, 0.0), dtype=float)
        robot.set_qpos(closed_qpos)
        initial_link_quaternions_wxyz = {
            side: _vector(robot.get_link(scene_contract["tcp"][side]["link"]).get_quat())
            for side in ("left", "right")
        }
        rows: list[dict[str, Any]] = []
        for half_span_m in half_spans_m:
            for z_m in z_values_m:
                row: dict[str, Any] = {
                    "half_span_m": half_span_m,
                    "z_m": z_m,
                    "arms": {},
                }
                for side, x_sign in (("left", -1.0), ("right", 1.0)):
                    target = np.asarray(
                        [
                            selected.position_xyz_m[0] + x_sign * half_span_m,
                            selected.position_xyz_m[1],
                            z_m,
                        ],
                        dtype=float,
                    )
                    qpos, error = robot.inverse_kinematics(
                        robot.get_link(scene_contract["tcp"][side]["link"]),
                        pos=target,
                        quat=np.asarray(orientations[side], dtype=float),
                        local_point=np.asarray(
                            scene_contract["tcp"][side]["local_point_xyz_m"], dtype=float
                        ),
                        init_qpos=closed_qpos,
                        respect_joint_limit=True,
                        max_samples=int(ik["max_samples"]),
                        max_solver_iters=int(ik["max_solver_iters"]),
                        dofs_idx_local=_dof_indices(robot, arm_dof_names(side)),
                        return_error=True,
                    )
                    del qpos
                    error_vector = _vector(error)
                    position_error = math.sqrt(sum(value * value for value in error_vector[:3]))
                    rotation_error = math.sqrt(sum(value * value for value in error_vector[3:]))
                    row["arms"][side] = {
                        "target_xyz_m": target.tolist(),
                        "orientation_wxyz": orientations[side],
                        "position_error_m": position_error,
                        "rotation_error_rad": rotation_error,
                        "ik_pass": position_error <= float(ik["position_tolerance_m"])
                        and rotation_error <= float(ik["rotation_tolerance_rad"]),
                    }
                row["bimanual_ik_pass"] = all(
                    arm["ik_pass"] for arm in row["arms"].values()
                )
                rows.append(row)
        front_clearance_rows: list[dict[str, Any]] = []
        for y_m in (-0.12, -0.10, -0.08, -0.06, -0.04, -0.02, 0.0):
            row = {
                "half_span_m": 0.14,
                "y_m": y_m,
                "z_m": 0.81,
                "arms": {},
            }
            for side, x_sign in (("left", -1.0), ("right", 1.0)):
                target = np.asarray(
                    [
                        selected.position_xyz_m[0] + x_sign * 0.14,
                        y_m,
                        0.81,
                    ],
                    dtype=float,
                )
                qpos, error = robot.inverse_kinematics(
                    robot.get_link(scene_contract["tcp"][side]["link"]),
                    pos=target,
                    quat=np.asarray(orientations[side], dtype=float),
                    local_point=np.asarray(
                        scene_contract["tcp"][side]["local_point_xyz_m"], dtype=float
                    ),
                    init_qpos=closed_qpos,
                    respect_joint_limit=True,
                    max_samples=int(ik["max_samples"]),
                    max_solver_iters=int(ik["max_solver_iters"]),
                    dofs_idx_local=_dof_indices(robot, arm_dof_names(side)),
                    return_error=True,
                )
                del qpos
                error_vector = _vector(error)
                position_error = math.sqrt(sum(value * value for value in error_vector[:3]))
                rotation_error = math.sqrt(sum(value * value for value in error_vector[3:]))
                row["arms"][side] = {
                    "target_xyz_m": target.tolist(),
                    "orientation_wxyz": orientations[side],
                    "position_error_m": position_error,
                    "rotation_error_rad": rotation_error,
                    "ik_pass": position_error <= float(ik["position_tolerance_m"])
                    and rotation_error <= float(ik["rotation_tolerance_rad"]),
                }
            row["bimanual_ik_pass"] = all(
                arm["ik_pass"] for arm in row["arms"].values()
            )
            front_clearance_rows.append(row)
        passing = [row for row in rows if row["bimanual_ik_pass"]]
        passing_front_clearance = [
            row for row in front_clearance_rows if row["bimanual_ik_pass"]
        ]
        route_rows: list[dict[str, Any]] = []
        for stage, y_m, z_m, stage_orientations in (
            (
                "separate_high_initial_orientation",
                0.025,
                0.88,
                initial_link_quaternions_wxyz,
            ),
            ("rotate_high_opposed_orientation", -0.08, 0.85, orientations),
        ):
            row = {"stage": stage, "half_span_m": 0.14, "y_m": y_m, "z_m": z_m, "arms": {}}
            for side, x_sign in (("left", -1.0), ("right", 1.0)):
                target = np.asarray(
                    [selected.position_xyz_m[0] + x_sign * 0.14, y_m, z_m],
                    dtype=float,
                )
                qpos, error = robot.inverse_kinematics(
                    robot.get_link(scene_contract["tcp"][side]["link"]),
                    pos=target,
                    quat=np.asarray(stage_orientations[side], dtype=float),
                    local_point=np.asarray(
                        scene_contract["tcp"][side]["local_point_xyz_m"], dtype=float
                    ),
                    init_qpos=closed_qpos,
                    respect_joint_limit=True,
                    max_samples=int(ik["max_samples"]),
                    max_solver_iters=int(ik["max_solver_iters"]),
                    dofs_idx_local=_dof_indices(robot, arm_dof_names(side)),
                    return_error=True,
                )
                del qpos
                error_vector = _vector(error)
                position_error = math.sqrt(sum(value * value for value in error_vector[:3]))
                rotation_error = math.sqrt(sum(value * value for value in error_vector[3:]))
                row["arms"][side] = {
                    "target_xyz_m": target.tolist(),
                    "orientation_wxyz": stage_orientations[side],
                    "position_error_m": position_error,
                    "rotation_error_rad": rotation_error,
                    "ik_pass": position_error <= float(ik["position_tolerance_m"])
                    and rotation_error <= float(ik["rotation_tolerance_rad"]),
                }
            row["bimanual_ik_pass"] = all(
                arm["ik_pass"] for arm in row["arms"].values()
            )
            route_rows.append(row)
        preferred = min(
            passing,
            key=lambda row: (abs(row["half_span_m"] - 0.13), abs(row["z_m"] - 0.77)),
        ) if passing else None
        receipt = {
            "schema_version": 1,
            "genesis_version": importlib.metadata.version("genesis-world"),
            "backend": args.backend,
            "bowl": selected.name,
            "bowl_center_xyz_m": list(selected.position_xyz_m),
            "orientation_semantics": "closed grippers act as opposed pads; local +x faces inward from each bowl side",
            "initial_link_quaternions_wxyz": initial_link_quaternions_wxyz,
            "geometry_derivation": "nominal TCP half-span 0.130 m is bowl radius 0.0678 m plus clamp forward extent 0.0652 m minus 0.003 m squeeze",
            "rows": rows,
            "passing_count": len(passing),
            "preferred_passing_candidate": preferred,
            "front_clearance_rows": front_clearance_rows,
            "front_clearance_passing_count": len(passing_front_clearance),
            "preferred_front_clearance_candidate": max(
                passing_front_clearance,
                key=lambda row: row["y_m"],
                default=None,
            ),
            "route_rows": route_rows,
            "route_pass": all(row["bimanual_ik_pass"] for row in route_rows),
            "evidence_boundary": "bimanual IK diagnostic only; no simultaneous trajectory, contact, lift, or task-success claim",
            "scene_contract_sha256": sha256_file(args.scene_contract),
            "port_config_sha256": sha256_file(args.port),
            "mantis_urdf_sha256": sha256_file(args.mantis_urdf),
        }
        receipt_path = run_dir / "receipt.json"
        receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        receipt_written = True
        finish_run(
            args.ops_root,
            args.run_id,
            "completed" if passing else "failed",
            {"receipt_sha256": sha256_file(receipt_path), "passing_count": len(passing)},
        )
        print(json.dumps(receipt, indent=2, sort_keys=True))
        return 0 if passing else 2
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
