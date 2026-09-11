"""Trace-level expert failure attribution for reproducible controller experiments."""

from __future__ import annotations

from collections import Counter
import math
import statistics
from typing import Any

from .metrics import wilson_interval


SCHEMA_VERSION = 1
FACTOR_NAMES = (
    "mass_kg",
    "friction",
    "canonical_abs_yaw_rad",
    "position_x_m",
    "abs_position_y_m",
    "action_delay_steps",
    "grasp_span_m",
    "height_m",
    "volume_m3",
)


def _percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    index = quantile * (len(ordered) - 1)
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return ordered[lower]
    weight = index - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _numeric_summary(values: list[float]) -> dict[str, float | int | None]:
    return {
        "count": len(values),
        "min": min(values) if values else None,
        "p25": _percentile(values, 0.25),
        "median": statistics.median(values) if values else None,
        "mean": statistics.fmean(values) if values else None,
        "p75": _percentile(values, 0.75),
        "p95": _percentile(values, 0.95),
        "max": max(values) if values else None,
    }


def _sample_factors(sample: dict[str, Any]) -> dict[str, float]:
    dimensions = sample.get("dimensions_m")
    if not isinstance(dimensions, list) or len(dimensions) != 3:
        raise ValueError("expert summary sample must contain three dimensions_m values")
    x, y, z = (float(value) for value in dimensions)
    shape = str(sample.get("shape", "box"))
    orientation = str(sample.get("orientation_mode", "yaw"))
    if shape == "cylinder" and orientation == "upright":
        grasp_span = x
        volume = math.pi * (x / 2.0) ** 2 * z
    elif shape == "cylinder" and orientation == "horizontal":
        grasp_span = y
        volume = math.pi * (y / 2.0) ** 2 * x
    else:
        grasp_span = y
        volume = x * y * z
    position = sample.get("position_xy")
    if not isinstance(position, list) or len(position) != 2:
        raise ValueError("expert summary sample must contain two position_xy values")
    yaw_rad = float(sample["yaw_rad"])
    canonical_yaw = (yaw_rad + math.pi / 2.0) % math.pi - math.pi / 2.0
    return {
        "mass_kg": float(sample["mass_kg"]),
        "friction": float(sample["friction"]),
        "canonical_abs_yaw_rad": abs(canonical_yaw),
        "position_x_m": float(position[0]),
        "abs_position_y_m": abs(float(position[1])),
        "action_delay_steps": float(sample["action_delay_steps"]),
        "grasp_span_m": grasp_span,
        "height_m": z,
        "volume_m3": volume,
    }


def _primary_failure_mode(
    *,
    success: bool,
    dropped: bool,
    force_violation: bool,
    terminal_reason: str,
    reached_pregrasp: bool,
    grasp_contact: bool,
    parcel_lifted: bool,
) -> str:
    if success:
        return "complete"
    if force_violation:
        return "force_safety_abort"
    if dropped:
        return "parcel_drop"
    reason_modes = {
        "approaching parcel": "approach_timeout",
        "grasp verification failed": "grasp_verification_failure",
        "grasp lost during lift": "grasp_lost_during_lift",
        "parcel missed destination": "placement_failure",
    }
    if terminal_reason in reason_modes:
        return reason_modes[terminal_reason]
    if not reached_pregrasp:
        return "approach_timeout"
    if not grasp_contact:
        return "grasp_verification_failure"
    if parcel_lifted:
        return "post_lift_failure"
    return "unclassified_failure"


def diagnose_episode(episode: dict[str, Any], force_threshold_n: float) -> dict[str, Any]:
    trace = episode.get("trace")
    sample = episode.get("sample")
    result = episode.get("result")
    if not isinstance(trace, list) or not trace:
        raise ValueError("expert summary episode must contain a non-empty trace")
    if not isinstance(sample, dict) or not isinstance(result, dict):
        raise ValueError("expert summary episode is missing sample or result")

    success = bool(result.get("success"))
    dropped = bool(result.get("dropped"))
    terminal_reason = str(trace[-1].get("reason", "unknown"))
    max_force_n = max(
        float(result.get("max_contact_force_n", 0.0)),
        *(float(frame.get("contact_force_n", 0.0)) for frame in trace),
    )
    force_indices = [
        index
        for index, frame in enumerate(trace)
        if bool(frame.get("excessive_contact_force"))
        or float(frame.get("contact_force_n", 0.0)) > force_threshold_n
    ]
    force_violation = bool(force_indices) or max_force_n > force_threshold_n
    force_context_stage = None
    force_context_command = None
    force_jump_n = None
    if force_indices:
        index = force_indices[0]
        force_frame = trace[index]
        context_index = index - 1
        while context_index >= 0 and trace[context_index].get("stage") == "abort":
            context_index -= 1
        if context_index >= 0:
            context = trace[context_index]
            force_context_stage = str(context.get("stage", "unknown"))
            force_context_command = str(context.get("command", "unknown"))
            force_jump_n = float(force_frame.get("contact_force_n", 0.0)) - float(
                context.get("contact_force_n", 0.0)
            )
        else:
            force_context_stage = "initial_state"
            force_context_command = "none"

    reached_pregrasp = any(bool(frame.get("at_pregrasp")) for frame in trace)
    grasp_contact = any(bool(frame.get("grasp_contact")) for frame in trace)
    parcel_lifted = any(bool(frame.get("parcel_lifted")) for frame in trace)
    entered_place = any(
        frame.get("stage") in {"place", "release", "complete"}
        for frame in trace
    )
    failure_mode = _primary_failure_mode(
        success=success,
        dropped=dropped,
        force_violation=force_violation,
        terminal_reason=terminal_reason,
        reached_pregrasp=reached_pregrasp,
        grasp_contact=grasp_contact,
        parcel_lifted=parcel_lifted,
    )
    return {
        "episode_index": int(episode["episode_index"]),
        "profile_id": str(sample["profile_id"]),
        "success": success,
        "primary_failure_mode": failure_mode,
        "terminal_stage": str(episode.get("terminal_stage", "unknown")),
        "terminal_reason": terminal_reason,
        "retries": int(result.get("retries", 0)),
        "dropped": dropped,
        "trace_frames": len(trace),
        "max_contact_force_n": max_force_n,
        "force_violation": force_violation,
        "force_context_stage": force_context_stage,
        "force_context_command": force_context_command,
        "force_jump_n": force_jump_n,
        "reached_pregrasp": reached_pregrasp,
        "grasp_contact": grasp_contact,
        "parcel_lifted": parcel_lifted,
        "entered_place": entered_place,
        "stage_frame_counts": dict(Counter(str(frame.get("stage", "unknown")) for frame in trace)),
        "factors": _sample_factors(sample),
    }


