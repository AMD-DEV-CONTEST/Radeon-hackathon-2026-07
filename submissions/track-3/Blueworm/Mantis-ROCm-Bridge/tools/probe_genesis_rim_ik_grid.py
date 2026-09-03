#!/usr/bin/env python3
"""Probe Mantis near-rim pinch IK candidates without object contact."""

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
    contact = scene_contract["contact_probe"]
    ik = scene_contract["ik_gate"]
    reset = sample_source_reset_poses(seed=int(contact["seed"]))
    selected = next(pose for pose in reset if pose.name == contact["bowl"])
    side = arm_for_bowl_x(selected.position_xyz_m[0])
    target_xy = [
        selected.position_xyz_m[0],
        selected.position_xyz_m[1] + float(contact["grasp_center_y_offset_m"]),
    ]
    pitch_degrees = [90.0, 80.0, 70.0, 60.0]
    z_values = [0.84, 0.85, 0.86, 0.875, 0.89, 0.90]
    run_dir = args.ops_root / args.run_id
    begun = False
    receipt_written = False

    try:
        begin_run(
            args.ops_root,
            args.run_id,
            {
                "phase": "genesis_rim_ik_grid",
                "backend": args.backend,
                "side": side,
                "scene_contract_sha256": sha256_file(args.scene_contract),
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
        open_qpos = np.asarray(physical_pose(port, 1.0), dtype=float)
        robot.set_qpos(open_qpos)
        link = robot.get_link(scene_contract["tcp"][side]["link"])
        local_point = np.asarray(scene_contract["tcp"][side]["local_point_xyz_m"], dtype=float)
        arm_indices = _dof_indices(robot, arm_dof_names(side))
        rows: list[dict[str, Any]] = []
        for pitch_deg in pitch_degrees:
            half_angle = math.radians(pitch_deg) / 2.0
            orientation = np.asarray([math.cos(half_angle), 0.0, math.sin(half_angle), 0.0])
            for z_m in z_values:
                target = np.asarray([target_xy[0], target_xy[1], z_m], dtype=float)
                qpos, error = robot.inverse_kinematics(
                    link,
                    pos=target,
                    quat=orientation,
                    local_point=local_point,
                    init_qpos=open_qpos,
                    respect_joint_limit=True,
                    max_samples=int(ik["max_samples"]),
                    max_solver_iters=int(ik["max_solver_iters"]),
                    dofs_idx_local=arm_indices,
                    return_error=True,
                )
                del qpos
                error_vector = _vector(error)
                position_error = math.sqrt(sum(value * value for value in error_vector[:3]))
                rotation_error = math.sqrt(sum(value * value for value in error_vector[3:]))
                rows.append(
                    {
                        "pitch_deg": pitch_deg,
                        "target_xyz_m": target.tolist(),
                        "orientation_wxyz": orientation.tolist(),
                        "position_error_m": position_error,
                        "rotation_error_rad": rotation_error,
                        "ik_pass": position_error <= float(ik["position_tolerance_m"])
                        and rotation_error <= float(ik["rotation_tolerance_rad"]),
                    }
                )
        passing = [row for row in rows if row["ik_pass"]]
        receipt = {
            "schema_version": 1,
            "genesis_version": importlib.metadata.version("genesis-world"),
            "backend": args.backend,
            "side": side,
            "target_xy_m": target_xy,
            "position_tolerance_m": ik["position_tolerance_m"],
            "rotation_tolerance_rad": ik["rotation_tolerance_rad"],
            "rows": rows,
            "passing_count": len(passing),
            "best_passing_candidate": max(passing, key=lambda row: row["pitch_deg"]) if passing else None,
            "evidence_boundary": "IK diagnostic only; no trajectory, contact, lift, or task-success claim",
            "scene_contract_sha256": sha256_file(args.scene_contract),
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
