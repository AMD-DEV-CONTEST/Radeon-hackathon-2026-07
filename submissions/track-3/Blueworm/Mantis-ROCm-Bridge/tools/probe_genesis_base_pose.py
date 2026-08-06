#!/usr/bin/env python3
"""Diagnose Mantis base-Y candidates against frozen reset/IK targets.

This tool is deliberately diagnostic: it loads no bowls, executes no motion,
and cannot produce a pre-G1 or task-success claim.  Multiple robots are offset
along world X so all candidates can be evaluated in one Genesis scene.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import math
from pathlib import Path
from typing import Any

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


def _csv_floats(raw: str) -> list[float]:
    try:
        values = [float(item.strip()) for item in raw.split(",") if item.strip()]
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected comma-separated floats") from exc
    if not values or not all(math.isfinite(value) for value in values):
        raise argparse.ArgumentTypeError("at least one finite value is required")
    if len(values) != len(set(values)):
        raise argparse.ArgumentTypeError("candidate values must be unique")
    return values


def _csv_ints(raw: str) -> list[int]:
    try:
        values = [int(item.strip()) for item in raw.split(",") if item.strip()]
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected comma-separated integers") from exc
    if not values or len(values) != len(set(values)):
        raise argparse.ArgumentTypeError("at least one unique seed is required")
    return values


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
    parser.add_argument("--base-y-candidates", type=_csv_floats, required=True)
    parser.add_argument("--seeds", type=_csv_ints, default=_csv_ints("0,1,42,20260722"))
    parser.add_argument("--ops-root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--backend", choices=BACKENDS, required=True)
    args = parser.parse_args()
    if not args.mantis_urdf.is_file():
        parser.error(f"Mantis URDF does not exist: {args.mantis_urdf}")

    port = load_json(args.port)
    source_task = load_json(args.source_task)
    task = load_json(args.task)
    scene_contract = load_json(args.scene_contract)
    validate_contract_pair(port, task, source_task)
    validate_genesis_scene_contract(scene_contract, source_task, port)
    base = scene_contract["world"]["mantis_base"]
    tcp = scene_contract["tcp"]
    ik = scene_contract["ik_gate"]
    run_dir = args.ops_root / args.run_id
    begun = False

    try:
        begin_run(
            args.ops_root,
            args.run_id,
            {
                "phase": "diagnose_mantis_base_y_ik_coverage",
                "diagnostic_only": True,
                "base_y_candidates_m": args.base_y_candidates,
                "seeds": args.seeds,
                "backend": args.backend,
                "scene_contract_sha256": sha256_file(args.scene_contract),
                "mantis_urdf_sha256": sha256_file(args.mantis_urdf),
            },
        )
        begun = True
        import genesis as gs
        import numpy as np

        gs.init(backend=resolve_backend(gs, args.backend), seed=args.seeds[0], logging_level="warning")
        scene = gs.Scene(show_viewer=False)
        robots: list[tuple[float, float, Any]] = []
        for index, base_y in enumerate(args.base_y_candidates):
            x_offset = float(index) * 2.0
            robot = scene.add_entity(
                gs.morphs.URDF(
                    file=str(args.mantis_urdf.resolve()),
                    pos=(x_offset, base_y, float(base["position_xyz_m"][2])),
                    quat=tuple(base["quaternion_wxyz"]),
                    fixed=True,
                )
            )
            robots.append((base_y, x_offset, robot))
        scene.build()

        reset_by_seed = {
            seed: sample_source_reset_poses(seed=seed)
            for seed in args.seeds
        }
        orientation = np.asarray(tcp["orientation_wxyz"], dtype=float)
        position_tolerance = float(ik["position_tolerance_m"])
        rotation_tolerance = float(ik["rotation_tolerance_rad"])
        candidate_rows: list[dict[str, object]] = []

        for base_y, x_offset, robot in robots:
            neutral = np.asarray(_vector(robot.get_qpos()), dtype=float)
            indices_by_side = {side: _dof_indices(robot, side) for side in ("left", "right")}
            specs: list[tuple[str, str, list[float]]] = []
            for seed, poses in reset_by_seed.items():
                for pose in poses:
                    x, y, _ = pose.position_xyz_m
                    side = arm_for_bowl_x(x)
                    specs.append(
                        (
                            f"seed_{seed}_{pose.name}_pregrasp",
                            side,
                            [x + x_offset, y - float(ik["pregrasp_retreat_y_m"]), float(ik["bowl_tcp_z_m"])],
                        )
                    )
                    specs.append(
                        (
                            f"seed_{seed}_{pose.name}_grasp",
                            side,
                            [x + x_offset, y, float(ik["bowl_tcp_z_m"])],
                        )
                    )
            target_x, target_y = scene_contract["world"]["target_xy_m"]
            for z in ik["stack_target_z_m"]:
                for side in ("left", "right"):
                    specs.append(
                        (
                            f"stack_z_{float(z):.3f}_{side}",
                            side,
                            [target_x + x_offset, target_y, float(z)],
                        )
                    )

            probes: list[dict[str, object]] = []
            for name, side, target in specs:
                robot.set_qpos(neutral)
                qpos, error = robot.inverse_kinematics(
                    robot.get_link(tcp[side]["link"]),
                    pos=np.asarray(target, dtype=float),
                    quat=orientation,
                    local_point=np.asarray(tcp[side]["local_point_xyz_m"], dtype=float),
                    init_qpos=neutral,
                    respect_joint_limit=bool(ik["respect_joint_limits"]),
                    max_samples=int(ik["max_samples"]),
                    max_solver_iters=int(ik["max_solver_iters"]),
                    dofs_idx_local=indices_by_side[side],
                    return_error=True,
                )
                error_vector = _vector(error)
                qpos_vector = _vector(qpos)
                position_error = math.sqrt(sum(value * value for value in error_vector[:3]))
                rotation_error = math.sqrt(sum(value * value for value in error_vector[3:]))
                finite = all(math.isfinite(value) for value in error_vector + qpos_vector)
                passed = finite and position_error <= position_tolerance and rotation_error <= rotation_tolerance
                probes.append(
                    {
                        "name": name,
                        "side": side,
                        "position_error_m": position_error,
                        "rotation_error_rad": rotation_error,
                        "pass": passed,
                    }
                )
            candidate_rows.append(
                {
                    "base_y_m": base_y,
                    "probe_count": len(probes),
                    "passed_count": sum(bool(probe["pass"]) for probe in probes),
                    "all_pass": all(bool(probe["pass"]) for probe in probes),
                    "maximum_position_error_m": max(float(probe["position_error_m"]) for probe in probes),
                    "maximum_rotation_error_rad": max(float(probe["rotation_error_rad"]) for probe in probes),
                    "failed_probes": [probe for probe in probes if not probe["pass"]],
                }
            )

        passing = [row for row in candidate_rows if row["all_pass"]]
        source_base_y = float(base["position_xyz_m"][1])
        selected = min(
            passing,
            key=lambda row: abs(float(row["base_y_m"]) - source_base_y),
            default=None,
        )
        receipt = {
            "schema_version": 1,
            "diagnostic_only": True,
            "task_success_claim": False,
            "pre_g1_claim": False,
            "backend_requested": args.backend,
            "backend_active": str(gs.backend),
            "device": str(gs.device),
            "genesis_version": importlib.metadata.version("genesis-world"),
            "source_base_y_m": source_base_y,
            "seeds": args.seeds,
            "candidate_results": candidate_rows,
            "selected_base_y_m": None if selected is None else selected["base_y_m"],
            "selection_rule": "closest candidate to source base_y with all frozen IK probes passing",
            "scene_contract_sha256": sha256_file(args.scene_contract),
            "mantis_urdf_sha256": sha256_file(args.mantis_urdf),
        }
        receipt_path = run_dir / "receipt.json"
        receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        finish_run(
            args.ops_root,
            args.run_id,
            "completed",
            {
                "receipt_sha256": sha256_file(receipt_path),
                "selected_base_y_m": receipt["selected_base_y_m"],
            },
        )
        print(json.dumps(receipt, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        if begun:
            finish_run(
                args.ops_root,
                args.run_id,
                "failed",
                {"error_type": type(exc).__name__, "message": str(exc)},
            )
        raise


if __name__ == "__main__":
    raise SystemExit(main())
