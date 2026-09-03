#!/usr/bin/env python3
"""Run a guarded two-arm opposed-pad bowl grasp/lift smoke in Genesis.

The grippers stay closed and act as rigid pads while the arms approach the
outside of one source-scale bowl symmetrically.  The probe never teleports an
object and never claims a complete ``stack_bowls_three`` episode or G1.
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
    sample_source_reset_poses,
    validate_genesis_scene_contract,
)


ROOT = Path(__file__).resolve().parents[1]
SIDES = ("left", "right")
STAGES = (
    "left_separate_high",
    "left_rotate_high",
    "right_rotate_high",
    "side_clearance",
    "pregrasp",
    "approach",
    "hold",
    "lift",
)
RIM_HOOK_STAGES = (
    "left_separate_high",
    "left_rotate_high",
    "right_rotate_high",
    "side_clearance",
    "pregrasp",
    "approach",
    "close",
    "hold",
    "lift",
)
SINGLE_BOWL_PLACE_STAGES = RIM_HOOK_STAGES + (
    "transport",
    "place",
    "release",
    "retreat",
    "stabilize",
)
SINGLE_BOWL_SLIDE_STAGES = (
    "left_separate_high",
    "left_rotate_high",
    "right_rotate_high",
    "side_clearance",
    "pregrasp",
    "approach",
    "hold",
    "slide",
    "retreat",
    "stabilize",
)


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
    if not isinstance(contact_info, dict) or "geom_a" not in contact_info:
        raise RuntimeError("Genesis get_contacts returned an unexpected structure")
    geom_a = contact_info["geom_a"]
    if not hasattr(geom_a, "shape") or len(geom_a.shape) < 1:
        raise RuntimeError("Genesis contact geom_a has no row dimension")
    return int(geom_a.shape[-1] if len(geom_a.shape) > 1 else geom_a.shape[0])


def _robot_geom_label(geom: Any) -> str:
    metadata = getattr(geom, "metadata", {})
    metadata = metadata if isinstance(metadata, dict) else {}
    collision_name = metadata.get("name")
    if collision_name:
        suffix = str(collision_name)
    elif metadata.get("mesh_path"):
        suffix = "source_mesh_collision"
    else:
        geom_type = getattr(getattr(geom, "type", None), "name", None)
        suffix = f"anonymous_{str(geom_type or 'geom').lower()}_collision"
    return f"mantis:{geom.link.name}:{suffix}"


def _record_contact_pairs(
    contact_info: Any,
    geom_labels: dict[int, str],
    histogram: dict[str, int],
) -> None:
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
        pair = " <> ".join(labels)
        histogram[pair] = histogram.get(pair, 0) + 1


def _record_self_contact_pairs(
    contact_info: Any,
    geom_labels: dict[int, str],
    histogram: dict[str, int],
) -> int:
    count = 0
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
        if all(label.startswith("mantis:") for label in labels):
            pair = " <> ".join(labels)
            if any(
                all(label.startswith(f"mantis:{side}_clamp") for label in labels)
                for side in SIDES
            ):
                continue
            histogram[pair] = histogram.get(pair, 0) + 1
            count += 1
    return count


def _matrix_rows(value: Any, width: int) -> list[list[float]]:
    import numpy as np

    array = np.asarray(_vector(value), dtype=float)
    if array.size == 0:
        return []
    if array.size % width:
        raise RuntimeError(
            f"Genesis contact field has {array.size} values, not a multiple of {width}"
        )
    return array.reshape((-1, width)).tolist()


def _selected_bowl_force_sample(
    contact_info: Any,
    selected_bowl_geom_ids: set[int],
    geom_labels: dict[int, str],
    bowl_position_z_m: float,
) -> dict[str, Any]:
    """Normalize Genesis A/B forces to the force applied to the selected bowl."""

    import numpy as np

    geom_a = [int(value) for value in _vector(contact_info["geom_a"])]
    geom_b = [int(value) for value in _vector(contact_info["geom_b"])]
    positions = _matrix_rows(contact_info["position"], 3)
    forces_a = _matrix_rows(contact_info["force_a"], 3)
    forces_b = _matrix_rows(contact_info["force_b"], 3)
    row_count = len(geom_a)
    if not all(
        len(values) == row_count
        for values in (geom_b, positions, forces_a, forces_b)
    ):
        raise RuntimeError("Genesis contact fields have inconsistent row counts")

    net_force = np.zeros(3, dtype=float)
    clamp_force_by_side = {side: np.zeros(3, dtype=float) for side in SIDES}
    clamp_force_by_geom: dict[str, np.ndarray] = {}
    clamp_position_z_by_side: dict[str, list[float]] = {side: [] for side in SIDES}
    clamp_position_z_by_geom: dict[str, list[float]] = {}
    clamp_positions_by_geom: dict[str, list[list[float]]] = {}
    clamp_contact_count_by_side = {side: 0 for side in SIDES}
    clamp_contact_count_by_geom: dict[str, int] = {}
    for index, (a, b) in enumerate(zip(geom_a, geom_b)):
        a_is_bowl = a in selected_bowl_geom_ids
        b_is_bowl = b in selected_bowl_geom_ids
        if a_is_bowl == b_is_bowl:
            raise RuntimeError("selected-bowl contact row does not contain exactly one bowl geom")
        bowl_force = np.asarray(forces_a[index] if a_is_bowl else forces_b[index])
        robot_geom = b if a_is_bowl else a
        robot_label = geom_labels.get(robot_geom, f"geom:{robot_geom}")
        net_force += bowl_force
        for side in SIDES:
            if robot_label.startswith(f"mantis:{side}_clamp"):
                clamp_force_by_side[side] += bowl_force
                clamp_position_z_by_side[side].append(float(positions[index][2]))
                clamp_contact_count_by_side[side] += 1
                clamp_force_by_geom.setdefault(robot_label, np.zeros(3, dtype=float))
                clamp_force_by_geom[robot_label] += bowl_force
                clamp_position_z_by_geom.setdefault(robot_label, []).append(
                    float(positions[index][2])
                )
                clamp_positions_by_geom.setdefault(robot_label, []).append(
                    [float(value) for value in positions[index]]
                )
                clamp_contact_count_by_geom[robot_label] = (
                    clamp_contact_count_by_geom.get(robot_label, 0) + 1
                )
                break

    return {
        "bowl_position_z_m": float(bowl_position_z_m),
        "contact_count": row_count,
        "net_force_on_bowl_n": net_force.tolist(),
        "clamp_force_on_bowl_by_side_n": {
            side: clamp_force_by_side[side].tolist() for side in SIDES
        },
        "clamp_contact_count_by_side": clamp_contact_count_by_side,
        "clamp_force_on_bowl_by_geom_n": {
            label: force.tolist() for label, force in sorted(clamp_force_by_geom.items())
        },
        "clamp_contact_count_by_geom": dict(sorted(clamp_contact_count_by_geom.items())),
        "clamp_contact_position_z_range_m_by_side": {
            side: (
                [
                    min(clamp_position_z_by_side[side]),
                    max(clamp_position_z_by_side[side]),
                ]
                if clamp_position_z_by_side[side]
                else None
            )
            for side in SIDES
        },
        "clamp_contact_position_z_range_m_by_geom": {
            label: [min(values), max(values)]
            for label, values in sorted(clamp_position_z_by_geom.items())
        },
        "clamp_contact_position_xyz_bounds_m_by_geom": {
            label: {
                "minimum": [min(row[axis] for row in values) for axis in range(3)],
                "maximum": [max(row[axis] for row in values) for axis in range(3)],
            }
            for label, values in sorted(clamp_positions_by_geom.items())
        },
    }


def _summarize_selected_bowl_force_samples(
    samples_by_stage: dict[str, list[dict[str, Any]]],
    nominal_weight_n: float,
) -> dict[str, dict[str, Any]]:
    import numpy as np

    result: dict[str, dict[str, Any]] = {}
    for stage, samples in samples_by_stage.items():
        contacting = [sample for sample in samples if sample["contact_count"] > 0]
        net_force_z = [float(sample["net_force_on_bowl_n"][2]) for sample in contacting]
        side_force_z = {
            side: [
                float(sample["clamp_force_on_bowl_by_side_n"][side][2])
                for sample in contacting
            ]
            for side in SIDES
        }
        geometry_labels = sorted(
            {
                label
                for sample in contacting
                for label in sample["clamp_force_on_bowl_by_geom_n"]
            }
        )
        geometry_force_z = {
            label: [
                float(sample["clamp_force_on_bowl_by_geom_n"].get(label, [0.0, 0.0, 0.0])[2])
                for sample in contacting
            ]
            for label in geometry_labels
        }
        result[stage] = {
            "sample_count": len(samples),
            "contact_sample_count": len(contacting),
            "net_force_on_bowl_z_n": (
                {
                    "minimum": min(net_force_z),
                    "maximum": max(net_force_z),
                    "mean": float(np.mean(net_force_z)),
                }
                if net_force_z
                else None
            ),
            "mean_upward_support_ratio_to_nominal_weight": (
                float(np.mean(net_force_z)) / nominal_weight_n
                if net_force_z and nominal_weight_n > 0.0
                else None
            ),
            "clamp_force_on_bowl_z_n_by_side": {
                side: (
                    {
                        "minimum": min(side_force_z[side]),
                        "maximum": max(side_force_z[side]),
                        "mean": float(np.mean(side_force_z[side])),
                    }
                    if side_force_z[side]
                    else None
                )
                for side in SIDES
            },
            "clamp_force_on_bowl_z_n_by_geom": {
                label: {
                    "minimum": min(values),
                    "maximum": max(values),
                    "mean": float(np.mean(values)),
                }
                for label, values in geometry_force_z.items()
            },
        }
    return result


def _tcp_world_position(link: Any, local_point: Any) -> list[float]:
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
    parser.add_argument(
        "--probe-contract",
        choices=("bimanual_contact_probe", "bimanual_rim_hook_probe"),
        default="bimanual_contact_probe",
    )
    parser.add_argument(
        "--candidate-lift-distance-m",
        type=float,
        help=(
            "experimental rim-hook lift command; must be at least the frozen contract "
            "value and does not change the fixed success threshold"
        ),
    )
    parser.add_argument(
        "--candidate-lift-duration-s",
        type=float,
        help=(
            "experimental rim-hook lift duration; must be at least the frozen contract "
            "value and is recorded in the receipt"
        ),
    )
    parser.add_argument(
        "--candidate-lift-gripper-open-fraction",
        type=float,
        help=(
            "experimental tighter lift/transport gripper fraction; must be no "
            "greater than the frozen lift fraction"
        ),
    )
    parser.add_argument(
        "--single-bowl-place",
        action="store_true",
        help="continue the rim-hook probe through target transport, release, and stabilization",
    )
    parser.add_argument(
        "--single-bowl-slide",
        action="store_true",
        help="use the opposed-pad probe to slide one bowl to the target on the table",
    )
    parser.add_argument(
        "--cartesian-transport-waypoints",
        type=int,
        default=1,
        help=(
            "experimental number of synchronized Cartesian IK waypoints for both "
            "transport and placement; values above one require --single-bowl-place"
        ),
    )
    parser.add_argument(
        "--candidate-transport-duration-s",
        type=float,
        help=(
            "experimental slower total transport duration; requires "
            "--single-bowl-place and cannot be shorter than the frozen duration"
        ),
    )
    parser.add_argument(
        "--candidate-transport-half-span-m",
        type=float,
        help=(
            "experimental inward shelf span for transport and placement; requires "
            "--single-bowl-place and cannot exceed the frozen lift half-span"
        ),
    )
    parser.add_argument(
        "--candidate-transport-tcp-z-m",
        type=float,
        help=(
            "experimental lower constant transport TCP height; requires "
            "--single-bowl-place and must remain at or above the placement height"
        ),
    )
    parser.add_argument(
        "--smooth-transport-profile",
        action="store_true",
        help=(
            "execute all transport and placement IK waypoints with one quintic "
            "time profile; requires --single-bowl-place"
        ),
    )
    parser.add_argument(
        "--candidate-right-tcp-z-offset-m",
        type=float,
        help=(
            "experimental signed right-arm TCP height correction for the rim-hook "
            "probe; absolute value must not exceed 0.005 m"
        ),
    )
    parser.add_argument(
        "--contact-weld-transport",
        action="store_true",
        help=(
            "activate a Genesis dynamic weld as an idealized suction constraint "
            "only after verified clamp-to-bowl contact; requires --single-bowl-place"
        ),
    )
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

    contract = scene_contract[args.probe_contract]
    is_rim_hook = args.probe_contract == "bimanual_rim_hook_probe"
    right_tcp_z_offset_override = args.candidate_right_tcp_z_offset_m is not None
    right_tcp_z_offset_m = (
        0.0
        if args.candidate_right_tcp_z_offset_m is None
        else float(args.candidate_right_tcp_z_offset_m)
    )
    if right_tcp_z_offset_override:
        if not is_rim_hook:
            parser.error("right TCP height correction requires the rim-hook probe")
        if abs(right_tcp_z_offset_m) > 0.005:
            parser.error("right TCP height correction must be within +/-0.005 m")
    if args.single_bowl_place and not is_rim_hook:
        parser.error("single-bowl placement is valid only for the rim-hook probe")
    if args.single_bowl_slide and is_rim_hook:
        parser.error("single-bowl slide requires the opposed-pad probe")
    if args.single_bowl_place and args.single_bowl_slide:
        parser.error("single-bowl place and slide modes are mutually exclusive")
    if not 1 <= args.cartesian_transport_waypoints <= 16:
        parser.error("--cartesian-transport-waypoints must be in [1, 16]")
    if args.cartesian_transport_waypoints > 1 and not args.single_bowl_place:
        parser.error(
            "Cartesian transport waypoints above one require --single-bowl-place"
        )
    if args.smooth_transport_profile and not args.single_bowl_place:
        parser.error("smooth transport profile requires --single-bowl-place")
    if args.contact_weld_transport and not args.single_bowl_place:
        parser.error("contact-weld transport requires --single-bowl-place")
    if args.contact_weld_transport and not is_rim_hook:
        parser.error("contact-weld transport requires the rim-hook probe")
    transport_duration_override = args.candidate_transport_duration_s is not None
    if transport_duration_override:
        if not args.single_bowl_place:
            parser.error(
                "candidate transport duration requires --single-bowl-place"
            )
        base_transport_duration = float(contract["transport_duration_s"])
        candidate_transport_duration = float(args.candidate_transport_duration_s)
        if not base_transport_duration <= candidate_transport_duration <= 12.0:
            parser.error(
                "candidate transport duration must be between the frozen duration "
                "and 12 seconds"
            )
        contract = dict(contract)
        contract["transport_duration_s"] = candidate_transport_duration
    transport_half_span_override = (
        args.candidate_transport_half_span_m is not None
    )
    if transport_half_span_override:
        if not args.single_bowl_place:
            parser.error(
                "candidate transport half-span requires --single-bowl-place"
            )
        base_transport_half_span = float(contract["lift_half_span_m"])
        candidate_transport_half_span = float(
            args.candidate_transport_half_span_m
        )
        if not 0.09 <= candidate_transport_half_span <= base_transport_half_span:
            parser.error(
                "candidate transport half-span must be between 0.09 m and the "
                "frozen lift half-span"
            )
        contract = dict(contract)
        contract["transport_half_span_m"] = candidate_transport_half_span
    transport_tcp_z_override = args.candidate_transport_tcp_z_m is not None
    if transport_tcp_z_override:
        if not args.single_bowl_place:
            parser.error(
                "candidate transport TCP height requires --single-bowl-place"
            )
        candidate_transport_tcp_z = float(args.candidate_transport_tcp_z_m)
        minimum_transport_tcp_z = float(contract["place_tcp_z_m"])
        base_transport_tcp_z = float(contract["transport_tcp_z_m"])
        if not minimum_transport_tcp_z <= candidate_transport_tcp_z <= base_transport_tcp_z:
            parser.error(
                "candidate transport TCP height must be between the placement "
                "height and the frozen transport height"
            )
        contract = dict(contract)
        contract["transport_tcp_z_m"] = candidate_transport_tcp_z
    candidate_override = (
        args.candidate_lift_distance_m is not None
        or args.candidate_lift_duration_s is not None
        or args.candidate_lift_gripper_open_fraction is not None
    )
    if candidate_override:
        if not is_rim_hook:
            parser.error("candidate lift overrides are valid only for the rim-hook probe")
        base_distance = float(contract["lift_distance_m"])
        base_duration = float(contract["lift_duration_s"])
        distance = (
            base_distance
            if args.candidate_lift_distance_m is None
            else float(args.candidate_lift_distance_m)
        )
        duration = (
            base_duration
            if args.candidate_lift_duration_s is None
            else float(args.candidate_lift_duration_s)
        )
        base_lift_gripper_fraction = float(
            contract["lift_gripper_open_fraction"]
        )
        lift_gripper_fraction = (
            base_lift_gripper_fraction
            if args.candidate_lift_gripper_open_fraction is None
            else float(args.candidate_lift_gripper_open_fraction)
        )
        if not base_distance <= distance <= 0.06:
            parser.error(
                "candidate lift distance must be between the frozen command and 0.06 m"
            )
        if not base_duration <= duration <= 2.0:
            parser.error(
                "candidate lift duration must be between the frozen duration and 2.0 s"
            )
        if not 0.3 <= lift_gripper_fraction <= base_lift_gripper_fraction:
            parser.error(
                "candidate lift gripper fraction must be between 0.3 and the "
                "frozen lift fraction"
            )
        contract = dict(contract)
        contract["protocol_version"] = "bimanual_shelf_lift_candidate_v22"
        contract["lift_distance_m"] = distance
        contract["lift_duration_s"] = duration
        contract["lift_gripper_open_fraction"] = lift_gripper_fraction
    expected_boundary = (
        "bimanual rim-hook single-bowl contact smoke only; not a complete episode or G1"
        if is_rim_hook
        else "bimanual single-bowl contact smoke only; not a complete episode or G1"
    )
    if contract.get("claim_boundary") != expected_boundary:
        raise RuntimeError("bimanual contact probe claim boundary changed")
    transport_candidate_override = (
        args.cartesian_transport_waypoints > 1
        or transport_duration_override
        or transport_half_span_override
        or transport_tcp_z_override
        or args.smooth_transport_profile
        or right_tcp_z_offset_override
        or args.contact_weld_transport
    )
    if args.contact_weld_transport:
        active_protocol_version = "contact_triggered_suction_transport_candidate_v30"
    elif right_tcp_z_offset_override:
        active_protocol_version = "bimanual_shelf_right_height_candidate_v29"
    elif args.smooth_transport_profile:
        active_protocol_version = "bimanual_shelf_quintic_transport_candidate_v28"
    elif transport_tcp_z_override:
        active_protocol_version = (
            "bimanual_shelf_low_inward_transport_candidate_v27"
            if transport_half_span_override
            else "bimanual_shelf_low_transport_candidate_v27"
        )
    elif transport_half_span_override:
        active_protocol_version = (
            "bimanual_shelf_inward_preloaded_transport_candidate_v26"
            if args.candidate_lift_gripper_open_fraction is not None
            else "bimanual_shelf_inward_transport_candidate_v26"
        )
    else:
        active_protocol_version = (
            (
                (
                    "bimanual_shelf_preloaded_transport_candidate_v25"
                    if args.candidate_lift_gripper_open_fraction is not None
                    else "bimanual_shelf_slow_cartesian_transport_candidate_v24"
                )
                if transport_duration_override
                else (
                    "bimanual_shelf_preloaded_lift_candidate_v25"
                    if args.candidate_lift_gripper_open_fraction is not None
                    else "bimanual_shelf_cartesian_transport_candidate_v23"
                )
            )
            if transport_candidate_override
            else (
                "bimanual_shelf_preloaded_lift_candidate_v25"
                if args.candidate_lift_gripper_open_fraction is not None
                else contract["protocol_version"]
            )
        )
    active_stages = (
        SINGLE_BOWL_PLACE_STAGES
        if args.single_bowl_place
        else (
            SINGLE_BOWL_SLIDE_STAGES
            if args.single_bowl_slide
            else (RIM_HOOK_STAGES if is_rim_hook else STAGES)
        )
    )
    seed = int(contract["seed"])
    reset = sample_source_reset_poses(seed=seed)
    selected_pose = next(pose for pose in reset if pose.name == contract["bowl"])
    run_dir = args.ops_root / args.run_id
    begun = False
    receipt_written = False

    try:
        begin_run(
            args.ops_root,
            args.run_id,
            {
                "phase": (
                    "genesis_bimanual_horizontal_rim_hook_contact_probe"
                    if is_rim_hook
                    else "genesis_bimanual_bowl_contact_probe"
                ),
                "protocol_version": active_protocol_version,
                "seed": seed,
                "bowl": selected_pose.name,
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
                    fixed=False,
                    merge_fixed_links=False,
                    recompute_inertia=False,
                    file_meshes_are_zup=True,
                ),
                name=pose.name,
            )
            for pose in reset
        ]
        selected_index = [pose.name for pose in reset].index(selected_pose.name)
        selected_bowl = bowls[selected_index]
        other_bowls = [bowl for index, bowl in enumerate(bowls) if index != selected_index]
        scene.build()

        geom_labels = {int(geom.idx): _robot_geom_label(geom) for geom in robot.geoms}
        geom_labels.update({int(geom.idx): f"table:{geom.link.name}" for geom in table.geoms})
        for pose, bowl in zip(reset, bowls):
            geom_labels.update(
                {int(geom.idx): f"{pose.name}:{geom.link.name}" for geom in bowl.geoms}
            )
        selected_bowl.set_friction(float(contract["bowl_friction_coefficient"]))
        finger_geom_labels: list[str] = []
        for geom in robot.geoms:
            if any(geom.link.name.startswith(f"{side}_clamp") for side in SIDES):
                geom.set_friction(float(contract["finger_friction_coefficient"]))
                finger_geom_labels.append(geom_labels[int(geom.idx)])
        if not all(any(label.startswith(f"mantis:{side}_clamp") for label in finger_geom_labels) for side in SIDES):
            raise RuntimeError("Genesis did not expose clamp geometry for both Mantis arms")

        physical_names = port["target"]["physical_joint_order"]
        all_indices = _dof_indices(robot, physical_names)
        arm_indices_by_side = {
            side: _dof_indices(robot, arm_dof_names(side)) for side in SIDES
        }
        all_arm_indices = [
            index for side in SIDES for index in arm_indices_by_side[side]
        ]
        gripper_names_by_side = {
            side: list(
                port["assets"]["virtual_gripper_mapping"]["coefficients"][
                    f"{side}_gripper_joint"
                ]
            )
            for side in SIDES
        }
        gripper_indices_by_side = {
            side: _dof_indices(robot, gripper_names_by_side[side]) for side in SIDES
        }
        all_gripper_indices = [
            index for side in SIDES for index in gripper_indices_by_side[side]
        ]
        arm_index_set = set(all_arm_indices)
        kp = [
            float(contract["arm_kp"] if index in arm_index_set else contract["gripper_kp"])
            for index in all_indices
        ]
        kv = [
            float(contract["arm_kv"] if index in arm_index_set else contract["gripper_kv"])
            for index in all_indices
        ]
        lower_force = [
            -float(
                contract["arm_force_limit"]
                if index in arm_index_set
                else contract["gripper_force_limit"]
            )
            for index in all_indices
        ]
        robot.set_dofs_kp(kp, dofs_idx_local=all_indices)
        robot.set_dofs_kv(kv, dofs_idx_local=all_indices)
        robot.set_dofs_force_range(
            lower_force,
            [-value for value in lower_force],
            dofs_idx_local=all_indices,
        )

        closed_qpos = np.asarray(physical_pose(port, 0.0), dtype=float)
        open_qpos = np.asarray(physical_pose(port, 1.0), dtype=float)
        grasp_qpos = np.asarray(
            physical_pose(
                port,
                float(contract.get("gripper_hold_open_fraction", 0.0)),
            ),
            dtype=float,
        )
        lift_grasp_qpos = np.asarray(
            physical_pose(
                port,
                float(
                    contract.get(
                        "lift_gripper_open_fraction",
                        contract.get("gripper_hold_open_fraction", 0.0),
                    )
                ),
            ),
            dtype=float,
        )
        navigation_qpos = open_qpos if is_rim_hook else closed_qpos
        robot.set_qpos(navigation_qpos)
        robot.control_dofs_position(navigation_qpos, dofs_idx_local=all_indices)
        for _ in range(25):
            scene.step()

        tcp = scene_contract["tcp"]
        ik = scene_contract["ik_gate"]
        links = {side: robot.get_link(tcp[side]["link"]) for side in SIDES}
        local_points = {
            side: np.asarray(tcp[side]["local_point_xyz_m"], dtype=float)
            for side in SIDES
        }
        orientations = {
            side: np.asarray(
                contract[
                    "slide_orientations_wxyz"
                    if args.single_bowl_slide
                    else "orientations_wxyz"
                ][side],
                dtype=float,
            )
            for side in SIDES
        }
        separation_orientations = {
            side: np.asarray(contract["separation_orientations_wxyz"][side], dtype=float)
            for side in SIDES
        }
        target_x, target_y, _ = selected_pose.position_xyz_m

        def targets(
            half_span_m: float,
            y_m: float,
            z_m: float,
            *,
            center_x_m: float = target_x,
        ) -> dict[str, np.ndarray]:
            return {
                "left": np.asarray([center_x_m - half_span_m, y_m, z_m], dtype=float),
                "right": np.asarray(
                    [
                        center_x_m + half_span_m,
                        y_m,
                        z_m + right_tcp_z_offset_m,
                    ],
                    dtype=float,
                ),
            }

        target_positions = {
            "left_separate_high": {
                "left": targets(
                    float(contract["clearance_half_span_m"]),
                    float(contract["separation_y_m"]),
                    float(contract["separation_z_m"]),
                )["left"]
            },
            "left_rotate_high": {
                "left": targets(
                    float(contract["clearance_half_span_m"]),
                    float(contract["rotate_high_y_m"]),
                    float(contract["rotate_high_z_m"]),
                )["left"]
            },
            "right_rotate_high": {
                "right": targets(
                    float(contract["clearance_half_span_m"]),
                    float(contract["rotate_high_y_m"]),
                    float(contract["rotate_high_z_m"]),
                )["right"]
            },
            "side_clearance": targets(
                float(contract["clearance_half_span_m"]),
                target_y,
                float(contract["clearance_z_m"]),
            ),
            "pregrasp": targets(
                float(contract["clearance_half_span_m"]),
                target_y,
                float(contract["grasp_z_m"]),
            ),
            "approach": targets(
                float(contract["grasp_half_span_m"]),
                target_y,
                float(contract["grasp_z_m"]),
            ),
            "lift": targets(
                float(contract.get("lift_half_span_m", contract["grasp_half_span_m"])),
                target_y,
                float(contract["grasp_z_m"] + contract["lift_distance_m"]),
            ),
        }
        if args.single_bowl_place:
            place_x, place_y = (float(value) for value in contract["transport_target_xy_m"])
            transport_half_span = float(
                contract.get("transport_half_span_m", contract["lift_half_span_m"])
            )
            target_positions.update(
                {
                    "transport": targets(
                        transport_half_span,
                        place_y,
                        float(contract["transport_tcp_z_m"]),
                        center_x_m=place_x,
                    ),
                    "place": targets(
                        transport_half_span,
                        place_y,
                        float(contract["place_tcp_z_m"]),
                        center_x_m=place_x,
                    ),
                    "retreat": targets(
                        float(contract["clearance_half_span_m"]),
                        place_y,
                        float(contract["clearance_z_m"]),
                        center_x_m=place_x,
                    ),
                }
            )
        if args.single_bowl_slide:
            slide_x, slide_y = (float(value) for value in contract["slide_target_xy_m"])
            target_positions.update(
                {
                    "slide": targets(
                        float(contract["grasp_half_span_m"]),
                        slide_y,
                        float(contract["grasp_z_m"]),
                        center_x_m=slide_x,
                    ),
                    "retreat": targets(
                        float(contract["clearance_half_span_m"]),
                        slide_y,
                        float(contract["clearance_z_m"]),
                        center_x_m=slide_x,
                    ),
                }
            )

        ik_errors: dict[str, dict[str, dict[str, float]]] = {}

        def solve_stage(stage: str, initial: np.ndarray) -> np.ndarray:
            combined = initial.copy()
            ik_errors[stage] = {}
            for side in target_positions[stage]:
                best: tuple[float, float, np.ndarray] | None = None
                for candidate_initial in (combined, navigation_qpos):
                    qpos, error = robot.inverse_kinematics(
                        links[side],
                        pos=target_positions[stage][side],
                        quat=(
                            separation_orientations[side]
                            if stage == "left_separate_high"
                            else orientations[side]
                        ),
                        local_point=local_points[side],
                        init_qpos=candidate_initial,
                        respect_joint_limit=True,
                        max_samples=int(ik["max_samples"]),
                        max_solver_iters=int(ik["max_solver_iters"]),
                        dofs_idx_local=arm_indices_by_side[side],
                        return_error=True,
                    )
                    error_vector = _vector(error)
                    position_error = math.sqrt(sum(value * value for value in error_vector[:3]))
                    rotation_error = math.sqrt(sum(value * value for value in error_vector[3:]))
                    candidate_qpos = np.asarray(_vector(qpos), dtype=float)
                    for index in all_indices:
                        if index not in arm_indices_by_side[side]:
                            candidate_qpos[index] = combined[index]
                    if best is None or (position_error, rotation_error) < (best[0], best[1]):
                        best = (position_error, rotation_error, candidate_qpos)
                    if position_error <= float(ik["position_tolerance_m"]) and rotation_error <= float(
                        ik["rotation_tolerance_rad"]
                    ):
                        break
                assert best is not None
                ik_errors[stage][side] = {
                    "position_error_m": best[0],
                    "rotation_error_rad": best[1],
                }
                if best[0] > float(ik["position_tolerance_m"]) or best[1] > float(
                    ik["rotation_tolerance_rad"]
                ):
                    raise RuntimeError(
                        f"{stage} {side} IK error exceeds tolerance: "
                        f"position={best[0]:.6f}, rotation={best[1]:.6f}"
                    )
                combined = best[2]
            for index in all_gripper_indices:
                combined[index] = navigation_qpos[index]
            return combined

        qpos_by_stage: dict[str, np.ndarray] = {}
        transport_qpos_path: list[np.ndarray] = []
        place_qpos_path: list[np.ndarray] = []
        previous = navigation_qpos
        solve_stages = [
            "left_separate_high",
            "left_rotate_high",
            "right_rotate_high",
            "side_clearance",
            "pregrasp",
            "approach",
            "lift",
        ]
        if args.single_bowl_slide:
            solve_stages.remove("lift")
            solve_stages.extend(("slide", "retreat"))
        for stage in solve_stages:
            qpos_by_stage[stage] = solve_stage(stage, previous)
            previous = qpos_by_stage[stage]
        if args.single_bowl_place:
            path_count = args.cartesian_transport_waypoints

            def solve_path(
                stage: str,
                start_positions: dict[str, np.ndarray],
                end_positions: dict[str, np.ndarray],
                initial: np.ndarray,
            ) -> tuple[list[np.ndarray], np.ndarray]:
                path: list[np.ndarray] = []
                current = initial
                for waypoint in range(1, path_count + 1):
                    alpha = waypoint / path_count
                    waypoint_stage = (
                        stage
                        if path_count == 1
                        else f"{stage}_cartesian_{waypoint:02d}_of_{path_count:02d}"
                    )
                    target_positions[waypoint_stage] = {
                        side: start_positions[side]
                        + alpha * (end_positions[side] - start_positions[side])
                        for side in SIDES
                    }
                    current = solve_stage(waypoint_stage, current)
                    path.append(current)
                return path, current

            transport_qpos_path, previous = solve_path(
                "transport",
                target_positions["lift"],
                target_positions["transport"],
                previous,
            )
            qpos_by_stage["transport"] = transport_qpos_path[-1]
            place_qpos_path, previous = solve_path(
                "place",
                target_positions["transport"],
                target_positions["place"],
                previous,
            )
            qpos_by_stage["place"] = place_qpos_path[-1]
            qpos_by_stage["retreat"] = solve_stage("retreat", previous)

        closed_approach_qpos = qpos_by_stage["approach"].copy()
        for index in all_gripper_indices:
            closed_approach_qpos[index] = grasp_qpos[index]
            if is_rim_hook:
                qpos_by_stage["lift"][index] = lift_grasp_qpos[index]
                if args.single_bowl_place:
                    for waypoint_qpos in transport_qpos_path + place_qpos_path:
                        waypoint_qpos[index] = lift_grasp_qpos[index]
                    qpos_by_stage["retreat"][index] = open_qpos[index]

        contact_counts = {stage: [] for stage in active_stages}
        contact_pair_rows_by_stage = {stage: {} for stage in active_stages}
        selected_bowl_force_samples_by_stage = {stage: [] for stage in active_stages}
        table_contact_counts = {stage: [] for stage in active_stages}
        table_contact_pair_rows_by_stage = {stage: {} for stage in active_stages}
        other_bowl_contact_counts = {stage: [] for stage in active_stages}
        other_bowl_contact_pair_rows_by_stage = {stage: {} for stage in active_stages}
        self_contact_counts = {stage: [] for stage in active_stages}
        self_contact_pair_rows_by_stage = {stage: {} for stage in active_stages}
        final_arm_tracking_error: dict[str, float] = {}
        final_gripper_tracking_error: dict[str, float] = {}
        bowl_position_by_stage = {"initial": _vector(selected_bowl.get_pos())}
        tcp_world_position_by_stage = {
            "initial": {
                side: _tcp_world_position(links[side], local_points[side]) for side in SIDES
            }
        }
        sample_interval = int(contract["contact_sample_interval_steps"])
        selected_bowl_geom_ids = {int(geom.idx) for geom in selected_bowl.geoms}
        bowl_mass_kg = float(bowl_manifest["source_physics_receipt"]["mass_kg"])
        nominal_bowl_weight_n = bowl_mass_kg * 9.81
        weld_active = False
        weld_activation_contact_pass = False
        weld_registered_after_add = False
        weld_removed_before_release = False
        weld_link_names = {
            "robot": "left_clamp_left_link",
            "bowl": "bowl_link",
        }
        weld_link_indices: dict[str, int] | None = None

        def weld_pair_registered(robot_link_index: int, bowl_link_index: int) -> bool:
            constraints = scene.rigid_solver.get_weld_constraints()
            link_a = [int(value) for value in _vector(constraints["link_a"])]
            link_b = [int(value) for value in _vector(constraints["link_b"])]
            return any(
                {a, b} == {robot_link_index, bowl_link_index}
                for a, b in zip(link_a, link_b)
            )

        def sample_contacts(stage: str) -> None:
            selected_info = robot.get_contacts(with_entity=selected_bowl)
            contact_counts[stage].append(_contact_count(selected_info))
            _record_contact_pairs(
                selected_info,
                geom_labels,
                contact_pair_rows_by_stage[stage],
            )
            selected_bowl_force_samples_by_stage[stage].append(
                _selected_bowl_force_sample(
                    selected_info,
                    selected_bowl_geom_ids,
                    geom_labels,
                    float(_vector(selected_bowl.get_pos())[2]),
                )
            )
            table_info = robot.get_contacts(with_entity=table)
            table_contact_counts[stage].append(_contact_count(table_info))
            _record_contact_pairs(
                table_info,
                geom_labels,
                table_contact_pair_rows_by_stage[stage],
            )
            other_count = 0
            for other_bowl in other_bowls:
                other_info = robot.get_contacts(with_entity=other_bowl)
                other_count += _contact_count(other_info)
                _record_contact_pairs(
                    other_info,
                    geom_labels,
                    other_bowl_contact_pair_rows_by_stage[stage],
                )
            other_bowl_contact_counts[stage].append(other_count)
            self_info = robot.get_contacts()
            self_contact_counts[stage].append(
                _record_self_contact_pairs(
                    self_info,
                    geom_labels,
                    self_contact_pair_rows_by_stage[stage],
                )
            )

        def command_segment(stage: str, target: np.ndarray, minimum_duration_s: float) -> None:
            start = np.asarray(_vector(robot.get_qpos()), dtype=float)
            duration = max(
                float(minimum_duration_s),
                max(abs(target[index] - start[index]) for index in all_arm_indices),
            )
            steps = max(1, int(math.ceil(duration / dt)))
            for step in range(1, steps + 1):
                alpha = step / steps
                robot.control_dofs_position(start + alpha * (target - start), dofs_idx_local=all_indices)
                scene.step()
                if step % sample_interval == 0 or step == steps:
                    sample_contacts(stage)
            required = int(contract["waypoint_settle_consecutive_steps"])
            settle_steps = max(
                1,
                int(math.ceil(float(contract["waypoint_settle_timeout_s"]) / dt)),
            )
            consecutive = 0
            for settle_step in range(1, settle_steps + 1):
                robot.control_dofs_position(target, dofs_idx_local=all_indices)
                scene.step()
                if settle_step % sample_interval == 0 or settle_step == settle_steps:
                    sample_contacts(stage)
                actual = _vector(robot.get_qpos())
                if _max_error(actual, target.tolist(), all_arm_indices) <= float(
                    contract["maximum_arm_tracking_error_rad"]
                ):
                    consecutive += 1
                    if consecutive >= required:
                        break
                else:
                    consecutive = 0
            actual = _vector(robot.get_qpos())
            final_arm_tracking_error[stage] = _max_error(
                actual, target.tolist(), all_arm_indices
            )
            final_gripper_tracking_error[stage] = _max_error(
                actual, target.tolist(), all_gripper_indices
            )
            bowl_position_by_stage[stage] = _vector(selected_bowl.get_pos())
            tcp_world_position_by_stage[stage] = {
                side: _tcp_world_position(links[side], local_points[side]) for side in SIDES
            }

        def command_smooth_path(
            stage: str,
            path: list[np.ndarray],
            total_duration_s: float,
        ) -> None:
            if not path:
                raise RuntimeError(f"{stage} smooth path is empty")
            start = np.asarray(_vector(robot.get_qpos()), dtype=float)
            nodes = [start, *path]
            steps = max(1, int(math.ceil(float(total_duration_s) / dt)))
            segment_count = len(path)
            for step in range(1, steps + 1):
                progress = step / steps
                smooth = (
                    10.0 * progress**3
                    - 15.0 * progress**4
                    + 6.0 * progress**5
                )
                path_coordinate = min(float(segment_count), smooth * segment_count)
                segment = min(segment_count - 1, int(path_coordinate))
                local_alpha = path_coordinate - segment
                if segment == segment_count - 1 and step == steps:
                    local_alpha = 1.0
                target = nodes[segment] + local_alpha * (
                    nodes[segment + 1] - nodes[segment]
                )
                robot.control_dofs_position(target, dofs_idx_local=all_indices)
                scene.step()
                if step % sample_interval == 0 or step == steps:
                    sample_contacts(stage)
            final_target = path[-1]
            required = int(contract["waypoint_settle_consecutive_steps"])
            settle_steps = max(
                1,
                int(math.ceil(float(contract["waypoint_settle_timeout_s"]) / dt)),
            )
            consecutive = 0
            for settle_step in range(1, settle_steps + 1):
                robot.control_dofs_position(
                    final_target, dofs_idx_local=all_indices
                )
                scene.step()
                if settle_step % sample_interval == 0 or settle_step == settle_steps:
                    sample_contacts(stage)
                actual = _vector(robot.get_qpos())
                if _max_error(
                    actual, final_target.tolist(), all_arm_indices
                ) <= float(contract["maximum_arm_tracking_error_rad"]):
                    consecutive += 1
                    if consecutive >= required:
                        break
                else:
                    consecutive = 0
            actual = _vector(robot.get_qpos())
            final_arm_tracking_error[stage] = _max_error(
                actual, final_target.tolist(), all_arm_indices
            )
            final_gripper_tracking_error[stage] = _max_error(
                actual, final_target.tolist(), all_gripper_indices
            )
            bowl_position_by_stage[stage] = _vector(selected_bowl.get_pos())
            tcp_world_position_by_stage[stage] = {
                side: _tcp_world_position(links[side], local_points[side])
                for side in SIDES
            }

        command_segment(
            "left_separate_high",
            qpos_by_stage["left_separate_high"],
            float(contract["minimum_segment_duration_s"]),
        )
        command_segment(
            "left_rotate_high",
            qpos_by_stage["left_rotate_high"],
            float(contract["minimum_segment_duration_s"]),
        )
        command_segment(
            "right_rotate_high",
            qpos_by_stage["right_rotate_high"],
            float(contract["minimum_segment_duration_s"]),
        )
        command_segment(
            "side_clearance",
            qpos_by_stage["side_clearance"],
            float(contract["minimum_segment_duration_s"]),
        )
        command_segment(
            "pregrasp",
            qpos_by_stage["pregrasp"],
            float(contract["minimum_segment_duration_s"]),
        )
        bowl_z_before_approach = float(_vector(selected_bowl.get_pos())[2])
        command_segment(
            "approach",
            qpos_by_stage["approach"],
            float(contract["approach_duration_s"]),
        )
        hold_target = qpos_by_stage["approach"]
        if is_rim_hook:
            command_segment(
                "close",
                closed_approach_qpos,
                float(contract["gripper_close_duration_s"]),
            )
            hold_target = closed_approach_qpos
        hold_steps = max(
            1,
            int(
                math.ceil(
                    float(
                        contract[
                            "post_close_hold_s"
                            if is_rim_hook
                            else "post_approach_hold_s"
                        ]
                    )
                    / dt
                )
            ),
        )
        for step in range(1, hold_steps + 1):
            robot.control_dofs_position(hold_target, dofs_idx_local=all_indices)
            scene.step()
            if step % sample_interval == 0 or step == hold_steps:
                sample_contacts("hold")
        actual = _vector(robot.get_qpos())
        final_arm_tracking_error["hold"] = _max_error(
            actual, hold_target.tolist(), all_arm_indices
        )
        final_gripper_tracking_error["hold"] = _max_error(
            actual, hold_target.tolist(), all_gripper_indices
        )
        bowl_position_by_stage["hold"] = _vector(selected_bowl.get_pos())
        tcp_world_position_by_stage["hold"] = {
            side: _tcp_world_position(links[side], local_points[side]) for side in SIDES
        }
        if args.contact_weld_transport:
            selected_label = f"{selected_pose.name}:"
            weld_activation_contact_pass = any(
                selected_label in pair
                and f"mantis:{weld_link_names['robot']}:" in pair
                for pair in contact_pair_rows_by_stage["hold"]
            )
            if not weld_activation_contact_pass:
                raise RuntimeError(
                    "refusing suction activation without verified clamp-to-bowl contact"
                )
            suction_link = robot.get_link(weld_link_names["robot"])
            bowl_link = selected_bowl.get_link(weld_link_names["bowl"])
            weld_link_indices = {
                "robot": int(suction_link.idx),
                "bowl": int(bowl_link.idx),
            }
            scene.rigid_solver.add_weld_constraint(
                weld_link_indices["robot"],
                weld_link_indices["bowl"],
            )
            weld_active = True
            weld_registered_after_add = weld_pair_registered(
                weld_link_indices["robot"],
                weld_link_indices["bowl"],
            )
            if not weld_registered_after_add:
                raise RuntimeError("Genesis did not register the requested suction weld")
        bowl_z_before_lift = float(_vector(selected_bowl.get_pos())[2])
        if not args.single_bowl_slide:
            command_segment(
                "lift",
                qpos_by_stage["lift"],
                float(contract["lift_duration_s"]),
            )

        bowl_position_after_lift = _vector(selected_bowl.get_pos())
        lift_reference_z = bowl_z_before_lift if is_rim_hook else bowl_z_before_approach
        lift_delta = float(bowl_position_after_lift[2]) - lift_reference_z
        stability_rows: list[dict[str, object]] = []
        bowl_position_after_place: list[float] | None = None
        if args.single_bowl_place:
            if args.smooth_transport_profile:
                command_smooth_path(
                    "transport",
                    transport_qpos_path,
                    float(contract["transport_duration_s"]),
                )
                command_smooth_path(
                    "place",
                    place_qpos_path,
                    float(contract["place_duration_s"]),
                )
            else:
                for target in transport_qpos_path:
                    command_segment(
                        "transport",
                        target,
                        float(contract["transport_duration_s"])
                        / len(transport_qpos_path),
                    )
                for target in place_qpos_path:
                    command_segment(
                        "place",
                        target,
                        float(contract["place_duration_s"]) / len(place_qpos_path),
                    )
            if args.contact_weld_transport:
                assert weld_link_indices is not None
                scene.rigid_solver.delete_weld_constraint(
                    weld_link_indices["robot"],
                    weld_link_indices["bowl"],
                )
                weld_active = False
                weld_removed_before_release = not weld_pair_registered(
                    weld_link_indices["robot"],
                    weld_link_indices["bowl"],
                )
                if not weld_removed_before_release:
                    raise RuntimeError("Genesis suction weld remained active before release")
            release_target = qpos_by_stage["place"].copy()
            for index in all_gripper_indices:
                release_target[index] = open_qpos[index]
            command_segment(
                "release",
                release_target,
                float(contract["release_duration_s"]),
            )
            command_segment(
                "retreat",
                qpos_by_stage["retreat"],
                float(contract["retreat_duration_s"]),
            )

            policy_hz = float(task["policy_hz"])
            required_stability_frames = int(contract["stability_policy_frames"])
            previous_step = 0
            previous_position = np.asarray(_vector(selected_bowl.get_pos()), dtype=float)
            previous_quaternion = np.asarray(_vector(selected_bowl.get_quat()), dtype=float)
            for frame in range(required_stability_frames):
                target_step = int(math.ceil((frame + 1) / (policy_hz * dt)))
                for _ in range(previous_step, target_step):
                    robot.control_dofs_position(
                        qpos_by_stage["retreat"], dofs_idx_local=all_indices
                    )
                    scene.step()
                sample_contacts("stabilize")
                position = np.asarray(_vector(selected_bowl.get_pos()), dtype=float)
                quaternion = np.asarray(_vector(selected_bowl.get_quat()), dtype=float)
                elapsed = (target_step - previous_step) * dt
                linear_speed = float(np.linalg.norm(position - previous_position) / elapsed)
                q0 = previous_quaternion / np.linalg.norm(previous_quaternion)
                q1 = quaternion / np.linalg.norm(quaternion)
                angular_distance = 2.0 * math.acos(
                    min(1.0, max(0.0, abs(float(np.dot(q0, q1)))))
                )
                angular_speed = angular_distance / elapsed
                frame_stable = (
                    linear_speed
                    < float(task["success_predicate"]["maximum_linear_speed_m_s"])
                    and angular_speed
                    < float(task["success_predicate"]["maximum_angular_speed_rad_s"])
                )
                stability_rows.append(
                    {
                        "frame": frame + 1,
                        "linear_speed_m_s": linear_speed,
                        "angular_speed_rad_s": angular_speed,
                        "stable": frame_stable,
                    }
                )
                previous_step = target_step
                previous_position = position
                previous_quaternion = quaternion
            actual = _vector(robot.get_qpos())
            final_arm_tracking_error["stabilize"] = _max_error(
                actual, qpos_by_stage["retreat"].tolist(), all_arm_indices
            )
            final_gripper_tracking_error["stabilize"] = _max_error(
                actual, qpos_by_stage["retreat"].tolist(), all_gripper_indices
            )
            bowl_position_by_stage["stabilize"] = _vector(selected_bowl.get_pos())
            tcp_world_position_by_stage["stabilize"] = {
                side: _tcp_world_position(links[side], local_points[side])
                for side in SIDES
            }
            bowl_position_after_place = _vector(selected_bowl.get_pos())
        if args.single_bowl_slide:
            command_segment(
                "slide",
                qpos_by_stage["slide"],
                float(contract["slide_duration_s"]),
            )
            command_segment(
                "retreat",
                qpos_by_stage["retreat"],
                float(contract["slide_retreat_duration_s"]),
            )
            policy_hz = float(task["policy_hz"])
            required_stability_frames = int(contract["slide_stability_policy_frames"])
            previous_step = 0
            previous_position = np.asarray(_vector(selected_bowl.get_pos()), dtype=float)
            previous_quaternion = np.asarray(_vector(selected_bowl.get_quat()), dtype=float)
            for frame in range(required_stability_frames):
                target_step = int(math.ceil((frame + 1) / (policy_hz * dt)))
                for _ in range(previous_step, target_step):
                    robot.control_dofs_position(
                        qpos_by_stage["retreat"], dofs_idx_local=all_indices
                    )
                    scene.step()
                sample_contacts("stabilize")
                position = np.asarray(_vector(selected_bowl.get_pos()), dtype=float)
                quaternion = np.asarray(_vector(selected_bowl.get_quat()), dtype=float)
                elapsed = (target_step - previous_step) * dt
                linear_speed = float(np.linalg.norm(position - previous_position) / elapsed)
                q0 = previous_quaternion / np.linalg.norm(previous_quaternion)
                q1 = quaternion / np.linalg.norm(quaternion)
                angular_distance = 2.0 * math.acos(
                    min(1.0, max(0.0, abs(float(np.dot(q0, q1)))))
                )
                angular_speed = angular_distance / elapsed
                frame_stable = (
                    linear_speed
                    < float(task["success_predicate"]["maximum_linear_speed_m_s"])
                    and angular_speed
                    < float(task["success_predicate"]["maximum_angular_speed_rad_s"])
                )
                stability_rows.append(
                    {
                        "frame": frame + 1,
                        "linear_speed_m_s": linear_speed,
                        "angular_speed_rad_s": angular_speed,
                        "stable": frame_stable,
                    }
                )
                previous_step = target_step
                previous_position = position
                previous_quaternion = quaternion
            actual = _vector(robot.get_qpos())
            final_arm_tracking_error["stabilize"] = _max_error(
                actual, qpos_by_stage["retreat"].tolist(), all_arm_indices
            )
            final_gripper_tracking_error["stabilize"] = _max_error(
                actual, qpos_by_stage["retreat"].tolist(), all_gripper_indices
            )
            bowl_position_by_stage["stabilize"] = _vector(selected_bowl.get_pos())
            tcp_world_position_by_stage["stabilize"] = {
                side: _tcp_world_position(links[side], local_points[side])
                for side in SIDES
            }
            bowl_position_after_place = _vector(selected_bowl.get_pos())
        navigation_stages = (
            "left_separate_high",
            "left_rotate_high",
            "right_rotate_high",
            "side_clearance",
            "pregrasp",
        )
        selected_navigation_contact_failure_stage = next(
            (
                stage
                for stage in navigation_stages
                if max(contact_counts[stage], default=0) > 0
            ),
            None,
        )

        def first_nonzero_stage(values: dict[str, list[int]]) -> str | None:
            return next(
                (stage for stage in active_stages if max(values[stage], default=0) > 0),
                None,
            )

        table_contact_failure_stage = first_nonzero_stage(table_contact_counts)
        other_bowl_contact_failure_stage = first_nonzero_stage(other_bowl_contact_counts)
        self_contact_failure_stage = first_nonzero_stage(self_contact_counts)
        selected_label = f"{selected_pose.name}:"

        def finger_contact(side: str, stage: str) -> bool:
            required_link = f"mantis:{side}_{contract['required_contact_link_substring']}"
            return any(
                required_link in pair and selected_label in pair
                for pair in contact_pair_rows_by_stage[stage]
            )

        contact_sides_by_stage = {
            stage: {side: finger_contact(side, stage) for side in SIDES}
            for stage in active_stages
        }
        contact_stages = ("close", "hold") if is_rim_hook else ("approach", "hold")
        opposed_contact_observed = any(
            all(contact_sides_by_stage[stage].values()) for stage in contact_stages
        )
        opposed_contact_held = all(contact_sides_by_stage["hold"].values())
        opposed_contact_during_lift = (
            True
            if args.single_bowl_slide
            else all(contact_sides_by_stage["lift"].values())
        )
        contacted_finger_links_by_stage = {
            stage: {
                side: sorted(
                    {
                        label
                        for pair in contact_pair_rows_by_stage[stage]
                        for label in pair.split(" <> ")
                        if label.startswith(f"mantis:{side}_clamp")
                        and selected_label in pair
                    }
                )
                for side in SIDES
            }
            for stage in active_stages
        }
        minimum_contacted_fingers = int(
            contract.get("minimum_contacted_fingers_per_arm", 1)
        )
        required_finger_contacts_held = all(
            len(contacted_finger_links_by_stage["hold"][side])
            >= minimum_contacted_fingers
            for side in SIDES
        )
        required_finger_contacts_during_lift = args.single_bowl_slide or all(
            len(contacted_finger_links_by_stage["lift"][side])
            >= minimum_contacted_fingers
            for side in SIDES
        )
        selected_contact_check_stages = (
            ("approach", "close", "hold", "lift", "transport", "place", "release", "retreat", "stabilize")
            if args.single_bowl_place
            else (
                ("approach", "hold", "slide", "retreat", "stabilize")
                if args.single_bowl_slide
                else (("approach", "close", "hold", "lift") if is_rim_hook else ("approach", "hold", "lift"))
            )
        )
        unexpected_bowl_contact_failure_stage = next(
            (
                stage
                for stage in selected_contact_check_stages
                if any(
                    selected_label in pair
                    and "mantis:" in pair
                    and "_clamp" not in pair
                    for pair in contact_pair_rows_by_stage[stage]
                )
            ),
            None,
        )
        lift_pass = args.single_bowl_slide or (
            lift_delta >= float(contract["minimum_lift_delta_m"])
        )
        tracking_failure_stage = next(
            (
                stage
                for stage in active_stages
                if final_arm_tracking_error.get(stage, math.inf)
                > float(contract["maximum_arm_tracking_error_rad"])
            ),
            None,
        )
        gripper_tracking_stages = navigation_stages + (
            ("approach", "retreat", "stabilize")
            if args.single_bowl_place
            else (
                ("approach", "hold", "slide", "retreat", "stabilize")
                if args.single_bowl_slide
                else (("approach",) if is_rim_hook else ("approach", "hold", "lift"))
            )
        )
        gripper_tracking_pass = max(
            (final_gripper_tracking_error[stage] for stage in gripper_tracking_stages),
            default=math.inf,
        ) <= float(contract["maximum_gripper_tracking_error_m"])
        finite_values = bowl_position_after_lift + [bowl_z_before_approach, lift_delta]
        if bowl_position_after_place is not None:
            finite_values.extend(bowl_position_after_place)
        finite = all(
            math.isfinite(value)
            for value in finite_values
        )
        suction_transport_pass = (
            not args.contact_weld_transport
            or (
                weld_activation_contact_pass
                and weld_registered_after_add
                and weld_removed_before_release
                and not weld_active
            )
        )
        transport_contact_pass = not args.single_bowl_place or (
            suction_transport_pass
            if args.contact_weld_transport
            else all(
                all(contact_sides_by_stage[stage].values())
                for stage in ("transport", "place")
            )
        )
        lift_transport_evidence_pass = (
            lift_pass
            and (
                suction_transport_pass
                if args.contact_weld_transport
                else (
                    opposed_contact_during_lift
                    and required_finger_contacts_during_lift
                )
            )
        )
        slide_contact_pass = not args.single_bowl_slide or all(
            contact_sides_by_stage["slide"].values()
        )
        release_open_pass = not args.single_bowl_place or (
            max(
                final_gripper_tracking_error[stage]
                for stage in ("retreat", "stabilize")
            )
            <= float(contract["maximum_gripper_tracking_error_m"])
        )
        target_place_pass = False
        stability_pass = False
        if bowl_position_after_place is not None:
            target_field = (
                "slide_target_xy_m"
                if args.single_bowl_slide
                else "transport_target_xy_m"
            )
            place_x, place_y = (float(value) for value in contract[target_field])
            target_place_pass = (
                abs(float(bowl_position_after_place[0]) - place_x)
                < float(task["success_predicate"]["xy_axis_alignment_tolerance_m"])
                and abs(float(bowl_position_after_place[1]) - place_y)
                < float(task["success_predicate"]["xy_axis_alignment_tolerance_m"])
                and (
                    args.single_bowl_slide
                    or abs(
                        float(bowl_position_after_place[2])
                        - float(task["success_predicate"]["target_heights_m"][0])
                    )
                    < float(task["success_predicate"]["height_absolute_tolerance_m"])
                )
            )
            stability_frame_field = (
                "slide_stability_policy_frames"
                if args.single_bowl_slide
                else "stability_policy_frames"
            )
            stability_pass = (
                len(stability_rows) == int(contract[stability_frame_field])
                and all(bool(row["stable"]) for row in stability_rows)
            )
        selected_bowl_force_summary_by_stage = _summarize_selected_bowl_force_samples(
            selected_bowl_force_samples_by_stage,
            nominal_bowl_weight_n,
        )
        if table_contact_failure_stage is not None:
            failure_stage = f"safety_table_{table_contact_failure_stage}"
        elif other_bowl_contact_failure_stage is not None:
            failure_stage = f"safety_other_bowl_{other_bowl_contact_failure_stage}"
        elif self_contact_failure_stage is not None:
            failure_stage = f"safety_self_{self_contact_failure_stage}"
        elif unexpected_bowl_contact_failure_stage is not None:
            failure_stage = f"safety_non_clamp_bowl_{unexpected_bowl_contact_failure_stage}"
        elif tracking_failure_stage is not None:
            failure_stage = tracking_failure_stage
        elif selected_navigation_contact_failure_stage is not None:
            failure_stage = selected_navigation_contact_failure_stage
        elif not opposed_contact_observed:
            failure_stage = "contact"
        elif not gripper_tracking_pass or not opposed_contact_held or not required_finger_contacts_held:
            failure_stage = "grasp"
        elif not args.single_bowl_slide and not lift_transport_evidence_pass:
            failure_stage = "transport"
        elif args.single_bowl_slide and not slide_contact_pass:
            failure_stage = "slide"
        elif args.single_bowl_slide and not target_place_pass:
            failure_stage = "slide"
        elif args.single_bowl_slide and not stability_pass:
            failure_stage = "stabilize"
        elif args.single_bowl_place and not transport_contact_pass:
            failure_stage = "transport"
        elif args.single_bowl_place and not target_place_pass:
            failure_stage = "place"
        elif args.single_bowl_place and not release_open_pass:
            failure_stage = "release"
        elif args.single_bowl_place and not stability_pass:
            failure_stage = "stabilize"
        elif not finite:
            failure_stage = "physics_divergence"
        else:
            failure_stage = None
        probe_pass = failure_stage is None

        receipt = {
            "schema_version": 1,
            "protocol_version": active_protocol_version,
            "probe_contract": args.probe_contract,
            "candidate_override": candidate_override or transport_candidate_override,
            "lift_candidate_override": candidate_override,
            "transport_candidate_override": transport_candidate_override,
            "transport_duration_candidate_override": transport_duration_override,
            "transport_half_span_candidate_override": transport_half_span_override,
            "transport_tcp_z_candidate_override": transport_tcp_z_override,
            "smooth_transport_profile": args.smooth_transport_profile,
            "right_tcp_z_offset_candidate_override": right_tcp_z_offset_override,
            "right_tcp_z_offset_m": right_tcp_z_offset_m,
            "contact_weld_transport": args.contact_weld_transport,
            "weld_activation_contact_pass": weld_activation_contact_pass,
            "weld_registered_after_add": weld_registered_after_add,
            "weld_removed_before_release": weld_removed_before_release,
            "weld_active_at_receipt": weld_active,
            "weld_link_names": weld_link_names,
            "weld_link_indices": weld_link_indices,
            "cartesian_transport_waypoints": args.cartesian_transport_waypoints,
            "transport_duration_s": float(contract["transport_duration_s"]),
            "transport_half_span_m": float(
                contract.get("transport_half_span_m", contract["lift_half_span_m"])
            ),
            "transport_tcp_z_m": float(contract["transport_tcp_z_m"]),
            "single_bowl_place_requested": args.single_bowl_place,
            "single_bowl_slide_requested": args.single_bowl_slide,
            "lift_command_distance_m": float(contract["lift_distance_m"]),
            "lift_command_duration_s": float(contract["lift_duration_s"]),
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
            "reset_position_xyz_m": list(selected_pose.position_xyz_m),
            "grasp_mode": contract["grasp_mode"],
            "gripper_hold_open_fraction": float(
                contract.get("gripper_hold_open_fraction", 0.0)
            ),
            "lift_gripper_open_fraction": float(
                contract.get(
                    "lift_gripper_open_fraction",
                    contract.get("gripper_hold_open_fraction", 0.0),
                )
            ),
            "target_tcp_positions_by_stage_m": {
                stage: {side: value.tolist() for side, value in positions.items()}
                for stage, positions in target_positions.items()
            },
            "orientations_wxyz": {
                side: orientations[side].tolist() for side in SIDES
            },
            "separation_orientations_wxyz": contract["separation_orientations_wxyz"],
            "geometry_derivation": contract["geometry_derivation"],
            "ik_errors_by_stage": ik_errors,
            "bowl_z_before_approach_m": bowl_z_before_approach,
            "bowl_z_before_lift_m": bowl_z_before_lift,
            "lift_reference_z_m": lift_reference_z,
            "bowl_position_after_lift_m": bowl_position_after_lift,
            "bowl_position_after_place_m": bowl_position_after_place,
            "lift_delta_m": lift_delta,
            "minimum_lift_delta_m": contract["minimum_lift_delta_m"],
            "contact_counts": contact_counts,
            "contact_pair_rows_by_stage": contact_pair_rows_by_stage,
            "selected_bowl_force_samples_by_stage": selected_bowl_force_samples_by_stage,
            "selected_bowl_force_summary_by_stage": selected_bowl_force_summary_by_stage,
            "bowl_mass_kg": bowl_mass_kg,
            "nominal_bowl_weight_n": nominal_bowl_weight_n,
            "contact_sides_by_stage": contact_sides_by_stage,
            "contacted_finger_links_by_stage": contacted_finger_links_by_stage,
            "minimum_contacted_fingers_per_arm": minimum_contacted_fingers,
            "required_finger_contacts_held": required_finger_contacts_held,
            "required_finger_contacts_during_lift": required_finger_contacts_during_lift,
            "transport_contact_pass": transport_contact_pass,
            "lift_transport_evidence_pass": lift_transport_evidence_pass,
            "slide_contact_pass": slide_contact_pass,
            "target_place_pass": target_place_pass,
            "release_open_pass": release_open_pass,
            "stability_pass": stability_pass,
            "stability_policy_rows": stability_rows,
            "opposed_contact_observed": opposed_contact_observed,
            "opposed_contact_held": opposed_contact_held,
            "opposed_contact_during_lift": opposed_contact_during_lift,
            "unexpected_bowl_contact_failure_stage": unexpected_bowl_contact_failure_stage,
            "selected_navigation_contact_failure_stage": selected_navigation_contact_failure_stage,
            "table_contact_counts": table_contact_counts,
            "table_contact_pair_rows_by_stage": table_contact_pair_rows_by_stage,
            "table_contact_failure_stage": table_contact_failure_stage,
            "other_bowl_contact_counts": other_bowl_contact_counts,
            "other_bowl_contact_pair_rows_by_stage": other_bowl_contact_pair_rows_by_stage,
            "other_bowl_contact_failure_stage": other_bowl_contact_failure_stage,
            "self_contact_counts": self_contact_counts,
            "self_contact_pair_rows_by_stage": self_contact_pair_rows_by_stage,
            "self_contact_failure_stage": self_contact_failure_stage,
            "bowl_position_by_stage_m": bowl_position_by_stage,
            "tcp_world_position_by_stage_m": tcp_world_position_by_stage,
            "final_arm_tracking_error_rad_by_stage": final_arm_tracking_error,
            "final_gripper_tracking_error_m_by_stage": final_gripper_tracking_error,
            "tracking_pass": tracking_failure_stage is None,
            "gripper_tracking_pass": gripper_tracking_pass,
            "friction": {
                "bowl_coefficient": contract["bowl_friction_coefficient"],
                "finger_coefficient": contract["finger_friction_coefficient"],
                "finger_geoms": sorted(finger_geom_labels),
                "semantics": contract["friction_semantics"],
            },
            "finite": finite,
            "scene_contract_sha256": sha256_file(args.scene_contract),
            "port_config_sha256": sha256_file(args.port),
            "mantis_urdf_sha256": sha256_file(args.mantis_urdf),
            "bowl_urdf_sha256": sha256_file(bowl_urdf),
            "bowl_manifest_sha256": sha256_file(bowl_manifest_path),
            "evidence_boundary": contract["claim_boundary"],
        }
        receipt_path = run_dir / "receipt.json"
        receipt_path.write_text(
            json.dumps(receipt, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
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
