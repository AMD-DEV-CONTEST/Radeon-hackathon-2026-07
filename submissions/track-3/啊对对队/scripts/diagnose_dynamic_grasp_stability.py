#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import asdict, replace
import json
import math
from pathlib import Path
import sys
import time
from typing import Any, Mapping


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from parcel_sorter.config import load_config
from parcel_sorter.genesis_env import GenesisParcelEnv
from parcel_sorter.grasp_planning import (
    generate_box_grasp_pose_candidates,
    grasp_evaluation_is_feasible,
    rank_grasp_pose_evaluations,
)
from parcel_sorter.grasp_stability import (
    DynamicGraspThresholds,
    dynamic_grasp_is_stable,
    linear_segment_waypoints,
    rank_dynamic_grasp_evaluations,
)
from parcel_sorter.randomization import DomainRandomizer


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run isolated loaded-physics probes for statically feasible grasp "
            "candidates. This diagnostic does not alter the task controller."
        )
    )
    parser.add_argument("--config", type=Path, default=PROJECT_ROOT / "configs/catalog_v2.toml")
    parser.add_argument("--profile", required=True)
    parser.add_argument("--episode", type=int, required=True)
    parser.add_argument("--backend", choices=("cpu", "rocm"), default="rocm")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-candidates", type=int, default=6)
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--close-steps", type=int, default=24)
    parser.add_argument("--lift-steps", type=int, default=12)
    parser.add_argument("--settle-steps", type=int, default=5)
    parser.add_argument("--transfer-steps", type=int, default=8)
    parser.add_argument("--lift-m", type=float, default=0.030)
    parser.add_argument("--transfer-m", type=float, default=0.030)
    parser.add_argument(
        "--horizon",
        choices=("short", "pre-release"),
        default="short",
        help="short diagnostic or full raise-transfer-descend path before release",
    )
    parser.add_argument("--full-raise-step-m", type=float, default=0.020)
    parser.add_argument("--full-transfer-step-m", type=float, default=0.010)
    parser.add_argument("--full-descent-step-m", type=float, default=0.005)
    return parser.parse_args()


def _flat_tuple(value: Any) -> tuple[float, ...]:
    if hasattr(value, "detach"):
        value = value.detach().cpu()
    if hasattr(value, "reshape"):
        value = value.reshape(-1)
    if hasattr(value, "tolist"):
        value = value.tolist()
    return tuple(float(item) for item in value)


def _state_vector(env: GenesisParcelEnv) -> tuple[float, ...]:
    return (
        *_flat_tuple(env.robot.get_qpos()),
        *_flat_tuple(env.robot.get_dofs_velocity()),
        *_flat_tuple(env.parcel.get_pos()),
        *_flat_tuple(env.parcel.get_quat()),
        *_flat_tuple(env.parcel.get_vel()),
        *_flat_tuple(env.parcel.get_ang()),
    )


def _max_abs_error(values: tuple[float, ...], reference: tuple[float, ...]) -> float:
    if len(values) != len(reference):
        raise RuntimeError("scene state vectors have different sizes")
    return max(
        abs(value - expected)
        for value, expected in zip(values, reference, strict=True)
    )


def _step_control(
    env: GenesisParcelEnv,
    arm_target: tuple[float, ...],
    force_n: float,
) -> None:
    env.robot.control_dofs_position(env.np.asarray(arm_target), env.arm_dofs)
    env.robot.control_dofs_force(
        env.np.asarray((-force_n, -force_n)),
        env.finger_dofs,
    )
    physics_steps = env.config.simulation.physics_hz // env.config.simulation.control_hz
    for _ in range(physics_steps):
        env.scene.step()


def _interpolate(
    start: tuple[float, ...],
    target: tuple[float, ...],
    step: int,
    total_steps: int,
) -> tuple[float, ...]:
    fraction = step / total_steps
    return tuple(
        current + (goal - current) * fraction
        for current, goal in zip(start, target, strict=True)
    )


