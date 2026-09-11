#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import asdict, replace
import json
import math
from pathlib import Path
import sys
import time
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from parcel_sorter.config import load_config
from parcel_sorter.genesis_env import GenesisParcelEnv
from parcel_sorter.grasp_planning import (
    generate_box_grasp_pose_candidates,
    generate_box_oblique_grasp_pose_candidates,
    generate_box_side_grasp_pose_candidates,
    grasp_evaluation_is_feasible,
    rank_grasp_pose_evaluations,
)
from parcel_sorter.randomization import DomainRandomizer


FINGER_LINKS = frozenset({"left_finger", "right_finger"})


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate deterministic box grasp poses with Radeon IK, FK, SVD, and collision queries."
    )
    parser.add_argument("--config", type=Path, default=PROJECT_ROOT / "configs/catalog_v2.toml")
    parser.add_argument("--profile", default="large_narrow_carton")
    parser.add_argument("--episode", type=int, required=True)
    parser.add_argument("--backend", choices=("cpu", "rocm"), default="rocm")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ik-max-samples", type=int, default=8)
    parser.add_argument("--ik-max-iters", type=int, default=40)
    parser.add_argument(
        "--include-side-grasps",
        action="store_true",
        help="also evaluate long-axis side approaches without enabling them in control",
    )
    parser.add_argument(
        "--include-oblique-grasps",
        action="store_true",
        help="also evaluate centred 30/45 degree top-down tilts for tall boxes",
    )
    return parser.parse_args()


def _flat_tuple(value: Any) -> tuple[float, ...]:
    if hasattr(value, "detach"):
        value = value.detach().cpu()
    if hasattr(value, "reshape"):
        value = value.reshape(-1)
    if hasattr(value, "tolist"):
        value = value.tolist()
    return tuple(float(item) for item in value)


def _seed_qpos(env: GenesisParcelEnv) -> tuple[tuple[str, tuple[float, ...]], ...]:
    current = _flat_tuple(env.robot.get_qpos())
    configured = (
        ("current", current),
        ("historical_reset", tuple(env.config.control.reset_qpos)),
        ("collision_free_reset", tuple(env.config.control.collision_free_reset_qpos)),
    )
    unique = []
    for name, values in configured:
        if not any(
            len(values) == len(other) and all(
                math.isclose(value, reference, abs_tol=1e-9)
                for value, reference in zip(values, other, strict=True)
            )
            for _, other in unique
        ):
            unique.append((name, values))
    return tuple(unique)


def _collision_descriptions(env: GenesisParcelEnv) -> list[dict[str, Any]]:
    rows = []
    for geom_a_index, geom_b_index in env.robot.detect_collision():
        geom_a = env.scene.rigid_solver.geoms[int(geom_a_index)]
        geom_b = env.scene.rigid_solver.geoms[int(geom_b_index)]
        entity_a = geom_a.entity
        entity_b = geom_b.entity
        if entity_a is env.robot:
            robot_geom, other_geom = geom_a, geom_b
        elif entity_b is env.robot:
            robot_geom, other_geom = geom_b, geom_a
        else:
            continue
        rows.append(
            {
                "robot_geom_index": int(robot_geom.idx),
                "robot_link": str(robot_geom.link.name),
                "other_geom_index": int(other_geom.idx),
                "other_link": str(other_geom.link.name),
                "other_is_parcel": other_geom.entity is env.parcel,
            }
        )
    return rows