def _aggregate(diagnoses: list[dict[str, Any]]) -> dict[str, Any]:
    attempts = len(diagnoses)
    successes = sum(bool(item["success"]) for item in diagnoses)
    force_violations = sum(bool(item["force_violation"]) for item in diagnoses)
    success_ci = wilson_interval(successes, attempts)
    force_ci = wilson_interval(force_violations, attempts)
    factor_comparison: dict[str, Any] = {}
    for name in FACTOR_NAMES:
        success_values = [float(item["factors"][name]) for item in diagnoses if item["success"]]
        failure_values = [float(item["factors"][name]) for item in diagnoses if not item["success"]]
        factor_comparison[name] = {
            "successful": _numeric_summary(success_values),
            "failed": _numeric_summary(failure_values),
        }
    return {
        "attempts": attempts,
        "successes": successes,
        "success_rate": successes / attempts,
        "success_rate_ci95_low": success_ci[0],
        "success_rate_ci95_high": success_ci[1],
        "force_safety_violations": force_violations,
        "force_safety_violation_rate": force_violations / attempts,
        "force_safety_violation_rate_ci95_low": force_ci[0],
        "force_safety_violation_rate_ci95_high": force_ci[1],
        "failure_mode_counts": dict(Counter(item["primary_failure_mode"] for item in diagnoses)),
        "terminal_reason_counts": dict(Counter(item["terminal_reason"] for item in diagnoses)),
        "force_context_stage_counts": dict(
            Counter(
                str(item["force_context_stage"])
                for item in diagnoses
                if item["force_violation"]
            )
        ),
        "phase_reach_counts": {
            "pregrasp": sum(bool(item["reached_pregrasp"]) for item in diagnoses),
            "grasp_contact": sum(bool(item["grasp_contact"]) for item in diagnoses),
            "parcel_lifted": sum(bool(item["parcel_lifted"]) for item in diagnoses),
            "place": sum(bool(item["entered_place"]) for item in diagnoses),
        },
        "episodes_with_retries": sum(int(item["retries"]) > 0 for item in diagnoses),
        "dropped_episodes": sum(bool(item["dropped"]) for item in diagnoses),
        "max_contact_force_n": _numeric_summary(
            [float(item["max_contact_force_n"]) for item in diagnoses]
        ),
        "force_jump_n": _numeric_summary(
            [
                float(item["force_jump_n"])
                for item in diagnoses
                if item["force_jump_n"] is not None
            ]
        ),
        "factor_comparison": factor_comparison,
    }


def analyze_expert_summary(payload: dict[str, Any]) -> dict[str, Any]:
    """Analyze a completed expert summary without changing historical evidence."""
    episodes = payload.get("episodes")
    config = payload.get("config")
    if not isinstance(episodes, list) or not episodes:
        raise ValueError("expert summary must contain at least one episode")
    if not isinstance(config, dict) or not isinstance(config.get("task"), dict):
        raise ValueError("expert summary is missing config.task")
    force_threshold_n = float(config["task"]["max_contact_force_n"])
    if not math.isfinite(force_threshold_n) or force_threshold_n <= 0:
        raise ValueError("expert summary contact-force threshold must be positive and finite")

    diagnoses = [diagnose_episode(episode, force_threshold_n) for episode in episodes]
    profile_ids = sorted({str(item["profile_id"]) for item in diagnoses})
    profiles = {
        profile_id: _aggregate(
            [item for item in diagnoses if item["profile_id"] == profile_id]
        )
        for profile_id in profile_ids
    }
    priorities = sorted(
        (
            {
                "profile_id": profile_id,
                "priority_score": (
                    1.0 - float(summary["success_rate"])
                    + float(summary["force_safety_violation_rate"])
                ),
                "success_rate": summary["success_rate"],
                "force_safety_violation_rate": summary["force_safety_violation_rate"],
            }
            for profile_id, summary in profiles.items()
        ),
        key=lambda item: (-float(item["priority_score"]), str(item["profile_id"])),
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "force_threshold_n": force_threshold_n,
        "priority_formula": "(1 - success_rate) + force_safety_violation_rate",
        "global": _aggregate(diagnoses),
        "profiles": profiles,
        "diagnostic_priority": priorities,
        "failed_episodes": [item for item in diagnoses if not item["success"]],
        "limitations": [
            "Factor comparisons are descriptive and do not establish causality.",
            "Small profile samples require fixed-episode reruns before accepting a controller change.",
            "A force-context stage is inferred from the last non-abort frame before the first violation.",
        ],
    }
