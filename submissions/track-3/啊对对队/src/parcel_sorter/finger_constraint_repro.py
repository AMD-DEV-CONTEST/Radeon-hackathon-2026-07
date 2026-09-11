from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

from .contact_branch import (
    compare_contact_branch_events,
    summarize_contact_branch_events,
)


DYNAMIC_STATE_LENGTHS = {
    "robot_qpos": 9,
    "robot_dof_velocity": 9,
    "robot_dof_actual_force_n": 9,
    "robot_dof_control_force_n": 9,
    "parcel_qpos": 7,
    "parcel_dof_velocity": 6,
}

DYNAMIC_CONTROL_INPUT_LENGTHS = {
    "robot_dof_control_mode": 9,
    "robot_dof_position_target": 9,
    "robot_dof_velocity_target": 9,
    "robot_dof_force_target_n": 9,
}

CONTROL_MODE_NAMES = {
    0: "position",
    1: "velocity",
    2: "force",
}


def summarize_finger_constraint_repro(
    events: Sequence[Mapping[str, Any]],
    *,
    force_abort_n: float,
    penetration_limit_m: float,
) -> dict[str, Any]:
    """Summarize one fixed-command finger/contact reproduction trace."""
    if not math.isfinite(penetration_limit_m) or penetration_limit_m <= 0.0:
        raise ValueError("penetration_limit_m must be finite and positive")
    summary = summarize_contact_branch_events(events, force_abort_n)
    first_penetration_limit = None
    all_values_finite = True
    for event in events:
        all_values_finite &= _all_numeric_values_finite(event)
        if first_penetration_limit is not None:
            continue
        for contact in event.get("contacts", ()):
            penetration_m = float(contact.get("penetration_m", 0.0))
            if penetration_m >= penetration_limit_m:
                first_penetration_limit = {
                    "control_step": int(event["control_step"]),
                    "physics_substep": int(event["physics_substep"]),
                    "penetration_m": penetration_m,
                }
                break
    return {
        **summary,
        "all_recorded_values_finite": all_values_finite,
        "penetration_limit_m": penetration_limit_m,
        "first_penetration_limit": first_penetration_limit,
        "numerical_safety_failure": (
            not all_values_finite
            or summary["first_force_abort"] is not None
            or first_penetration_limit is not None
        ),
    }