def _evaluate_candidate(
    env: GenesisParcelEnv,
    candidate: Any,
    seed_name: str,
    seed_qpos: tuple[float, ...],
    args: argparse.Namespace,
) -> dict[str, Any]:
    started = time.perf_counter_ns()
    qpos, ik_error = env.robot.inverse_kinematics(
        link=env.end_effector,
        pos=env.np.asarray(candidate.target_position),
        quat=env.np.asarray(candidate.target_quaternion),
        init_qpos=env.np.asarray(seed_qpos),
        respect_joint_limit=True,
        max_samples=args.ik_max_samples,
        max_solver_iters=args.ik_max_iters,
        return_error=True,
    )
    qpos_values = list(_flat_tuple(qpos))
    qpos_values[7:] = (
        env.config.control.open_width_m,
        env.config.control.open_width_m,
    )
    qpos_array = env.np.asarray(qpos_values)
    ik_error_values = _flat_tuple(ik_error)
    finite = all(math.isfinite(value) for value in (*qpos_values, *ik_error_values))

    link_local_index = int(env.end_effector.idx - env.robot.link_start)
    qpos_device = env.robot.get_qpos().device
    fk_positions, fk_quaternions = env.robot.forward_kinematics(
        env.torch.as_tensor(qpos_array, device=qpos_device),
        links_idx_local=env.np.asarray((link_local_index,)),
    )
    fk_position = _flat_tuple(fk_positions)
    fk_quaternion = _flat_tuple(fk_quaternions)
    fk_position_error_m = math.dist(fk_position, candidate.target_position)

    original_qpos = _flat_tuple(env.robot.get_qpos())
    collisions: list[dict[str, Any]] = []
    singular_values: tuple[float, ...] = ()
    clearance_m = 0.0
    restore_error = None
    try:
        env.robot.set_qpos(qpos_array)
        collisions = _collision_descriptions(env)
        clearance_m = env._minimum_nonfinger_parcel_clearance_m()
        jacobian = env.robot.get_jacobian(env.end_effector)[..., :7]
        singular_values = tuple(
            float(value) for value in env.torch.linalg.svdvals(jacobian).detach().cpu()
        )
    finally:
        env.robot.set_qpos(env.np.asarray(original_qpos))
        restored = _flat_tuple(env.robot.get_qpos())
        restore_error = max(
            abs(value - reference)
            for value, reference in zip(restored, original_qpos, strict=True)
        )

    parcel_collisions = [row for row in collisions if row["other_is_parcel"]]
    disallowed_collisions = [
        row
        for row in collisions
        if not (
            row["robot_link"] in FINGER_LINKS and row["other_is_parcel"]
        )
    ]
    joint_distance = math.sqrt(
        sum(
            (value - reference) ** 2
            for value, reference in zip(qpos_values[:7], original_qpos[:7], strict=True)
        )
    )
    min_singular_value = min(singular_values) if singular_values else 0.0
    condition_number = (
        max(singular_values) / min_singular_value
        if min_singular_value > 1e-12
        else None
    )
    evaluation = {
        **asdict(candidate),
        "seed_name": seed_name,
        "qpos": qpos_values,
        "ik_error_pose": ik_error_values,
        "ik_position_error_m": math.sqrt(sum(value * value for value in ik_error_values[:3])),
        "ik_rotation_error_rad": math.sqrt(sum(value * value for value in ik_error_values[3:])),
        "fk_position": fk_position,
        "fk_quaternion": fk_quaternion,
        "fk_position_error_m": fk_position_error_m,
        "joint_distance_rad": joint_distance,
        "jacobian_singular_values": singular_values,
        "minimum_singular_value": min_singular_value,
        "condition_number": condition_number,
        "nonfinger_clearance_m": clearance_m,
        "collisions": collisions,
        "parcel_collision_count": len(parcel_collisions),
        "disallowed_collisions": disallowed_collisions,
        "disallowed_collision_count": len(disallowed_collisions),
        "restore_max_abs_error": restore_error,
        "finite": finite,
        "compute_ms": (time.perf_counter_ns() - started) / 1_000_000,
    }
    evaluation["feasible"] = grasp_evaluation_is_feasible(evaluation)
    return evaluation


def run(args: argparse.Namespace) -> dict[str, Any]:
    config = load_config(args.config)
    config = replace(
        config,
        control=replace(config.control, collision_checked_reset_enabled=True),
    )
    randomizer = DomainRandomizer(config.randomization, config.seed, config.parcel_profiles)
    sample = randomizer.sample_profile(args.profile, args.episode)
    with GenesisParcelEnv(config, sample, backend=args.backend) as env:
        state = env.state()
        candidates = list(generate_box_grasp_pose_candidates(
            sample,
            state.parcel_pose,
            hand_clearance_m=env.expert.grasp_hand_clearance_m(),
        ))
        if args.include_side_grasps:
            candidates.extend(
                generate_box_side_grasp_pose_candidates(
                    sample,
                    state.parcel_pose,
                    hand_clearance_m=env.expert.grasp_hand_clearance_m(),
                )
            )
        if args.include_oblique_grasps:
            candidates.extend(
                generate_box_oblique_grasp_pose_candidates(
                    sample,
                    state.parcel_pose,
                    hand_clearance_m=env.expert.grasp_hand_clearance_m(),
                )
            )
        seeds = _seed_qpos(env)
        rows = [
            _evaluate_candidate(env, candidate, seed_name, seed_qpos, args)
            for candidate in candidates
            for seed_name, seed_qpos in seeds
        ]
        ranked = rank_grasp_pose_evaluations(rows)
        return {
            "schema_version": 2,
            "backend": args.backend,
            "config": str(args.config.resolve()),
            "episode": args.episode,
            "profile": args.profile,
            "sample": asdict(sample),
            "initial_state": asdict(state),
            "candidate_count": len(candidates),
            "seed_count": len(seeds),
            "evaluation_count": len(rows),
            "feasible_count": sum(bool(row["feasible"]) for row in rows),
            "ranking_contract": [
                "feasible_first",
                "disallowed_collision_count",
                "thresholded_ik_position_error",
                "thresholded_ik_rotation_error",
                "thresholded_fk_position_error",
                "canonical_before_symmetric_pi",
                "absolute_longitudinal_offset_m",
                "vertical_offset_m",
                "joint_distance_rad",
                "negative_minimum_singular_value",
                "negative_nonfinger_clearance_m",
            ],
            "candidates": ranked,
        }


def main() -> int:
    args = parse_args()
    if args.episode < 0 or args.ik_max_samples < 1 or args.ik_max_iters < 1:
        raise SystemExit("episode and IK budgets must be positive")
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
                "candidate_count": payload["candidate_count"],
                "evaluation_count": payload["evaluation_count"],
                "feasible_count": payload["feasible_count"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
