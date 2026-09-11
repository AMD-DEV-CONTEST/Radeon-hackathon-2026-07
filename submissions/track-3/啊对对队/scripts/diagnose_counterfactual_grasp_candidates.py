#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import asdict, replace
import json
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
from parcel_sorter.grasp_stability import full_episode_grasp_rank_key
from parcel_sorter.randomization import DomainRandomizer
from parcel_sorter.runner import run_expert_episode


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run controller-faithful closed-loop counterfactuals while forcing "
            "one statically feasible grasp candidate. This is diagnostic only."
        )
    )
    parser.add_argument("--config", type=Path, default=PROJECT_ROOT / "configs/catalog_v2.toml")
    parser.add_argument("--profile", required=True)
    parser.add_argument("--episode", type=int, required=True)
    parser.add_argument("--backend", choices=("cpu", "rocm"), default="rocm")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--candidate-id", action="append", default=[])
    parser.add_argument("--all-candidates", action="store_true")
    parser.add_argument("--max-candidates", type=int, default=6)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument(
        "--contact-wrench-telemetry",
        action="store_true",
        help=(
            "record read-only post-contact wrench diagnostics; this does not "
            "change candidate ranking or controller actions"
        ),
    )
    parser.add_argument(
        "--contact-wrench-backend",
        choices=("cpu", "rocm"),
        default="cpu",
        help="diagnostic scorer backend; Genesis physics remains on --backend",
    )
    parser.add_argument(
        "--parcel-gripper-adapter",
        action="store_true",
        help="use the generated open-source parcel finger adapter",
    )
    parser.add_argument(
        "--parcel-gripper-extension-m",
        type=float,
        default=None,
        help="override the adapter extension length in metres",
    )
    parser.add_argument(
        "--parcel-gripper-density-kg-m3",
        type=float,
        default=None,
        help="override the effective adapter density used for finger inertia",
    )
    parser.add_argument(
        "--parcel-gripper-stock-inertia",
        action="store_true",
        help=(
            "diagnostic ablation: keep stock finger inertia while retaining "
            "adapter collision geometry"
        ),
    )
    parser.add_argument(
        "--contact-branch-telemetry",
        action="store_true",
        help="capture all robot contacts and finger dynamics at physics rate",
    )
    parser.add_argument("--contact-branch-frame-start", type=int, default=196)
    parser.add_argument("--contact-branch-frame-end", type=int, default=204)
    parser.add_argument(
        "--planning-activation",
        choices=("reset-fallback", "geometry-eligible", "all-boxes"),
        default="reset-fallback",
        help=(
            "activate planning only after reset fallback, for every parcel "
            "inside the frozen tall-box scope, or for every rigid box"
        ),
    )
    parser.add_argument(
        "--inactive-gate",
        choices=("error", "skip"),
        default="error",
        help="fail or emit a structured skip when the formal reset gate is inactive",
    )
    return parser.parse_args()


def _static_candidate_rows(
    env: GenesisParcelEnv,
) -> tuple[list[dict[str, Any]], set[str]]:
    state = env.state()
    candidates = generate_box_grasp_pose_candidates(
        env.sample,
        state.parcel_pose,
        hand_clearance_m=env.expert.grasp_hand_clearance_m(),
    )
    evaluations = [
        env._evaluate_grasp_pose_candidate(candidate, seed_name, seed_qpos)
        for candidate in candidates
        for seed_name, seed_qpos in env._grasp_planning_seeds()
    ]
    ranked = rank_grasp_pose_evaluations(evaluations)
    unique_feasible: list[dict[str, Any]] = []
    seen: set[str] = set()
    for static_rank, evaluation in enumerate(ranked):
        candidate_id = str(evaluation["candidate_id"])
        if candidate_id in seen or not grasp_evaluation_is_feasible(evaluation):
            continue
        row = dict(evaluation)
        row["static_rank"] = static_rank
        unique_feasible.append(row)
        seen.add(candidate_id)
    return unique_feasible, {candidate.candidate_id for candidate in candidates}


