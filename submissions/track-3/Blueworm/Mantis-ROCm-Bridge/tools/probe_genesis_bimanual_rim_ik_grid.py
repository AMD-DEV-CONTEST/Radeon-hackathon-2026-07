#!/usr/bin/env python3
"""Probe two-arm local rim-pinch IK candidates without bowl contact."""

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
SIDES = ("left", "right")


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


def _unexpected_self_pairs(contact_info: Any, geom_labels: dict[int, str]) -> list[str]:
    pairs: set[str] = set()
    for geom_a, geom_b in zip(
        _vector(contact_info["geom_a"]),
        _vector(contact_info["geom_b"]),
    ):
        labels = sorted(
            (
                geom_labels.get(int(geom_a), f"geom:{int(geom_a)}"),
                geom_labels.get(int(geom_b), f"geom:{int(geom_b)}"),
            )
        )
        if not all(label.startswith("mantis:") for label in labels):
            continue
        expected_same_gripper = any(
            all(label.startswith(f"mantis:{side}_clamp") for label in labels)
            for side in SIDES
        )
        if not expected_same_gripper:
            pairs.add(" <> ".join(labels))
    return sorted(pairs)


def _quaternion_wxyz_from_axes(
    local_x_world: Any,
    local_y_world: Any,
) -> list[float]:
    """Build a local-to-world quaternion from orthogonal local x/y axes."""
    import numpy as np

    x_axis = np.asarray(local_x_world, dtype=float)
    y_axis = np.asarray(local_y_world, dtype=float)
    x_axis /= np.linalg.norm(x_axis)
    y_axis /= np.linalg.norm(y_axis)
    z_axis = np.cross(x_axis, y_axis)
    z_axis /= np.linalg.norm(z_axis)
    y_axis = np.cross(z_axis, x_axis)
    rotation = np.column_stack((x_axis, y_axis, z_axis))
    trace = float(np.trace(rotation))
    if trace > 0.0:
        scale = math.sqrt(trace + 1.0) * 2.0
        quaternion = np.asarray(
            [
                0.25 * scale,
                (rotation[2, 1] - rotation[1, 2]) / scale,
                (rotation[0, 2] - rotation[2, 0]) / scale,
                (rotation[1, 0] - rotation[0, 1]) / scale,
            ],
            dtype=float,
        )
    else:
        diagonal = np.diag(rotation)
        index = int(np.argmax(diagonal))
        if index == 0:
            scale = math.sqrt(1.0 + rotation[0, 0] - rotation[1, 1] - rotation[2, 2]) * 2.0
            quaternion = np.asarray(
                [
                    (rotation[2, 1] - rotation[1, 2]) / scale,
                    0.25 * scale,
                    (rotation[0, 1] + rotation[1, 0]) / scale,
                    (rotation[0, 2] + rotation[2, 0]) / scale,
                ],
                dtype=float,
            )
        elif index == 1:
            scale = math.sqrt(1.0 + rotation[1, 1] - rotation[0, 0] - rotation[2, 2]) * 2.0
            quaternion = np.asarray(
                [
                    (rotation[0, 2] - rotation[2, 0]) / scale,
                    (rotation[0, 1] + rotation[1, 0]) / scale,
                    0.25 * scale,
                    (rotation[1, 2] + rotation[2, 1]) / scale,
                ],
                dtype=float,
            )
        else:
            scale = math.sqrt(1.0 + rotation[2, 2] - rotation[0, 0] - rotation[1, 1]) * 2.0
            quaternion = np.asarray(
                [
                    (rotation[1, 0] - rotation[0, 1]) / scale,
                    (rotation[0, 2] + rotation[2, 0]) / scale,
                    (rotation[1, 2] + rotation[2, 1]) / scale,
                    0.25 * scale,
                ],
                dtype=float,
            )
    quaternion /= np.linalg.norm(quaternion)
    if quaternion[0] < 0.0:
        quaternion *= -1.0
    return quaternion.tolist()


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
    parser.add_argument("--ops-root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--backend", choices=("cpu", "cuda", "amdgpu"), required=True)
    args = parser.parse_args()

    if not args.mantis_urdf.is_file():
        parser.error(f"Mantis URDF does not exist: {args.mantis_urdf}")
    port = load_json(args.port)
    source_task = load_json(args.source_task)
    scene_contract = load_json(args.scene_contract)
    validate_genesis_scene_contract(scene_contract, source_task, port)
    single_contact = scene_contract["contact_probe"]
    seed = int(single_contact["seed"])
    selected = next(
        pose
        for pose in sample_source_reset_poses(seed=seed)
        if pose.name == single_contact["bowl"]
    )
    rim_radii_m = (0.060, 0.0678)
    z_values_m = (0.84, 0.86)
    splay_tilt_degrees = (35.0, 50.0, 65.0, 75.0)
    site_families = {
        "x_left_negative_right_positive": {
            "radial_unit_xy": {"left": [-1.0, 0.0], "right": [1.0, 0.0]},
            "splay_unit_xy": {"left": [0.0, 1.0], "right": [0.0, -1.0]},
        },
        "y_left_near_right_far": {
            "radial_unit_xy": {"left": [0.0, -1.0], "right": [0.0, 1.0]},
            "splay_unit_xy": {"left": [-1.0, 0.0], "right": [1.0, 0.0]},
        },
        "y_left_far_right_near": {
            "radial_unit_xy": {"left": [0.0, 1.0], "right": [0.0, -1.0]},
            "splay_unit_xy": {"left": [-1.0, 0.0], "right": [1.0, 0.0]},
        },
        "diagonal_left_near_negative_x": {
            "radial_unit_xy": {
                "left": [-0.7071067811865476, -0.7071067811865476],
                "right": [0.7071067811865476, 0.7071067811865476],
            },
            "splay_unit_xy": {
                "left": [0.7071067811865476, -0.7071067811865476],
                "right": [-0.7071067811865476, 0.7071067811865476],
            },
        },
        "diagonal_left_far_negative_x": {
            "radial_unit_xy": {
                "left": [-0.7071067811865476, 0.7071067811865476],
                "right": [0.7071067811865476, -0.7071067811865476],
            },
            "splay_unit_xy": {
                "left": [-0.7071067811865476, -0.7071067811865476],
                "right": [0.7071067811865476, 0.7071067811865476],
            },
        },
    }
    run_dir = args.ops_root / args.run_id
    begun = False
    receipt_written = False

    try:
        begin_run(
            args.ops_root,
            args.run_id,
            {
                "phase": "genesis_bimanual_local_rim_ik_grid",
                "backend": args.backend,
                "seed": seed,
                "bowl": selected.name,
                "scene_contract_sha256": sha256_file(args.scene_contract),
                "port_config_sha256": sha256_file(args.port),
                "mantis_urdf_sha256": sha256_file(args.mantis_urdf),
            },
        )
        begun = True
        import genesis as gs
        import numpy as np

        gs.init(backend=resolve_backend(gs, args.backend), seed=seed, logging_level="warning")
        scene = gs.Scene(
            sim_options=gs.options.SimOptions(
                dt=float(scene_contract["control"]["physics_dt_s"])
            ),
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
        scene.step()
        ik = scene_contract["ik_gate"]
        tcp = scene_contract["tcp"]
        links = {side: robot.get_link(tcp[side]["link"]) for side in SIDES}
        local_points = {
            side: np.asarray(tcp[side]["local_point_xyz_m"], dtype=float)
            for side in SIDES
        }
        arm_indices = {
            side: _dof_indices(robot, arm_dof_names(side)) for side in SIDES
        }
        geom_labels = {
            int(geom.idx): f"mantis:{geom.link.name}" for geom in robot.geoms
        }
        rows: list[dict[str, Any]] = []
        for site_family_name, site_family in site_families.items():
            for radius_m in rim_radii_m:
                for z_m in z_values_m:
                    for splay_tilt_degree in splay_tilt_degrees:
                        tilt_rad = math.radians(splay_tilt_degree)
                        orientations: dict[str, dict[str, list[float]]] = {}
                        for side in SIDES:
                            radial_x, radial_y = site_family["radial_unit_xy"][side]
                            splay_x, splay_y = site_family["splay_unit_xy"][side]
                            local_x_world = [
                                math.sin(tilt_rad) * splay_x,
                                math.sin(tilt_rad) * splay_y,
                                -math.cos(tilt_rad),
                            ]
                            orientations[side] = {}
                            for jaw_sign in (1.0, -1.0):
                                name = "jaw_radial_outward" if jaw_sign > 0 else "jaw_radial_inward"
                                orientations[side][name] = _quaternion_wxyz_from_axes(
                                    local_x_world,
                                    [jaw_sign * radial_x, jaw_sign * radial_y, 0.0],
                                )
                        for left_orientation_name, left_orientation in orientations["left"].items():
                            for right_orientation_name, right_orientation in orientations["right"].items():
                                combined = open_qpos.copy()
                                row: dict[str, Any] = {
                                    "site_family": site_family_name,
                                    "rim_radius_m": radius_m,
                                    "z_m": z_m,
                                    "splay_tilt_degree": splay_tilt_degree,
                                    "arms": {},
                                }
                                for side, orientation_name, orientation in (
                                    (
                                        "left",
                                        left_orientation_name,
                                        left_orientation,
                                    ),
                                    (
                                        "right",
                                        right_orientation_name,
                                        right_orientation,
                                    ),
                                ):
                                    radial_x, radial_y = site_family["radial_unit_xy"][side]
                                    target = np.asarray(
                                        [
                                            selected.position_xyz_m[0] + radial_x * radius_m,
                                            selected.position_xyz_m[1] + radial_y * radius_m,
                                            z_m,
                                        ],
                                        dtype=float,
                                    )
                                    qpos, error = robot.inverse_kinematics(
                                        links[side],
                                        pos=target,
                                        quat=np.asarray(orientation, dtype=float),
                                        local_point=local_points[side],
                                        init_qpos=combined,
                                        respect_joint_limit=True,
                                        max_samples=int(ik["max_samples"]),
                                        max_solver_iters=int(ik["max_solver_iters"]),
                                        dofs_idx_local=arm_indices[side],
                                        return_error=True,
                                    )
                                    candidate = np.asarray(_vector(qpos), dtype=float)
                                    for index in range(len(combined)):
                                        if index not in arm_indices[side]:
                                            candidate[index] = combined[index]
                                    combined = candidate
                                    error_vector = _vector(error)
                                    position_error = math.sqrt(
                                        sum(value * value for value in error_vector[:3])
                                    )
                                    rotation_error = math.sqrt(
                                        sum(value * value for value in error_vector[3:])
                                    )
                                    row["arms"][side] = {
                                        "target_xyz_m": target.tolist(),
                                        "orientation_name": orientation_name,
                                        "orientation_wxyz": orientation,
                                        "position_error_m": position_error,
                                        "rotation_error_rad": rotation_error,
                                        "ik_pass": position_error
                                        <= float(ik["position_tolerance_m"])
                                        and rotation_error
                                        <= float(ik["rotation_tolerance_rad"]),
                                    }
                                both_ik_pass = all(
                                    arm["ik_pass"] for arm in row["arms"].values()
                                )
                                unexpected_pairs: list[str] = []
                                if both_ik_pass:
                                    robot.set_qpos(combined)
                                    scene.step()
                                    unexpected_pairs = _unexpected_self_pairs(
                                        robot.get_contacts(), geom_labels
                                    )
                                row["bimanual_ik_pass"] = both_ik_pass
                                row["unexpected_self_collision_pairs"] = unexpected_pairs
                                row["candidate_pass"] = both_ik_pass and not unexpected_pairs
                                if row["candidate_pass"]:
                                    row["physical_qpos"] = combined.tolist()
                                rows.append(row)
        passing = [row for row in rows if row["candidate_pass"]]
        preferred = min(
            passing,
            key=lambda row: (
                abs(row["rim_radius_m"] - 0.0678),
                abs(row["z_m"] - 0.84),
                abs(row["splay_tilt_degree"] - 50.0),
                row["site_family"] != "y_left_near_right_far",
                row["arms"]["left"]["orientation_name"]
                != "jaw_radial_outward",
                row["arms"]["right"]["orientation_name"]
                != "jaw_radial_outward",
            ),
        ) if passing else None
        receipt = {
            "schema_version": 1,
            "genesis_version": importlib.metadata.version("genesis-world"),
            "backend": args.backend,
            "seed": seed,
            "bowl": selected.name,
            "bowl_center_xyz_m": list(selected.position_xyz_m),
            "site_semantics": "scan opposed world-X, both world-Y assignments, and two diagonal rim-site assignments",
            "orientation_semantics": "local jaw axis follows the radial rim normal while local +x tilts down and tangentially outward so the two wrist bodies splay apart",
            "rows": rows,
            "passing_count": len(passing),
            "preferred_passing_candidate": preferred,
            "evidence_boundary": "bimanual local-rim IK and static self-collision diagnostic only; no trajectory, bowl contact, lift, or task-success claim",
            "scene_contract_sha256": sha256_file(args.scene_contract),
            "port_config_sha256": sha256_file(args.port),
            "mantis_urdf_sha256": sha256_file(args.mantis_urdf),
        }
        receipt_path = run_dir / "receipt.json"
        receipt_path.write_text(
            json.dumps(receipt, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        receipt_written = True
        finish_run(
            args.ops_root,
            args.run_id,
            "completed" if passing else "failed",
            {
                "receipt_sha256": sha256_file(receipt_path),
                "passing_count": len(passing),
            },
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