def _solve_arm_target(
    env: GenesisParcelEnv,
    position: tuple[float, float, float],
    quaternion: tuple[float, float, float, float],
    seed_qpos: tuple[float, ...],
) -> tuple[tuple[float, ...] | None, tuple[float, ...]]:
    qpos, error = env.robot.inverse_kinematics(
        link=env.end_effector,
        pos=env.np.asarray(position),
        quat=env.np.asarray(quaternion),
        init_qpos=env.np.asarray(seed_qpos),
        respect_joint_limit=True,
        max_samples=8,
        max_solver_iters=40,
        return_error=True,
    )
    qpos_values = _flat_tuple(qpos)
    error_values = _flat_tuple(error)
    valid = (
        all(math.isfinite(value) for value in (*qpos_values, *error_values))
        and math.sqrt(sum(value * value for value in error_values[:3])) <= 0.005
        and math.sqrt(sum(value * value for value in error_values[3:])) <= 0.05
    )
    return (qpos_values[:7] if valid else None), error_values


def _record_sample(
    env: GenesisParcelEnv,
    trace: list[dict[str, Any]],
    phase: str,
    target_position_m: tuple[float, float, float] | None = None,
) -> None:
    state = env.state()
    dual_contact, force_n = env._finger_contact()
    relative = tuple(
        float(ee - parcel)
        for ee, parcel in zip(
            state.end_effector_pose[:3],
            state.parcel_pose[:3],
            strict=True,
        )
    )
    row = {
            "sample": len(trace),
            "phase": phase,
            "dual_contact": dual_contact,
            "contact_force_n": force_n,
            "ee_position_m": state.end_effector_pose[:3],
            "parcel_position_m": state.parcel_pose[:3],
            "relative_position_m": relative,
        }
    if target_position_m is not None:
        row["target_position_m"] = target_position_m
    trace.append(row)