def _compact_static_row(evaluation: Mapping[str, Any]) -> dict[str, Any]:
    keys = (
        "candidate_id",
        "seed_name",
        "static_rank",
        "target_position",
        "target_quaternion",
        "longitudinal_offset_m",
        "vertical_offset_m",
        "wrist_variant",
        "minimum_singular_value",
        "joint_distance_rad",
        "nonfinger_clearance_m",
        "disallowed_collision_count",
    )
    return {key: evaluation[key] for key in keys}


def _selected_candidate_id(safety_summary: Mapping[str, Any]) -> str | None:
    for event in safety_summary.get("grasp_plan_events", ()):
        selected = event.get("selected")
        if selected is not None:
            return str(selected["candidate_id"])
    return None


def _first_force_abort_frame(
    trace: tuple[dict[str, Any], ...],
    threshold_n: float,
) -> int | None:
    return next(
        (
            int(row["frame"])
            for row in trace
            if float(row["contact_force_n"]) > threshold_n
        ),
        None,
    )


def run(args: argparse.Namespace) -> dict[str, Any]:
    if args.episode < 0 or min(args.max_candidates, args.repeats) < 1:
        raise ValueError("episode must be non-negative and budgets must be positive")
    if args.all_candidates == bool(args.candidate_id):
        raise ValueError("choose exactly one of --all-candidates or --candidate-id")
    if args.parcel_gripper_stock_inertia and not args.parcel_gripper_adapter:
        raise ValueError("stock-inertia ablation requires --parcel-gripper-adapter")

    config = load_config(args.config)
    config = replace(
        config,
        task=replace(
            config.task,
            max_grasp_retries=0,
            geometry_aware_grasp_planning_enabled=True,
            grasp_planning_reset_fallback_gate_enabled=(
                args.planning_activation == "reset-fallback"
            ),
            grasp_planning_transport_contract_enabled=True,
            grasp_planning_transport_lookahead_enabled=False,
            parcel_gripper_adapter_enabled=args.parcel_gripper_adapter,
            parcel_gripper_adapter_extension_m=(
                config.task.parcel_gripper_adapter_extension_m
                if args.parcel_gripper_extension_m is None
                else args.parcel_gripper_extension_m
            ),
            parcel_gripper_adapter_density_kg_m3=(
                config.task.parcel_gripper_adapter_density_kg_m3
                if args.parcel_gripper_density_kg_m3 is None
                else args.parcel_gripper_density_kg_m3
            ),
            parcel_gripper_adapter_inertia_enabled=(
                not args.parcel_gripper_stock_inertia
            ),
        ),
        control=replace(
            config.control,
            collision_checked_reset_enabled=True,
            transport_slip_recovery_enabled=False,
            transport_slip_setdown_regrasp_enabled=False,
        ),
    )
    config.validate()
    randomizer = DomainRandomizer(config.randomization, config.seed, config.parcel_profiles)
    sample = randomizer.sample_profile(args.profile, args.episode)
    started = time.perf_counter_ns()

    with GenesisParcelEnv(config, sample, backend=args.backend) as discovery_env:
        if args.planning_activation == "all-boxes":
            discovery_env.set_diagnostic_all_box_grasp_planning()
        feasible, all_candidate_ids = _static_candidate_rows(discovery_env)
        planner_active = discovery_env.geometry_grasp_planning_active
    feasible_by_id = {str(row["candidate_id"]): row for row in feasible}
    if args.all_candidates:
        selected_ids = list(feasible_by_id)[: args.max_candidates]
    else:
        selected_ids = [str(candidate_id) for candidate_id in args.candidate_id]
    missing = sorted(set(selected_ids) - set(feasible_by_id))
    if missing:
        raise ValueError("requested candidates are not statically feasible: " + ", ".join(missing))
    if not planner_active:
        if args.inactive_gate == "error":
            raise RuntimeError(
                f"{args.planning_activation} policy did not activate geometry planning"
            )
        skipped_status = (
            "skipped_inactive_reset_gate"
            if args.planning_activation == "reset-fallback"
            else "skipped_ineligible_geometry"
        )
        return {
            "schema_version": 1,
            "status": skipped_status,
            "backend": args.backend,
            "config": str(args.config.resolve()),
            "episode": args.episode,
            "profile": args.profile,
            "sample": asdict(sample),
            "contract": {
                "controller_faithful": True,
                "fresh_scene_per_rollout": True,
                "collision_checked_reset_enabled": True,
                "planning_activation_policy": args.planning_activation,
                "reset_fallback_gate_enabled": (
                    args.planning_activation == "reset-fallback"
                ),
                "reset_fallback_gate_satisfied": False,
                "geometry_planning_active": False,
                "labels_generated": False,
                "reason": (
                    "geometry planning is not active under the frozen "
                    f"{args.planning_activation} policy"
                ),
            },
            "static_feasible_candidates": [
                _compact_static_row(row) for row in feasible
            ],
            "tested_candidate_ids": [],
            "repeat_count": args.repeats,
            "ranked_rollouts": [],
            "rollouts": [],
            "compute_ms": (time.perf_counter_ns() - started) / 1_000_000,
        }

    rollouts: list[dict[str, Any]] = []
    for candidate_id in selected_ids:
        static_row = feasible_by_id[candidate_id]
        for repeat in range(args.repeats):
            with GenesisParcelEnv(
                config,
                sample,
                backend=args.backend,
                capture_contact_wrench_telemetry=args.contact_wrench_telemetry,
                contact_wrench_telemetry_backend=args.contact_wrench_backend,
                contact_branch_control_window=(
                    (
                        args.contact_branch_frame_start,
                        args.contact_branch_frame_end,
                    )
                    if args.contact_branch_telemetry
                    else None
                ),
            ) as env:
                if args.planning_activation == "all-boxes":
                    env.set_diagnostic_all_box_grasp_planning()
                env.set_diagnostic_grasp_candidate_allowlist(
                    frozenset({candidate_id})
                )
                report = run_expert_episode(
                    env,
                    config,
                    sample,
                    args.episode,
                )
            selected = _selected_candidate_id(report.safety_summary)
            if selected != candidate_id:
                raise RuntimeError(
                    f"forced candidate mismatch: requested {candidate_id}, selected {selected}"
                )
            result = report.result
            force_abort_frame = _first_force_abort_frame(
                report.trace,
                config.task.max_contact_force_n,
            )
            rollouts.append(
                {
                    "candidate_id": candidate_id,
                    "repeat": repeat,
                    "static_rank": int(static_row["static_rank"]),
                    "success": result.success,
                    "safety_aborted": force_abort_frame is not None,
                    "force_abort_frame": force_abort_frame,
                    "dropped": result.dropped,
                    "max_contact_force_n": result.max_contact_force_n,
                    "duration_seconds": result.duration_seconds,
                    "terminal_stage": report.terminal_stage,
                    "selected_candidate_id": selected,
                    "planner_attempts": report.safety_summary["grasp_plan_attempts"],
                    "transport_final_phase": report.safety_summary[
                        "grasp_planning_transport_final_phase"
                    ],
                    "contact_wrench_summary": report.safety_summary[
                        "contact_wrench_summary"
                    ],
                    "contact_wrench_samples": report.safety_summary[
                        "contact_wrench_samples"
                    ],
                    "contact_wrench_device": report.safety_summary[
                        "contact_wrench_device"
                    ],
                    "contact_wrench_telemetry_backend": report.safety_summary[
                        "contact_wrench_telemetry_backend"
                    ],
                    "contact_branch_summary": report.safety_summary[
                        "contact_branch_summary"
                    ],
                    "contact_branch_device": report.safety_summary[
                        "contact_branch_device"
                    ],
                    "report": report.to_dict(),
                }
            )

    ranked = sorted(rollouts, key=full_episode_grasp_rank_key)
    return {
        "schema_version": 1,
        "status": "complete",
        "backend": args.backend,
        "config": str(args.config.resolve()),
        "episode": args.episode,
        "profile": args.profile,
        "sample": asdict(sample),
        "contract": {
            "controller_faithful": True,
            "fresh_scene_per_rollout": True,
            "collision_checked_reset_enabled": True,
            "planning_activation_policy": args.planning_activation,
            "reset_fallback_gate_enabled": (
                args.planning_activation == "reset-fallback"
            ),
            "geometry_planning_active": True,
            "labels_generated": True,
            "transport_contract_enabled": True,
            "transport_lookahead_enabled": False,
            "max_grasp_retries": 0,
            "force_abort_n": config.task.max_contact_force_n,
            "contact_wrench_telemetry_enabled": args.contact_wrench_telemetry,
            "contact_wrench_telemetry_backend": args.contact_wrench_backend,
            "contact_wrench_sample_hz": config.simulation.control_hz,
            "parcel_gripper_adapter_enabled": (
                config.task.parcel_gripper_adapter_enabled
            ),
            "parcel_gripper_adapter_extension_m": (
                config.task.parcel_gripper_adapter_extension_m
            ),
            "parcel_gripper_adapter_density_kg_m3": (
                config.task.parcel_gripper_adapter_density_kg_m3
            ),
            "parcel_gripper_adapter_inertia_enabled": (
                config.task.parcel_gripper_adapter_inertia_enabled
            ),
            "parcel_gripper_adapter_mass_per_finger_kg": (
                (
                    0.020
                    * 0.008
                    * config.task.parcel_gripper_adapter_extension_m
                    * config.task.parcel_gripper_adapter_density_kg_m3
                )
                if (
                    config.task.parcel_gripper_adapter_enabled
                    and config.task.parcel_gripper_adapter_inertia_enabled
                )
                else 0.0
            ),
            "parcel_gripper_adapter_inertia_model": (
                "combined_rigid_body"
                if (
                    config.task.parcel_gripper_adapter_enabled
                    and config.task.parcel_gripper_adapter_inertia_enabled
                )
                else (
                    "stock_explicit_inertia_ablation"
                    if config.task.parcel_gripper_adapter_enabled
                    else "stock_explicit_inertia"
                )
            ),
            "contact_branch_telemetry_enabled": args.contact_branch_telemetry,
            "contact_branch_control_window": (
                [args.contact_branch_frame_start, args.contact_branch_frame_end]
                if args.contact_branch_telemetry
                else None
            ),
            "contact_branch_changes_controller": False,
            "contact_branch_dynamic_state_fields": [
                "robot_qpos",
                "robot_dof_velocity",
                "robot_dof_actual_force_n",
                "robot_dof_control_force_n",
                "parcel_qpos",
                "parcel_dof_velocity",
            ],
            "contact_branch_control_input_fields": [
                "robot_dof_control_mode",
                "robot_dof_position_target",
                "robot_dof_velocity_target",
                "robot_dof_force_target_n",
            ],
            "contact_wrench_changes_controller": False,
            "contact_wrench_changes_ranking": False,
            "only_intervention": "reject every generated candidate ID except the target",
        },
        "static_feasible_candidates": [
            _compact_static_row(row) for row in feasible
        ],
        "tested_candidate_ids": selected_ids,
        "repeat_count": args.repeats,
        "ranked_rollouts": [
            {key: value for key, value in row.items() if key != "report"}
            for row in ranked
        ],
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
                "status": payload["status"],
                "episode": payload["episode"],
                "tested_candidate_ids": payload["tested_candidate_ids"],
                "ranked_rollouts": payload["ranked_rollouts"],
                "compute_ms": payload["compute_ms"],
            },
            allow_nan=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
