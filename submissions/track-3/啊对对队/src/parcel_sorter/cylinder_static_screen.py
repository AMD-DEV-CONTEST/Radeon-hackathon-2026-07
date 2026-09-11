from __future__ import annotations

from dataclasses import asdict
import json
import math
import time
from typing import Any, Mapping, Sequence

from .cylinder_grasp_planning import plan_cylinder_grasp_candidates
from .grasp_planning import (
    grasp_evaluation_is_feasible,
    rank_grasp_pose_evaluations,
)


def screen_episode_keys(
    protocol: Mapping[str, Any],
) -> tuple[tuple[str, int], ...]:
    population = protocol["population"]
    profile_ids = tuple(str(value) for value in population["profile_ids"])
    episode_starts = {
        str(key): int(value)
        for key, value in population["episode_starts"].items()
    }
    offsets = tuple(int(value) for value in population["episode_offsets"])
    if len(set(profile_ids)) != len(profile_ids):
        raise ValueError("static-screen profile IDs must be unique")
    if set(episode_starts) != set(profile_ids):
        raise ValueError("every static-screen profile requires one episode start")
    if not offsets or len(set(offsets)) != len(offsets) or any(value < 0 for value in offsets):
        raise ValueError("static-screen episode offsets must be unique and non-negative")
    keys = tuple(
        (profile_id, episode_starts[profile_id] + offset)
        for profile_id in profile_ids
        for offset in offsets
    )
    if len(keys) != int(population["expected_samples"]):
        raise ValueError("static-screen expected sample count does not match selection")
    return keys


def screen_cylinder_environment(
    env: Any,
    protocol: Mapping[str, Any],
) -> dict[str, Any]:
    """Run static IK/FK/collision evaluation without stepping the environment."""
    planner = protocol["planner"]
    state = env.state()
    hand_clearance_m = float(env.expert.grasp_hand_clearance_m())
    jaw_aperture_m = 2.0 * float(env.config.control.open_width_m)
    started = time.perf_counter_ns()
    plan = plan_cylinder_grasp_candidates(
        env.sample,
        state.parcel_pose,
        hand_clearance_m=hand_clearance_m,
        jaw_aperture_m=jaw_aperture_m,
        min_aperture_margin_m=float(planner["min_aperture_margin_m"]),
        min_horizontal_rolling_friction=float(
            planner["min_horizontal_rolling_friction"]
        ),
        max_parallel_jaw_length_m=float(planner["max_parallel_jaw_length_m"]),
        max_axis_tilt_deg=float(planner["max_axis_tilt_deg"]),
        include_symmetric_wrist=bool(planner["include_symmetric_wrist"]),
        upright_radial_yaw_count=int(planner["upright_radial_yaw_count"]),
        max_upright_vertical_offset_m=float(
            planner["max_upright_vertical_offset_m"]
        ),
        min_upright_side_overlap_m=float(
            planner["min_upright_side_overlap_m"]
        ),
        max_horizontal_axial_offset_m=float(
            planner["max_horizontal_axial_offset_m"]
        ),
        min_horizontal_end_margin_m=float(
            planner["min_horizontal_end_margin_m"]
        ),
        horizontal_radial_angles_deg=tuple(
            float(value) for value in planner["horizontal_radial_angles_deg"]
        ),
    )
    if not plan.capability.supported or not plan.candidates:
        raise RuntimeError(
            "static cylinder screen requires a supported non-empty candidate plan: "
            f"{plan.capability.reason}"
        )
    seeds = env._grasp_planning_seeds()
    if not seeds:
        raise RuntimeError("static cylinder screen requires at least one IK seed")
    evaluations = [
        env._evaluate_grasp_pose_candidate(candidate, seed_name, seed_qpos)
        for candidate in plan.candidates
        for seed_name, seed_qpos in seeds
    ]
    ranked = rank_grasp_pose_evaluations(evaluations)
    feasible = [row for row in ranked if grasp_evaluation_is_feasible(row)]
    feasible_candidate_ids = tuple(
        dict.fromkeys(str(row["candidate_id"]) for row in feasible)
    )
    compute_ms = (time.perf_counter_ns() - started) / 1_000_000
    finite = all(bool(row["finite"]) for row in evaluations)
    maximum_restore_error = max(
        (float(row["restore_max_abs_error"]) for row in evaluations),
        default=math.inf,
    )
    return {
        "schema_version": "1.0",
        "status": "complete",
        "profile_id": env.sample.profile_id,
        "episode": env.sample.episode_index,
        "sample": asdict(env.sample),
        "initial_parcel_pose": list(state.parcel_pose),
        "hand_clearance_m": hand_clearance_m,
        "jaw_aperture_m": jaw_aperture_m,
        "capability": asdict(plan.capability),
        "candidate_count": len(plan.candidates),
        "seed_count": len(seeds),
        "evaluation_count": len(evaluations),
        "feasible_evaluation_count": len(feasible),
        "feasible_candidate_count": len(feasible_candidate_ids),
        "feasible_candidate_ids": list(feasible_candidate_ids),
        "all_evaluations_finite": finite,
        "maximum_restore_error": maximum_restore_error,
        "screen_compute_ms": compute_ms,
        "selected_static": _compact_evaluation(feasible[0]) if feasible else None,
        "evaluations": [_compact_evaluation(row) for row in ranked],
        "contract": {
            "physics_stepped": False,
            "robot_action_executed": False,
            "task_outcome_read": False,
            "ik_fk_evaluated": True,
            "mesh_collision_evaluated": True,
            "robot_state_restored_after_each_evaluation": True,
        },
    }