def compare_finger_constraint_reproductions(
    reference: Mapping[str, Any],
    candidate: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate and compare stock-inertia and mass-aware reproduction outputs."""
    _validate_pair(reference, candidate)
    contract = reference["contract"]
    comparison = compare_contact_branch_events(
        reference["events"],
        candidate["events"],
        force_difference_n=float(contract["force_difference_n"]),
        finger_position_difference_m=float(
            contract["finger_position_difference_m"]
        ),
        finger_velocity_difference_m_s=float(
            contract["finger_velocity_difference_m_s"]
        ),
        finger_force_difference_n=float(contract["finger_force_difference_n"]),
    )
    reference_failed = bool(reference["summary"]["numerical_safety_failure"])
    candidate_failed = bool(candidate["summary"]["numerical_safety_failure"])
    if reference_failed:
        conclusion = "invalid_reference"
    elif candidate_failed:
        conclusion = "mass_aware_instability_reproduced"
    elif comparison["first_divergence"] is not None:
        conclusion = "bounded_contact_sensitivity_only"
    else:
        conclusion = "not_reproduced"
    return {
        "conclusion": conclusion,
        "reference_numerical_safety_failure": reference_failed,
        "candidate_numerical_safety_failure": candidate_failed,
        "comparison": comparison,
    }


def validate_dynamic_replay_source_events(
    events: Sequence[Mapping[str, Any]],
    *,
    expected_start: tuple[int, int],
) -> list[dict[str, Any]]:
    """Validate a consecutive high-rate state/control sequence for replay."""
    if len(events) < 2:
        raise ValueError("dynamic replay requires at least two source events")
    result: list[dict[str, Any]] = []
    previous_linear_step = None
    for event in events:
        key = (int(event["control_step"]), int(event["physics_substep"]))
        linear_step = key[0] * 8 + key[1]
        if previous_linear_step is not None and linear_step != previous_linear_step + 1:
            raise ValueError("dynamic replay source events must be consecutive")
        previous_linear_step = linear_step
        for field, expected_length in DYNAMIC_STATE_LENGTHS.items():
            values = event.get(field)
            if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
                raise ValueError(f"dynamic replay event is missing {field}")
            if len(values) != expected_length:
                raise ValueError(
                    f"{field} must contain {expected_length} values"
                )
            if not _all_numeric_values_finite(values):
                raise ValueError(f"{field} contains a non-finite value")
        result.append(dict(event))
    first_key = (
        int(result[0]["control_step"]),
        int(result[0]["physics_substep"]),
    )
    if first_key != expected_start:
        raise ValueError(
            f"dynamic replay source must start at {expected_start[0]}/{expected_start[1]}"
        )
    return result


def validate_dynamic_control_replay_source_events(
    events: Sequence[Mapping[str, Any]],
    *,
    expected_start: tuple[int, int],
) -> list[dict[str, Any]]:
    """Validate state plus raw Genesis control inputs for exact-mode replay."""
    result = validate_dynamic_replay_source_events(
        events,
        expected_start=expected_start,
    )
    for event in result:
        partition_dynamic_control_inputs(event)
    return result


def partition_dynamic_control_inputs(
    event: Mapping[str, Any],
) -> dict[str, dict[str, tuple[Any, ...]]]:
    """Group one nine-DOF Genesis control input by its active control mode."""
    values_by_field: dict[str, tuple[float, ...]] = {}
    for field, expected_length in DYNAMIC_CONTROL_INPUT_LENGTHS.items():
        values = event.get(field)
        if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
            raise ValueError(f"dynamic control replay event is missing {field}")
        if len(values) != expected_length:
            raise ValueError(f"{field} must contain {expected_length} values")
        if not _all_numeric_values_finite(values):
            raise ValueError(f"{field} contains a non-finite value")
        values_by_field[field] = tuple(float(value) for value in values)

    modes = values_by_field["robot_dof_control_mode"]
    canonical_modes: list[int] = []
    for mode in modes:
        if not mode.is_integer() or int(mode) not in CONTROL_MODE_NAMES:
            raise ValueError(f"unsupported Genesis control mode: {mode}")
        canonical_modes.append(int(mode))

    target_field_by_mode = {
        0: "robot_dof_position_target",
        1: "robot_dof_velocity_target",
        2: "robot_dof_force_target_n",
    }
    grouped: dict[str, dict[str, tuple[Any, ...]]] = {}
    for mode, name in CONTROL_MODE_NAMES.items():
        indices = tuple(
            index for index, observed_mode in enumerate(canonical_modes)
            if observed_mode == mode
        )
        target_values = values_by_field[target_field_by_mode[mode]]
        grouped[name] = {
            "dof_indices": indices,
            "targets": tuple(target_values[index] for index in indices),
        }
    return grouped


def _validate_pair(
    reference: Mapping[str, Any],
    candidate: Mapping[str, Any],
) -> None:
    allowed_status = {"complete", "safety_stopped"}
    for name, payload in (("reference", reference), ("candidate", candidate)):
        if payload.get("status") not in allowed_status:
            raise ValueError(f"{name} reproduction is incomplete")
        if not payload.get("events"):
            raise ValueError(f"{name} reproduction has no events")
    if reference.get("variant") != "stock_explicit_inertia_ablation":
        raise ValueError("reference must use stock explicit inertia")
    if candidate.get("variant") != "combined_rigid_body":
        raise ValueError("candidate must use combined rigid-body inertia")
    if reference.get("contract") != candidate.get("contract"):
        raise ValueError("reproduction contracts differ")


def _all_numeric_values_finite(value: Any) -> bool:
    if isinstance(value, Mapping):
        return all(_all_numeric_values_finite(item) for item in value.values())
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return all(_all_numeric_values_finite(item) for item in value)
    if isinstance(value, float):
        return math.isfinite(value)
    return True
