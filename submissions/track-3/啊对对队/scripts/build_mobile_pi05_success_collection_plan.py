#!/usr/bin/env python3
"""Build a deterministic, diversity-balanced parcel demonstration plan."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import random
from typing import Any, Callable


GRASP_MODES = ("top_suction", "side_suction", "cooperative_cradle")
DESIGN_CELLS_PER_MODE = 8
TARGET_SUCCESSES_PER_MODE = 500
DEFAULT_PILOT_ATTEMPTS_PER_MODE = 10
DEFAULT_BULK_ATTEMPTS_PER_MODE = 960
COLLECTION_REVISION = 8

TOP_SUCTION_SIZE_RELATIVE = 0.002
TOP_SUCTION_MASS_RELATIVE = 0.005
TOP_SUCTION_FRICTION_RELATIVE = 0.005
TOP_SUCTION_OFFSET_DELTA_M = 0.00025
TOP_SUCTION_YAW_DELTA_RAD = 0.0025

CRADLE_SIZE_RELATIVE = 0.0001
CRADLE_MASS_RELATIVE = 0.0002
CRADLE_FRICTION_RELATIVE = 0.0001
CRADLE_OFFSET_DELTA_M = 0.000001
CRADLE_YAW_DELTA_RAD = 0.000002


TOP_SUCTION_ANCHORS: dict[str, tuple[dict[str, Any], ...]] = {
    "micro_box": (
        {
            "size_m": (0.0637339768, 0.0375, 0.0285),
            "mass_kg": 0.08,
            "friction": 0.355,
            "offset_m": (0.0, 0.0),
            "yaw_rad": 0.0,
        },
    ),
}


CRADLE_ANCHORS: tuple[dict[str, Any], ...] = (
    {
        "size_m": (1.4383370049, 0.1199796566, 0.1798908722),
        "mass_kg": 0.398549662,
        "friction": 0.8998173977,
        "offset_m": (-0.0000365638, 0.000009501),
        "yaw_rad": 0.0001093866,
        "recovery_contact_offset_m": (0.0, 0.0030281706),
        "recovery_left_lift_offset_m": (0.0, 0.0, 0.0018923421),
        "recovery_right_lift_offset_m": (0.000024502, 0.0019897214, -0.0020125477),
    },
    {
        "size_m": (1.4395150683, 0.1199940678, 0.1799681782),
        "mass_kg": 0.3995770794,
        "friction": 0.8999467529,
        "offset_m": (-0.000010662, 0.0000027705),
        "yaw_rad": 0.0000318973,
        "recovery_contact_offset_m": (0.0, 0.0030082146),
        "recovery_left_lift_offset_m": (0.0, 0.0, 0.0019686068),
        "recovery_right_lift_offset_m": (0.0000071448, 0.0019970027, -0.0020036589),
    },
)

TOP_SUCTION_SEEDS = tuple(
    (profile, anchor_index, anchor)
    for profile, anchors in TOP_SUCTION_ANCHORS.items()
    for anchor_index, anchor in enumerate(anchors)
)


def _stratified(count: int, rng: random.Random) -> list[float]:
    values = [(index + rng.random()) / count for index in range(count)]
    rng.shuffle(values)
    return values


def _lerp(low: float, high: float, fraction: float) -> float:
    return round(low + (high - low) * fraction, 10)


def _dimensions(count: int, rng: random.Random, dimensions: int) -> list[list[float]]:
    return [_stratified(count, rng) for _ in range(dimensions)]


def _single_factor_perturbation(
    anchor: dict[str, Any],
    design_cell: int,
    fraction: float,
    *,
    size_relative: float,
    mass_relative: float,
    friction_relative: float,
    offset_delta_m: float,
    yaw_delta_rad: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not 0 <= design_cell < DESIGN_CELLS_PER_MODE:
        raise ValueError("design_cell must be in [0, 7]")
    physical = {
        key: list(value) if isinstance(value, (tuple, list)) else float(value)
        for key, value in anchor.items()
    }
    centered = 2.0 * min(max(float(fraction), 0.0), 1.0) - 1.0
    factors = (
        "size_x",
        "size_y",
        "size_z",
        "mass",
        "friction",
        "offset_x",
        "offset_y",
        "yaw",
    )
    factor = factors[design_cell]
    if design_cell < 3:
        relative_delta = size_relative * centered
        physical["size_m"][design_cell] = round(
            physical["size_m"][design_cell] * (1.0 + relative_delta), 10
        )
        applied_delta = relative_delta
    elif design_cell == 3:
        applied_delta = mass_relative * centered
        physical["mass_kg"] = round(
            physical["mass_kg"] * (1.0 + applied_delta), 10
        )
    elif design_cell == 4:
        applied_delta = friction_relative * centered
        physical["friction"] = round(
            physical["friction"] * (1.0 + applied_delta), 10
        )
    elif design_cell in {5, 6}:
        applied_delta = offset_delta_m * centered
        physical["offset_m"][design_cell - 5] = round(
            physical["offset_m"][design_cell - 5] + applied_delta, 10
        )
    else:
        applied_delta = yaw_delta_rad * centered
        physical["yaw_rad"] = round(physical["yaw_rad"] + applied_delta, 10)
    return physical, {
        "one_factor_cell": design_cell,
        "perturbed_factor": factor,
        "applied_delta": round(applied_delta, 10),
    }


def _interpolate_anchor_path(
    anchors: tuple[dict[str, Any], ...], fraction: float
) -> tuple[dict[str, Any], dict[str, Any]]:
    position = min(max(float(fraction), 0.0), 1.0) * (len(anchors) - 1)
    lower_index = min(int(position), len(anchors) - 1)
    upper_index = min(lower_index + 1, len(anchors) - 1)
    alpha = position - lower_index
    lower = anchors[lower_index]
    upper = anchors[upper_index]
    physical: dict[str, Any] = {}
    for key, lower_value in lower.items():
        upper_value = upper[key]
        if isinstance(lower_value, (tuple, list)):
            physical[key] = [
                _lerp(float(first), float(second), alpha)
                for first, second in zip(lower_value, upper_value, strict=True)
            ]
        else:
            physical[key] = _lerp(float(lower_value), float(upper_value), alpha)
    return physical, {
        "anchor_lower_index": lower_index,
        "anchor_upper_index": upper_index,
        "anchor_alpha": round(alpha, 10),
    }


def _top_suction(
    index: int, count: int, fractions: list[list[float]]
) -> dict[str, Any]:
    seed_index = (index * 7) % len(TOP_SUCTION_SEEDS)
    profile, profile_anchor_index, anchor = TOP_SUCTION_SEEDS[seed_index]
    design_cell = index % DESIGN_CELLS_PER_MODE
    physical, perturbation = _single_factor_perturbation(
        anchor,
        design_cell,
        fractions[0][index],
        size_relative=TOP_SUCTION_SIZE_RELATIVE,
        mass_relative=TOP_SUCTION_MASS_RELATIVE,
        friction_relative=TOP_SUCTION_FRICTION_RELATIVE,
        offset_delta_m=TOP_SUCTION_OFFSET_DELTA_M,
        yaw_delta_rad=TOP_SUCTION_YAW_DELTA_RAD,
    )
    return {
        "profile": profile,
        "shape": "box",
        "orientation_mode": "yaw",
        "yaw_rad": physical["yaw_rad"],
        "handling_class": "parallel_jaw",
        "grasp_mode": "top_suction",
        "minimum_sealed_cups": 1,
        "cooperative_cradle": False,
        "size_m": physical["size_m"],
        "mass_kg": physical["mass_kg"],
        "friction": physical["friction"],
        "offset_m": physical["offset_m"],
        # The 5/5 successful top-suction evidence used the nominal controller.
        # Recovery offsets are corrective trajectories, not generic demonstrations.
        "retry_index": 0,
        "parameter_envelope_revision": "top-current-success-one-factor-v6",
        "anchor_provenance": {
            "seed_index": seed_index,
            "profile_anchor_index": profile_anchor_index,
            **perturbation,
        },
        "task_text": (
            f"Pick up the {profile.replace('_', ' ')} with top suction and place it "
            "at the marked parcel destination."
        ),
    }


def _side_suction(
    index: int, count: int, fractions: list[list[float]]
) -> dict[str, Any]:
    diameter = _lerp(0.041, 0.045, fractions[0][index])
    return {
        "profile": "upright_canister",
        "shape": "cylinder",
        "orientation_mode": "upright",
        "yaw_rad": 0.0,
        "handling_class": "parallel_jaw",
        "grasp_mode": "side_suction",
        "minimum_sealed_cups": 1,
        "cooperative_cradle": False,
        "size_m": [
            diameter,
            diameter,
            _lerp(0.067, 0.073, fractions[1][index]),
        ],
        "mass_kg": _lerp(0.15, 0.19, fractions[2][index]),
        "friction": _lerp(0.29, 0.32, fractions[3][index]),
        "offset_m": [
            _lerp(-0.003, 0.003, fractions[4][index]),
            _lerp(-0.003, 0.003, fractions[5][index]),
        ],
        "recovery_contact_offset_m": [
            0.0,
            _lerp(0.0055, 0.0065, fractions[7][index]),
        ],
        "recovery_contact_penetration_delta_m": _lerp(
            0.00025, 0.00075, fractions[8][index]
        ),
        "recovery_vertical_speed_scale": 0.60,
        "retry_index": 1,
        "parameter_envelope_revision": "side-recovery-v2-8-of-8",
        "task_text": (
            "Pick up the upright canister with side suction and place it at the "
            "marked parcel destination."
        ),
    }


def _cooperative_cradle(
    index: int, count: int, fractions: list[list[float]]
) -> dict[str, Any]:
    anchor_index = (index // 3) % len(CRADLE_ANCHORS)
    design_cell = index % DESIGN_CELLS_PER_MODE
    physical, perturbation = _single_factor_perturbation(
        CRADLE_ANCHORS[anchor_index],
        design_cell,
        fractions[0][index],
        size_relative=CRADLE_SIZE_RELATIVE,
        mass_relative=CRADLE_MASS_RELATIVE,
        friction_relative=CRADLE_FRICTION_RELATIVE,
        offset_delta_m=CRADLE_OFFSET_DELTA_M,
        yaw_delta_rad=CRADLE_YAW_DELTA_RAD,
    )
    return {
        "profile": "large_rectangular_carton_boundary",
        "shape": "box",
        "orientation_mode": "yaw",
        "yaw_rad": physical["yaw_rad"],
        "handling_class": "cradle_required",
        "grasp_mode": "cooperative_cradle",
        "minimum_sealed_cups": 1,
        "cooperative_cradle": True,
        "cradle_contact_memory": True,
        "size_m": physical["size_m"],
        "mass_kg": physical["mass_kg"],
        "friction": physical["friction"],
        "offset_m": physical["offset_m"],
        "recovery_contact_offset_m": physical["recovery_contact_offset_m"],
        "recovery_contact_penetration_delta_m": 0.0,
        "recovery_cradle_engagement_delta_m": 0.0,
        "recovery_left_lift_offset_m": physical["recovery_left_lift_offset_m"],
        "recovery_right_lift_offset_m": physical["recovery_right_lift_offset_m"],
        "recovery_vertical_speed_scale": 1.0,
        "retry_index": 2,
        "parameter_envelope_revision": "cradle-verified-anchor-one-factor-v8",
        "anchor_provenance": {
            "anchor_index": anchor_index,
            **perturbation,
        },
        "task_text": (
            "Pick up the large rectangular carton with cooperative cradle control "
            "and place it at the marked parcel destination."
        ),
    }


BUILDERS: dict[
    str, Callable[[int, int, list[list[float]]], dict[str, Any]]
] = {
    "top_suction": _top_suction,
    "side_suction": _side_suction,
    "cooperative_cradle": _cooperative_cradle,
}


def _success_quotas(successes_per_mode: int) -> dict[str, int]:
    base, remainder = divmod(successes_per_mode, DESIGN_CELLS_PER_MODE)
    return {
        f"{mode}-cell-{cell:02d}": base + int(cell < remainder)
        for mode in GRASP_MODES
        for cell in range(DESIGN_CELLS_PER_MODE)
    }


def build_plan(attempts_per_mode: int, seed: int, phase: str) -> dict[str, Any]:
    if attempts_per_mode < DESIGN_CELLS_PER_MODE:
        raise ValueError("attempts_per_mode must cover every design cell")
    if phase not in {"pilot", "bulk"}:
        raise ValueError("phase must be pilot or bulk")
    if phase == "bulk" and attempts_per_mode < TARGET_SUCCESSES_PER_MODE:
        raise ValueError("bulk attempts_per_mode cannot be below its success quota")
    episodes_by_mode: dict[str, list[dict[str, Any]]] = {}
    for mode_index, mode in enumerate(GRASP_MODES):
        rng = random.Random(seed + 1009 * mode_index)
        fractions = _dimensions(attempts_per_mode, rng, 15)
        builder = BUILDERS[mode]
        mode_episodes = []
        for index in range(attempts_per_mode):
            item = builder(index, attempts_per_mode, fractions)
            item.update(
                {
                    "episode_id": f"parcel-success-{phase}-v{COLLECTION_REVISION}-{mode}-{index:04d}",
                    "design_cell": (
                        f"{mode}-cell-{index % DESIGN_CELLS_PER_MODE:02d}"
                    ),
                    "split": "collection_candidate",
                    "demonstration_provenance": "deterministic_expert_candidate",
                    "source_identity": (
                        f"parcel-success-{phase}-v{COLLECTION_REVISION}/{mode}/{index:04d}"
                    ),
                }
            )
            mode_episodes.append(item)
        episodes_by_mode[mode] = mode_episodes
    # Early pilot evidence must cover every mode instead of exhausting one mode first.
    episodes = [
        episodes_by_mode[mode][index]
        for index in range(attempts_per_mode)
        for mode in GRASP_MODES
    ]
    success_quotas = (
        _success_quotas(TARGET_SUCCESSES_PER_MODE) if phase == "bulk" else {}
    )
    candidate_attempts_by_design_cell = {
        cell: sum(item["design_cell"] == cell for item in episodes)
        for cell in {
            f"{mode}-cell-{index:02d}"
            for mode in GRASP_MODES
            for index in range(DESIGN_CELLS_PER_MODE)
        }
    }
    return {
        "schema_version": 1,
        "collection_id": f"parcel-success-{phase}-v{COLLECTION_REVISION}",
        "protocol": "pi05-success-current-contract-video-backed-v8",
        "seed": seed,
        "phase": phase,
        "attempts_per_mode": attempts_per_mode,
        "planned_attempts": len(episodes),
        "success_quotas_by_design_cell": success_quotas,
        "target_success_dataset": {
            "total_successes": TARGET_SUCCESSES_PER_MODE * len(GRASP_MODES),
            "successes_per_mode": TARGET_SUCCESSES_PER_MODE,
            "train": 1200,
            "development": 150,
            "confirmation": 150,
            "independent_unit": "unique_simulated_physical_episode_parameters",
            "candidate_attempts_by_design_cell": (
                candidate_attempts_by_design_cell if phase == "bulk" else {}
            ),
            "candidate_reserve_policy": (
                "stop each cell immediately at its 62/63-success quota"
                if phase == "bulk"
                else "pilot only"
            ),
        },
        "admission_policy": (
            "Only complete deterministic-expert demonstrations with a saved nonempty "
            "wrist RGB-D episode and no force violation enter behavior cloning. Their "
            "provenance remains expert_demo and never counts as pure-VLA task success. "
            "Failed attempts remain failure telemetry."
        ),
        "literature_alignment": {
            "target_domain_examples_per_cell": 50,
            "design_cells": 24,
            "long_trajectory_sampling_cap_per_stage": 100,
            "sampling_policy": "equal grasp-mode and design-cell probability",
            "evidence": [
                "OpenVLA arXiv:2406.09246v3: 10-150 target demonstrations per task",
                "OpenVLA-OFT arXiv:2502.19645v2: 500 demonstrations across 10 LIBERO tasks",
                "Octo arXiv:2405.12213v2: about 100 in-domain trajectories per fine-tune",
                "SmolVLA arXiv:2506.01844v1: 50 demonstrations per real-world task",
                "pi0.5 arXiv:2504.16054v1: successful bounded-length episodes in post-training",
            ],
        },
        "training_mixture": {
            "bootstrap_behavior_cloning": {
                "verified_target_successes": 1.0,
                "external_robot_replay": 0.0,
                "reason": (
                    "target fine-tuning is the common adaptation recipe and the external "
                    "DROID action/embodiment contract is not directly compatible"
                ),
            },
            "within_target": {
                "top_suction": 1 / 3,
                "side_suction": 1 / 3,
                "cooperative_cradle": 1 / 3,
                "design_cell_sampling": "uniform within grasp mode",
                "episode_stage_sampling": "at most 100 frames per stage",
            },
            "optional_general_replay_ablation": {
                "first_two_thirds": {"target": 0.9, "adapted_droid": 0.1},
                "final_third": {"target": 1.0, "adapted_droid": 0.0},
                "enabled_by_default": False,
                "gate": "requires a separate action adapter and matched normalization",
            },
        },
        "pilot_acceptance_gate": {
            "minimum_attempts_per_mode": 10,
            "minimum_success_rate_per_mode": 0.70,
        },
        "episodes": episodes,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--attempts-per-mode", type=int)
    parser.add_argument("--seed", type=int, default=20260729)
    parser.add_argument("--phase", choices=("pilot", "bulk"), default="pilot")
    args = parser.parse_args()
    attempts_per_mode = args.attempts_per_mode or (
        DEFAULT_PILOT_ATTEMPTS_PER_MODE
        if args.phase == "pilot"
        else DEFAULT_BULK_ATTEMPTS_PER_MODE
    )
    plan = build_plan(attempts_per_mode, args.seed, args.phase)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({
        "output": str(args.output),
        "planned_attempts": plan["planned_attempts"],
        "attempts_per_mode": plan["attempts_per_mode"],
        "seed": plan["seed"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