def _rollout_short_candidate(
    env: GenesisParcelEnv,
    evaluation: Mapping[str, Any],
    args: argparse.Namespace,
    thresholds: DynamicGraspThresholds,
    initial_parcel_z_m: float,
) -> dict[str, Any]:
    qpos = tuple(float(value) for value in evaluation["qpos"])
    arm_grasp = qpos[:7]
    open_qpos = (*arm_grasp, env.config.control.open_width_m, env.config.control.open_width_m)
    env.robot.set_qpos(env.np.asarray(open_qpos))
    env.robot.control_dofs_position(env.np.asarray(arm_grasp), env.arm_dofs)
    env.robot.control_dofs_position(
        env.np.asarray((env.config.control.open_width_m,) * 2),
        env.finger_dofs,
    )
    for _ in range(env.config.simulation.physics_hz // env.config.simulation.control_hz):
        env.scene.step()

    trace: list[dict[str, Any]] = []
    for step in range(1, args.close_steps + 1):
        force_n = min(
            env.config.control.close_force_n,
            step * env.config.control.close_force_ramp_n_per_step,
        )
        _step_control(env, arm_grasp, force_n)
        _record_sample(env, trace, "close")

    grasp_position = tuple(float(value) for value in evaluation["target_position"])
    grasp_quaternion = tuple(float(value) for value in evaluation["target_quaternion"])
    lift_position = (grasp_position[0], grasp_position[1], grasp_position[2] + args.lift_m)
    arm_lift, lift_error = _solve_arm_target(env, lift_position, grasp_quaternion, qpos)
    target_errors = {"lift_ik_error": lift_error}
    if arm_lift is not None:
        for step in range(1, args.lift_steps + 1):
            _step_control(
                env,
                _interpolate(arm_grasp, arm_lift, step, args.lift_steps),
                env.config.control.close_force_n,
            )
            _record_sample(env, trace, "lift")
        for _ in range(args.settle_steps):
            _step_control(env, arm_lift, env.config.control.close_force_n)
            _record_sample(env, trace, "lift_settle")

    destination = env.expert.destination_position
    dx = destination[0] - lift_position[0]
    dy = destination[1] - lift_position[1]
    horizontal_distance = math.hypot(dx, dy)
    transfer_position = lift_position
    arm_transfer = None
    transfer_error: tuple[float, ...] = ()
    if arm_lift is not None and horizontal_distance > 1e-12:
        transfer_position = (
            lift_position[0] + args.transfer_m * dx / horizontal_distance,
            lift_position[1] + args.transfer_m * dy / horizontal_distance,
            lift_position[2],
        )
        arm_transfer, transfer_error = _solve_arm_target(
            env,
            transfer_position,
            grasp_quaternion,
            (*arm_lift, qpos[7], qpos[8]),
        )
        if arm_transfer is not None:
            for step in range(1, args.transfer_steps + 1):
                _step_control(
                    env,
                    _interpolate(arm_lift, arm_transfer, step, args.transfer_steps),
                    env.config.control.close_force_n,
                )
                _record_sample(env, trace, "transfer")
            for _ in range(args.settle_steps):
                _step_control(env, arm_transfer, env.config.control.close_force_n)
                _record_sample(env, trace, "transfer_settle")
    target_errors["transfer_ik_error"] = transfer_error

    finite = all(
        math.isfinite(value)
        for row in trace
        for key in ("contact_force_n", "ee_position_m", "parcel_position_m", "relative_position_m")
        for value in ((row[key],) if isinstance(row[key], float) else row[key])
    )
    contact_rows = [row for row in trace if row["dual_contact"]]
    captured = any(row["dual_contact"] for row in trace[: args.close_steps])
    loaded_rows = [row for row in trace if row["phase"] != "close"]
    previous_relative = None
    max_relative_step_m = 0.0
    max_downward_step_m = 0.0
    for row in trace:
        relative = tuple(float(value) for value in row["relative_position_m"])
        if previous_relative is not None:
            delta = tuple(
                current - previous
                for current, previous in zip(relative, previous_relative, strict=True)
            )
            max_relative_step_m = max(
                max_relative_step_m,
                math.sqrt(sum(value * value for value in delta)),
            )
            max_downward_step_m = max(max_downward_step_m, delta[2])
        previous_relative = relative
    contact_reference = (
        tuple(float(value) for value in contact_rows[0]["relative_position_m"])
        if contact_rows
        else None
    )
    final_relative = (
        tuple(float(value) for value in trace[-1]["relative_position_m"])
        if trace
        else None
    )
    final_relative_drift_m = (
        math.dist(contact_reference, final_relative)
        if contact_reference is not None and final_relative is not None
        else 1_000_000.0
    )
    peak_force_n = max((float(row["contact_force_n"]) for row in trace), default=0.0)
    result = {
        "candidate_id": str(evaluation["candidate_id"]),
        "seed_name": str(evaluation["seed_name"]),
        "static_rank": int(evaluation["static_rank"]),
        "captured": captured,
        "final_dual_contact": bool(trace and trace[-1]["dual_contact"]),
        "finite": finite,
        "safety_aborted": peak_force_n > thresholds.max_contact_force_n,
        "parcel_lift_m": max(
            (float(row["parcel_position_m"][2]) - initial_parcel_z_m for row in trace),
            default=0.0,
        ),
        "max_relative_step_m": max_relative_step_m,
        "max_downward_step_m": max_downward_step_m,
        "final_relative_drift_m": final_relative_drift_m,
        "peak_contact_force_n": peak_force_n,
        "dual_contact_fraction": (
            sum(bool(row["dual_contact"]) for row in loaded_rows) / len(loaded_rows)
            if loaded_rows
            else 0.0
        ),
        "loaded_sample_count": len(loaded_rows),
        "targets": {
            "grasp_position_m": grasp_position,
            "lift_position_m": lift_position,
            "transfer_position_m": transfer_position,
            **target_errors,
        },
        "trace": trace,
    }
    result["stable"] = dynamic_grasp_is_stable(result, thresholds)
    return result


def _phase_metrics(trace: list[dict[str, Any]]) -> dict[str, dict[str, float | int]]:
    phases = sorted({str(row["phase"]) for row in trace})
    return {
        phase: {
            "sample_count": sum(row["phase"] == phase for row in trace),
            "peak_contact_force_n": max(
                float(row["contact_force_n"])
                for row in trace
                if row["phase"] == phase
            ),
        }
        for phase in phases
    }


def _rollout_pre_release_candidate(
    env: GenesisParcelEnv,
    evaluation: Mapping[str, Any],
    args: argparse.Namespace,
    thresholds: DynamicGraspThresholds,
    initial_parcel_z_m: float,
) -> dict[str, Any]:
    """Execute the complete planned path while retaining the parcel."""
    qpos = tuple(float(value) for value in evaluation["qpos"])
    arm_target = qpos[:7]
    open_qpos = (*arm_target, env.config.control.open_width_m, env.config.control.open_width_m)
    env.robot.set_qpos(env.np.asarray(open_qpos))
    env.robot.control_dofs_position(env.np.asarray(arm_target), env.arm_dofs)
    env.robot.control_dofs_position(
        env.np.asarray((env.config.control.open_width_m,) * 2),
        env.finger_dofs,
    )
    for _ in range(env.config.simulation.physics_hz // env.config.simulation.control_hz):
        env.scene.step()

    trace: list[dict[str, Any]] = []
    for step in range(1, args.close_steps + 1):
        force_n = min(
            env.config.control.close_force_n,
            step * env.config.control.close_force_ramp_n_per_step,
        )
        _step_control(env, arm_target, force_n)
        _record_sample(env, trace, "close")

    grasp_position = tuple(float(value) for value in evaluation["target_position"])
    grasp_quaternion = tuple(float(value) for value in evaluation["target_quaternion"])
    destination = env.expert.destination_position
    transfer_height_m = max(
        env.config.task.drop_hand_height_m + 0.10,
        grasp_position[2] + env.config.task.lift_height_m + 0.05,
    )
    phase_contract = (
        (
            "raise",
            (grasp_position[0], grasp_position[1], transfer_height_m),
            args.full_raise_step_m,
        ),
        (
            "transfer",
            (destination[0], destination[1], transfer_height_m),
            args.full_transfer_step_m,
        ),
        (
            "descend",
            (
                destination[0],
                destination[1],
                env.config.task.drop_hand_height_m,
            ),
            args.full_descent_step_m,
        ),
    )
    current_position = tuple(float(value) for value in env.state().end_effector_pose[:3])
    completed_horizon = True
    failure_reason: str | None = None
    planned_waypoint_count = 0
    executed_waypoint_count = 0
    phase_ik_error_max: dict[str, dict[str, float]] = {}

    for phase, target_position, max_step_m in phase_contract:
        waypoints = linear_segment_waypoints(
            current_position,
            target_position,
            max_step_m,
        )
        planned_waypoint_count += len(waypoints)
        max_position_error_m = 0.0
        max_rotation_error_rad = 0.0
        for waypoint in waypoints:
            solved_arm, ik_error = _solve_arm_target(
                env,
                waypoint,
                grasp_quaternion,
                (*arm_target, qpos[7], qpos[8]),
            )
            max_position_error_m = max(
                max_position_error_m,
                math.sqrt(sum(value * value for value in ik_error[:3])),
            )
            max_rotation_error_rad = max(
                max_rotation_error_rad,
                math.sqrt(sum(value * value for value in ik_error[3:])),
            )
            if solved_arm is None:
                completed_horizon = False
                failure_reason = f"{phase}_ik_failure"
                break
            arm_target = solved_arm
            _step_control(env, arm_target, env.config.control.close_force_n)
            executed_waypoint_count += 1
            _record_sample(env, trace, phase, waypoint)
            if float(trace[-1]["contact_force_n"]) > thresholds.max_contact_force_n:
                completed_horizon = False
                failure_reason = f"{phase}_force_abort"
                break
        phase_ik_error_max[phase] = {
            "position_m": max_position_error_m,
            "rotation_rad": max_rotation_error_rad,
        }
        if not completed_horizon:
            break
        for _ in range(args.settle_steps):
            _step_control(env, arm_target, env.config.control.close_force_n)
            _record_sample(env, trace, f"{phase}_settle", target_position)
            if float(trace[-1]["contact_force_n"]) > thresholds.max_contact_force_n:
                completed_horizon = False
                failure_reason = f"{phase}_settle_force_abort"
                break
        if not completed_horizon:
            break
        current_position = tuple(
            float(value) for value in env.state().end_effector_pose[:3]
        )

    final_target = phase_contract[-1][1]
    final_ee_position = tuple(float(value) for value in env.state().end_effector_pose[:3])
    final_position_error_m = math.dist(final_ee_position, final_target)
    if completed_horizon and final_position_error_m > env.config.task.position_tolerance_m:
        completed_horizon = False
        failure_reason = "final_target_not_reached"

    finite = all(
        math.isfinite(value)
        for row in trace
        for key in ("contact_force_n", "ee_position_m", "parcel_position_m", "relative_position_m")
        for value in ((row[key],) if isinstance(row[key], float) else row[key])
    )
    close_rows = trace[: args.close_steps]
    loaded_rows = trace[args.close_steps :]
    captured = any(bool(row["dual_contact"]) for row in close_rows)
    previous_relative = None
    max_relative_step_m = 0.0
    max_downward_step_m = 0.0
    for row in trace:
        relative = tuple(float(value) for value in row["relative_position_m"])
        if previous_relative is not None:
            delta = tuple(
                current - previous
                for current, previous in zip(relative, previous_relative, strict=True)
            )
            max_relative_step_m = max(
                max_relative_step_m,
                math.sqrt(sum(value * value for value in delta)),
            )
            max_downward_step_m = max(max_downward_step_m, delta[2])
        previous_relative = relative
    contact_rows = [row for row in trace if row["dual_contact"]]
    contact_reference = (
        tuple(float(value) for value in contact_rows[0]["relative_position_m"])
        if contact_rows
        else None
    )
    final_relative = (
        tuple(float(value) for value in trace[-1]["relative_position_m"])
        if trace
        else None
    )
    final_relative_drift_m = (
        math.dist(contact_reference, final_relative)
        if contact_reference is not None and final_relative is not None
        else 1_000_000.0
    )
    peak_force_n = max((float(row["contact_force_n"]) for row in trace), default=0.0)
    first_loaded_contact_loss_sample = next(
        (int(row["sample"]) for row in loaded_rows if not row["dual_contact"]),
        None,
    )
    result = {
        "candidate_id": str(evaluation["candidate_id"]),
        "seed_name": str(evaluation["seed_name"]),
        "static_rank": int(evaluation["static_rank"]),
        "completed_horizon": completed_horizon,
        "failure_reason": failure_reason,
        "captured": captured,
        "final_dual_contact": bool(trace and trace[-1]["dual_contact"]),
        "finite": finite,
        "safety_aborted": peak_force_n > thresholds.max_contact_force_n,
        "parcel_lift_m": max(
            (float(row["parcel_position_m"][2]) - initial_parcel_z_m for row in trace),
            default=0.0,
        ),
        "max_relative_step_m": max_relative_step_m,
        "max_downward_step_m": max_downward_step_m,
        "final_relative_drift_m": final_relative_drift_m,
        "peak_contact_force_n": peak_force_n,
        "dual_contact_fraction": (
            sum(bool(row["dual_contact"]) for row in loaded_rows) / len(loaded_rows)
            if loaded_rows
            else 0.0
        ),
        "loaded_sample_count": len(loaded_rows),
        "first_loaded_contact_loss_sample": first_loaded_contact_loss_sample,
        "planned_waypoint_count": planned_waypoint_count,
        "executed_waypoint_count": executed_waypoint_count,
        "phase_metrics": _phase_metrics(trace),
        "targets": {
            "grasp_position_m": grasp_position,
            "transfer_height_m": transfer_height_m,
            "destination_position_m": destination,
            "drop_position_m": final_target,
            "final_ee_position_m": final_ee_position,
            "final_position_error_m": final_position_error_m,
            "phase_ik_error_max": phase_ik_error_max,
        },
        "trace": trace,
    }
    result["stable"] = dynamic_grasp_is_stable(result, thresholds)
    return result


def _rollout_candidate(
    env: GenesisParcelEnv,
    evaluation: Mapping[str, Any],
    args: argparse.Namespace,
    thresholds: DynamicGraspThresholds,
    initial_parcel_z_m: float,
) -> dict[str, Any]:
    if args.horizon == "pre-release":
        return _rollout_pre_release_candidate(
            env,
            evaluation,
            args,
            thresholds,
            initial_parcel_z_m,
        )
    return _rollout_short_candidate(
        env,
        evaluation,
        args,
        thresholds,
        initial_parcel_z_m,
    )


def run(args: argparse.Namespace) -> dict[str, Any]:
    if min(
        args.episode,
        args.max_candidates,
        args.repeats,
        args.close_steps,
        args.lift_steps,
        args.settle_steps,
        args.transfer_steps,
    ) < 1:
        raise ValueError("episode and rollout budgets must be positive")
    if args.lift_m <= 0 or args.transfer_m <= 0:
        raise ValueError("lift and transfer distances must be positive")
    if min(
        args.full_raise_step_m,
        args.full_transfer_step_m,
        args.full_descent_step_m,
    ) <= 0:
        raise ValueError("full-horizon Cartesian steps must be positive")

    config = load_config(args.config)
    config = replace(
        config,
        control=replace(config.control, collision_checked_reset_enabled=True),
    )
    randomizer = DomainRandomizer(config.randomization, config.seed, config.parcel_profiles)
    sample = randomizer.sample_profile(args.profile, args.episode)
    thresholds = DynamicGraspThresholds(max_contact_force_n=config.task.max_contact_force_n)
    started = time.perf_counter_ns()
    with GenesisParcelEnv(config, sample, backend=args.backend) as env:
        state = env.state()
        candidates = generate_box_grasp_pose_candidates(
            sample,
            state.parcel_pose,
            hand_clearance_m=env.expert.grasp_hand_clearance_m(),
        )
        evaluations = [
            env._evaluate_grasp_pose_candidate(candidate, seed_name, seed_qpos)
            for candidate in candidates
            for seed_name, seed_qpos in env._grasp_planning_seeds()
        ]
        ranked_static = rank_grasp_pose_evaluations(evaluations)
        unique_feasible: list[dict[str, Any]] = []
        seen_candidate_ids: set[str] = set()
        for static_rank, evaluation in enumerate(ranked_static):
            candidate_id = str(evaluation["candidate_id"])
            if (
                candidate_id in seen_candidate_ids
                or not grasp_evaluation_is_feasible(evaluation)
            ):
                continue
            row = dict(evaluation)
            row["static_rank"] = static_rank
            unique_feasible.append(row)
            seen_candidate_ids.add(candidate_id)
            if len(unique_feasible) >= args.max_candidates:
                break

        snapshot = env.scene.get_state()
        baseline_state_vector = _state_vector(env)
        initial_parcel_z_m = float(state.parcel_pose[2])
        rollouts: list[dict[str, Any]] = []
        restore_errors: list[float] = []
        for evaluation in unique_feasible:
            for repeat in range(args.repeats):
                env.scene.reset(snapshot)
                restore_errors.append(
                    _max_abs_error(_state_vector(env), baseline_state_vector)
                )
                rollout = _rollout_candidate(
                    env,
                    evaluation,
                    args,
                    thresholds,
                    initial_parcel_z_m,
                )
                rollout["repeat"] = repeat
                rollouts.append(rollout)
                env.scene.reset(snapshot)
                restore_errors.append(
                    _max_abs_error(_state_vector(env), baseline_state_vector)
                )

        ranked_dynamic = rank_dynamic_grasp_evaluations(rollouts, thresholds)
        compact_rank = [
            {key: value for key, value in row.items() if key != "trace"}
            for row in ranked_dynamic
        ]
        return {
            "schema_version": 1,
            "backend": args.backend,
            "config": str(args.config.resolve()),
            "episode": args.episode,
            "profile": args.profile,
            "sample": asdict(sample),
            "thresholds": asdict(thresholds),
            "rollout_contract": {
                "horizon": args.horizon,
                "close_steps": args.close_steps,
                "lift_steps": args.lift_steps,
                "settle_steps": args.settle_steps,
                "transfer_steps": args.transfer_steps,
                "lift_m": args.lift_m,
                "transfer_m": args.transfer_m,
                "close_force_n": config.control.close_force_n,
                "physics_hz": config.simulation.physics_hz,
                "control_hz": config.simulation.control_hz,
                "candidate_initialization": "static_qpos_teleport_diagnostic_only",
                "full_raise_step_m": args.full_raise_step_m,
                "full_transfer_step_m": args.full_transfer_step_m,
                "full_descent_step_m": args.full_descent_step_m,
                "full_transport_execution": (
                    "direct IK joint-position targets; no action-delay queue"
                    if args.horizon == "pre-release"
                    else None
                ),
            },
            "static_candidate_count": len(candidates),
            "static_evaluation_count": len(evaluations),
            "static_feasible_count": sum(
                grasp_evaluation_is_feasible(evaluation)
                for evaluation in evaluations
            ),
            "tested_unique_candidate_count": len(unique_feasible),
            "repeat_count": args.repeats,
            "scene_restore_max_abs_error": max(restore_errors, default=0.0),
            "stable_rollout_count": sum(bool(row["stable"]) for row in rollouts),
            "dynamic_rank": compact_rank,
            "rollouts": rollouts,
            "compute_ms": (time.perf_counter_ns() - started) / 1_000_000,
        }


def main() -> int:
    args = parse_args()
    payload = run(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "episode": payload["episode"],
                "tested_unique_candidate_count": payload["tested_unique_candidate_count"],
                "stable_rollout_count": payload["stable_rollout_count"],
                "scene_restore_max_abs_error": payload["scene_restore_max_abs_error"],
                "compute_ms": payload["compute_ms"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