def summarize_static_screen(
    samples: Sequence[Mapping[str, Any]],
    protocol: Mapping[str, Any],
) -> dict[str, Any]:
    expected_keys = set(screen_episode_keys(protocol))
    observed_keys = {
        (str(row["profile_id"]), int(row["episode"])) for row in samples
    }
    errors = []
    if observed_keys != expected_keys or len(samples) != len(expected_keys):
        errors.append("sample_population_incomplete")
    if any(str(row.get("status")) != "complete" for row in samples):
        errors.append("sample_not_complete")

    gates = protocol["gates"]
    max_restore_error = float(gates["max_restore_error"])
    if any(not bool(row["all_evaluations_finite"]) for row in samples):
        errors.append("nonfinite_evaluation")
    if any(float(row["maximum_restore_error"]) > max_restore_error for row in samples):
        errors.append("state_restore_error")

    expected_backend = str(protocol.get("execution", {}).get("backend", ""))
    device_rows = [row.get("device") for row in samples]
    if expected_backend:
        if any(not isinstance(row, Mapping) for row in device_rows):
            errors.append("device_metadata_missing")
        else:
            canonical_devices = {
                json.dumps(row, sort_keys=True, separators=(",", ":"))
                for row in device_rows
            }
            if len(canonical_devices) != 1:
                errors.append("device_metadata_mismatch")
            if any(str(row.get("backend")) != expected_backend for row in device_rows):
                errors.append("execution_backend_mismatch")
            if bool(protocol["execution"].get("require_hip")) and any(
                not str(row.get("torch_hip_version", "")) for row in device_rows
            ):
                errors.append("hip_metadata_missing")
            if bool(protocol["execution"].get("require_single_visible_device")) and any(
                int(row.get("visible_device_count", 0)) != 1 for row in device_rows
            ):
                errors.append("visible_device_count")

    profile_summaries = {}
    for profile_id in protocol["population"]["profile_ids"]:
        rows = tuple(row for row in samples if row["profile_id"] == profile_id)
        feasible_samples = sum(int(row["feasible_candidate_count"]) > 0 for row in rows)
        fraction = feasible_samples / len(rows) if rows else 0.0
        profile_summaries[str(profile_id)] = {
            "sample_count": len(rows),
            "feasible_sample_count": feasible_samples,
            "feasible_sample_fraction": fraction,
            "feasible_candidate_count_min": min(
                (int(row["feasible_candidate_count"]) for row in rows),
                default=0,
            ),
            "feasible_candidate_count_median": _median(
                tuple(int(row["feasible_candidate_count"]) for row in rows)
            ),
            "screen_compute_p50_ms": _percentile(
                tuple(float(row["screen_compute_ms"]) for row in rows),
                0.50,
            ),
            "screen_compute_p95_ms": _percentile(
                tuple(float(row["screen_compute_ms"]) for row in rows),
                0.95,
            ),
            "scene_build_p50_ms": _percentile(
                tuple(float(row["scene_build_ms"]) for row in rows),
                0.50,
            ),
            "scene_build_p95_ms": _percentile(
                tuple(float(row["scene_build_ms"]) for row in rows),
                0.95,
            ),
        }
        if fraction < float(gates["min_feasible_sample_fraction_per_profile"]):
            errors.append(f"profile_feasible_fraction:{profile_id}")

    aggregate_p95_ms = _percentile(
        tuple(float(row["screen_compute_ms"]) for row in samples),
        0.95,
    )
    if aggregate_p95_ms > float(gates["max_screen_compute_p95_ms"]):
        errors.append("screen_compute_latency")
    return {
        "schema_version": "1.0",
        "status": "screen_pass" if not errors else "screen_fail",
        "expected_samples": len(expected_keys),
        "observed_samples": len(samples),
        "profile_summaries": profile_summaries,
        "screen_compute_p95_ms": aggregate_p95_ms,
        "maximum_restore_error": max(
            (float(row["maximum_restore_error"]) for row in samples),
            default=math.inf,
        ),
        "contract": {
            "physics_stepped": False,
            "robot_action_executed": False,
            "task_outcome_read": False,
        },
        "device": device_rows[0] if device_rows else None,
        "errors": list(dict.fromkeys(errors)),
    }


def _compact_evaluation(evaluation: Mapping[str, Any]) -> dict[str, Any]:
    keys = (
        "candidate_id",
        "seed_name",
        "target_position",
        "target_quaternion",
        "longitudinal_offset_m",
        "vertical_offset_m",
        "wrist_variant",
        "approach_variant",
        "radial_approach_angle_rad",
        "rolling_risk_score",
        "finite",
        "feasible",
        "ik_position_error_m",
        "ik_rotation_error_rad",
        "fk_position_error_m",
        "joint_distance_rad",
        "minimum_singular_value",
        "nonfinger_clearance_m",
        "collision_count",
        "disallowed_collision_count",
        "restore_max_abs_error",
        "compute_ms",
    )
    return {key: evaluation.get(key) for key in keys}


def _median(values: Sequence[int]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[middle])
    return (ordered[middle - 1] + ordered[middle]) / 2


def _percentile(values: Sequence[float], quantile: float) -> float:
    if not values:
        return math.inf
    if not 0 <= quantile <= 1:
        raise ValueError("quantile must be in [0, 1]")
    ordered = sorted(float(value) for value in values)
    rank = max(0, math.ceil(quantile * len(ordered)) - 1)
    return ordered[rank]
