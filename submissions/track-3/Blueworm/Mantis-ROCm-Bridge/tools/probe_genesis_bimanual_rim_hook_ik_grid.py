#!/usr/bin/env python3
"""Probe route-aware horizontal bimanual rim-hook IK without bowl contact."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import math
from itertools import product
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


def _all_pairs(contact_info: Any, geom_labels: dict[int, str]) -> list[str]:
    return sorted(
        {
            " <> ".join(
                sorted(
                    (
                        geom_labels.get(int(geom_a), f"geom:{int(geom_a)}"),
                        geom_labels.get(int(geom_b), f"geom:{int(geom_b)}"),
                    )
                )
            )
            for geom_a, geom_b in zip(
                _vector(contact_info["geom_a"]),
                _vector(contact_info["geom_b"]),
            )
        }
    )


def _quaternion_wxyz_from_axes(
    local_x_world: Any,
    local_y_world: Any,
) -> list[float]:
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
    parser.add_argument("--ops-root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--backend", choices=("cpu", "cuda", "amdgpu"), required=True)
    args = parser.parse_args()

    bowl_urdf = args.bowl_asset_root / "urdf/robotwin_002_bowl_model3.urdf"
    bowl_manifest_path = args.bowl_asset_root / "manifest.json"
    for path in (args.mantis_urdf, bowl_urdf, bowl_manifest_path):
        if not path.is_file():
            parser.error(f"required asset file does not exist: {path}")
    port = load_json(args.port)
    source_task = load_json(args.source_task)
    scene_contract = load_json(args.scene_contract)
    validate_genesis_scene_contract(scene_contract, source_task, port)
    contact = scene_contract["bimanual_rim_hook_probe"]
    seed = int(contact["seed"])
    reset = sample_source_reset_poses(seed=seed)
    selected = next(
        pose
        for pose in reset
        if pose.name == contact["bowl"]
    )
    run_dir = args.ops_root / args.run_id
    begun = False
    receipt_written = False

    try:
        begin_run(
            args.ops_root,
            args.run_id,
            {
                "phase": "genesis_bimanual_horizontal_rim_hook_ik_grid",
                "backend": args.backend,
                "seed": seed,
                "bowl": selected.name,
                "scene_contract_sha256": sha256_file(args.scene_contract),
                "port_config_sha256": sha256_file(args.port),
                "mantis_urdf_sha256": sha256_file(args.mantis_urdf),
                "bowl_urdf_sha256": sha256_file(bowl_urdf),
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
        table = scene.add_entity(
            gs.morphs.Plane(
                pos=(0.0, 0.0, float(scene_contract["world"]["table_plane_z_m"])),
                fixed=True,
            )
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
        bowls = [
            scene.add_entity(
                gs.morphs.URDF(
                    file=str(bowl_urdf.resolve()),
                    pos=pose.position_xyz_m,
                    quat=pose.quaternion_wxyz,
                    fixed=True,
                    merge_fixed_links=False,
                    recompute_inertia=False,
                    file_meshes_are_zup=True,
                ),
                name=pose.name,
            )
            for pose in reset
        ]
        selected_index = [pose.name for pose in reset].index(selected.name)
        selected_bowl = bowls[selected_index]
        other_bowls = [bowl for index, bowl in enumerate(bowls) if index != selected_index]
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
        initial_orientations = {side: _vector(links[side].get_quat()) for side in SIDES}
        geom_labels = {
            int(geom.idx): f"mantis:{geom.link.name}" for geom in robot.geoms
        }
        geom_labels.update(
            {int(geom.idx): f"table:{geom.link.name}" for geom in table.geoms}
        )
        for pose, bowl in zip(reset, bowls):
            geom_labels.update(
                {int(geom.idx): f"{pose.name}:{geom.link.name}" for geom in bowl.geoms}
            )
        half_spans_m = (0.105, 0.110, 0.115, 0.120, 0.125, 0.130, 0.135)
        z_values_m = (0.80, 0.81, 0.82, 0.83, 0.84)
        # Negative tilt places the selected hook finger below the rim before
        # closure.  Positive tilt is retained as the measured top-rim control.
        jaw_tilt_degrees = (-55.0, -45.0, -35.0, -25.0, 25.0, 35.0, 45.0, 55.0)
        clearance_half_span_m = float(contact["clearance_half_span_m"])
        target_x, target_y, _ = selected.position_xyz_m
        rows: list[dict[str, Any]] = []

        for half_span_m in half_spans_m:
            for z_m in z_values_m:
                for jaw_tilt_degree in jaw_tilt_degrees:
                    tilt_rad = math.radians(jaw_tilt_degree)
                    tilted_jaw_orientations: dict[str, dict[str, list[float]]] = {}
                    for side, inward_x in (("left", 1.0), ("right", -1.0)):
                        tilted_jaw_orientations[side] = {}
                        for world_y_sign in (1.0, -1.0):
                            name = (
                                f"jaw_tilt_{int(jaw_tilt_degree)}_world_y_"
                                + ("plus" if world_y_sign > 0 else "minus")
                            )
                            tilted_jaw_orientations[side][name] = _quaternion_wxyz_from_axes(
                                [inward_x, 0.0, 0.0],
                                [
                                    0.0,
                                    world_y_sign * math.cos(tilt_rad),
                                    math.sin(tilt_rad),
                                ],
                            )
                    for left_item, right_item in product(
                        tilted_jaw_orientations["left"].items(),
                        tilted_jaw_orientations["right"].items(),
                    ):
                        left_name, left_orientation = left_item
                        right_name, right_orientation = right_item
                        orientations = {
                            "left": np.asarray(left_orientation, dtype=float),
                            "right": np.asarray(right_orientation, dtype=float),
                        }
                        orientation_names = {"left": left_name, "right": right_name}
                        stages = (
                            (
                                "left_separate_high",
                                {"left": np.asarray([target_x - clearance_half_span_m, 0.025, 0.92])},
                                {"left": np.asarray(initial_orientations["left"])},
                            ),
                            (
                                "left_roll_high",
                                {"left": np.asarray([target_x - clearance_half_span_m, 0.025, 0.92])},
                                {"left": orientations["left"]},
                            ),
                            (
                                "right_roll_high",
                                {"right": np.asarray([target_x + clearance_half_span_m, 0.025, 0.92])},
                                {"right": orientations["right"]},
                            ),
                            (
                                "side_clearance",
                                {
                                    "left": np.asarray([target_x - clearance_half_span_m, target_y, 0.90]),
                                    "right": np.asarray([target_x + clearance_half_span_m, target_y, 0.90]),
                                },
                                orientations,
                            ),
                            (
                                "pregrasp",
                                {
                                    "left": np.asarray([target_x - clearance_half_span_m, target_y, z_m]),
                                    "right": np.asarray([target_x + clearance_half_span_m, target_y, z_m]),
                                },
                                orientations,
                            ),
                            (
                                "approach",
                                {
                                    "left": np.asarray([target_x - half_span_m, target_y, z_m]),
                                    "right": np.asarray([target_x + half_span_m, target_y, z_m]),
                                },
                                orientations,
                            ),
                        )
                        combined = open_qpos.copy()
                        stage_rows: list[dict[str, Any]] = []
                        route_pass = True
                        failure_stage: str | None = None
                        for stage_name, targets, stage_orientations in stages:
                            stage_row: dict[str, Any] = {"stage": stage_name, "arms": {}}
                            for side in targets:
                                qpos, error = robot.inverse_kinematics(
                                    links[side],
                                    pos=targets[side],
                                    quat=stage_orientations[side],
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
                                stage_row["arms"][side] = {
                                    "target_xyz_m": targets[side].tolist(),
                                    "position_error_m": position_error,
                                    "rotation_error_rad": rotation_error,
                                    "ik_pass": position_error
                                    <= float(ik["position_tolerance_m"])
                                    and rotation_error
                                    <= float(ik["rotation_tolerance_rad"]),
                                }
                            stage_row["ik_pass"] = all(
                                arm["ik_pass"] for arm in stage_row["arms"].values()
                            )
                            unexpected_pairs: list[str] = []
                            table_pairs: list[str] = []
                            other_bowl_pairs: list[str] = []
                            selected_bowl_pairs: list[str] = []
                            if stage_row["ik_pass"]:
                                robot.set_qpos(combined)
                                scene.step()
                                unexpected_pairs = _unexpected_self_pairs(
                                    robot.get_contacts(), geom_labels
                                )
                                table_pairs = _all_pairs(
                                    robot.get_contacts(with_entity=table), geom_labels
                                )
                                for other_bowl in other_bowls:
                                    other_bowl_pairs.extend(
                                        _all_pairs(
                                            robot.get_contacts(with_entity=other_bowl),
                                            geom_labels,
                                        )
                                    )
                                selected_bowl_pairs = _all_pairs(
                                    robot.get_contacts(with_entity=selected_bowl), geom_labels
                                )
                            stage_row["unexpected_self_collision_pairs"] = unexpected_pairs
                            stage_row["table_contact_pairs"] = sorted(set(table_pairs))
                            stage_row["other_bowl_contact_pairs"] = sorted(
                                set(other_bowl_pairs)
                            )
                            stage_row["selected_bowl_contact_pairs"] = selected_bowl_pairs
                            stage_row["stage_pass"] = (
                                stage_row["ik_pass"]
                                and not unexpected_pairs
                                and not table_pairs
                                and not other_bowl_pairs
                                and (stage_name == "approach" or not selected_bowl_pairs)
                            )
                            stage_rows.append(stage_row)
                            if not stage_row["stage_pass"]:
                                route_pass = False
                                failure_stage = stage_name
                                break
                        row: dict[str, Any] = {
                            "half_span_m": half_span_m,
                            "z_m": z_m,
                            "jaw_tilt_degree": jaw_tilt_degree,
                            "orientation_names": orientation_names,
                            "orientations_wxyz": {
                                side: orientations[side].tolist() for side in SIDES
                            },
                            "stages": stage_rows,
                            "failure_stage": failure_stage,
                            "candidate_pass": route_pass,
                        }
                        if route_pass:
                            row["physical_qpos"] = combined.tolist()
                        rows.append(row)

        passing = [row for row in rows if row["candidate_pass"]]
        preferred = min(
            passing,
            key=lambda row: (
                abs(row["half_span_m"] - 0.12),
                abs(row["z_m"] - 0.82),
                abs(abs(row["jaw_tilt_degree"]) - 35.0),
                row["jaw_tilt_degree"] > 0.0,
                not row["orientation_names"]["left"].endswith("world_y_plus"),
                not row["orientation_names"]["right"].endswith("world_y_plus"),
            ),
        ) if passing else None
        receipt = {
            "schema_version": 1,
            "genesis_version": importlib.metadata.version("genesis-world"),
            "backend": args.backend,
            "seed": seed,
            "bowl": selected.name,
            "bowl_center_xyz_m": list(selected.position_xyz_m),
            "clearance_half_span_m": clearance_half_span_m,
            "grasp_semantics": "both wrists remain outside the bowl and approach horizontally; signed jaw-axis tilts test both top-rim contact and below-rim hook placement while the wrist clears the table",
            "geometry_rationale": "a fully vertical 0.150 m wrist centered at the 0.792 m rim intersects the 0.740 m table; the measured positive-35-degree route pressed downward on the top rim, so the signed scan adds negative tilts to search for an upward-supporting contact face",
            "rows": rows,
            "passing_count": len(passing),
            "preferred_passing_candidate": preferred,
            "evidence_boundary": "route-aware bimanual rim-hook IK plus endpoint self/table/other-bowl safety diagnostic; selected-bowl approach contact is observed but no closure, lift, swept-path, or task-success claim",
            "scene_contract_sha256": sha256_file(args.scene_contract),
            "port_config_sha256": sha256_file(args.port),
            "mantis_urdf_sha256": sha256_file(args.mantis_urdf),
            "bowl_urdf_sha256": sha256_file(bowl_urdf),
            "bowl_manifest_sha256": sha256_file(bowl_manifest_path),
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
