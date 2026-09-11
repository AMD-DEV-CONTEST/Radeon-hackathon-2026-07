"""Causal attribution audit for reset-fallback-gated planning campaigns."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import math
import statistics
from typing import Any


def audit_reset_fallback_gate(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    *,
    state_tolerance: float = 1e-6,
) -> dict[str, Any]:
    """Separate planner-active effects from planner-inactive execution drift."""
    if not math.isfinite(state_tolerance) or state_tolerance < 0.0:
        raise ValueError("state tolerance must be finite and non-negative")
    baseline_episodes = _episode_map(baseline, "baseline")
    candidate_episodes = _episode_map(candidate, "candidate")
    if baseline_episodes.keys() != candidate_episodes.keys():
        raise ValueError("baseline and candidate episode sets differ")

    threshold = float(baseline["config"]["task"]["max_contact_force_n"])
    if float(candidate["config"]["task"]["max_contact_force_n"]) != threshold:
        raise ValueError("contact-force thresholds differ")

    active: list[int] = []
    inactive: list[int] = []
    gate_avoided: list[int] = []
    geometry_ineligible: list[int] = []
    trace_diagnostics: list[dict[str, Any]] = []
    for episode_index in sorted(baseline_episodes):
        old = baseline_episodes[episode_index]
        new = candidate_episodes[episode_index]
        if old.get("sample") != new.get("sample"):
            raise ValueError(f"episode {episode_index} randomized samples differ")
        safety = new.get("safety_summary", {})
        if safety.get("grasp_planning_reset_fallback_gate_enabled") is not True:
            raise ValueError(f"episode {episode_index} did not enable the reset gate")
        eligible = bool(
            safety.get("geometry_aware_grasp_planning_geometry_eligible", False)
        )
        satisfied = safety.get("grasp_planning_reset_fallback_gate_satisfied") is True
        planner_active = bool(
            safety.get("geometry_aware_grasp_planning_active", False)
        )
        attempts = int(safety.get("grasp_plan_attempts", 0))
        if planner_active and (not eligible or not satisfied):
            raise ValueError(
                f"episode {episode_index} activated planning without satisfying the gate"
            )
        if not planner_active and attempts:
            raise ValueError(
                f"episode {episode_index} recorded planning attempts while inactive"
            )
        if planner_active:
            active.append(episode_index)
        else:
            inactive.append(episode_index)
        if eligible and not planner_active:
            gate_avoided.append(episode_index)
        if not eligible:
            geometry_ineligible.append(episode_index)

        if not planner_active and _binary_outcome(old, threshold) != _binary_outcome(
            new, threshold
        ):
            trace_diagnostics.append(
                _trace_diagnostic(
                    old,
                    new,
                    threshold=threshold,
                    state_tolerance=state_tolerance,
                )
            )

    indices = sorted(baseline_episodes)
    return {
        "schema_version": 1,
        "design": "matched_episode_reset_gate_attribution",
        "contact_force_threshold_n": threshold,
        "state_divergence_tolerance": state_tolerance,
        "episode_count": len(indices),
        "partition_episode_indices": {
            "planner_active": active,
            "planner_inactive": inactive,
            "gate_avoided": gate_avoided,
            "geometry_ineligible": geometry_ineligible,
        },
        "overall": _partition_summary(
            baseline_episodes, candidate_episodes, indices, threshold
        ),
        "planner_active": _partition_summary(
            baseline_episodes, candidate_episodes, active, threshold
        ),
        "planner_inactive": _partition_summary(
            baseline_episodes, candidate_episodes, inactive, threshold
        ),
        "attribution": {
            "planner_active_success_discordant_episode_indices": (
                _success_discordant_indices(
                    baseline_episodes, candidate_episodes, active
                )
            ),
            "planner_inactive_success_discordant_episode_indices": (
                _success_discordant_indices(
                    baseline_episodes, candidate_episodes, inactive
                )
            ),
            "planner_inactive_binary_outcome_drift_episode_indices": [
                item["episode_index"] for item in trace_diagnostics
            ],
            "planner_inactive_drift_interpretation": (
                "execution_nondeterminism_candidate_not_planner_effect"
            ),
        },
        "planner_inactive_trace_diagnostics": trace_diagnostics,
    }


def _partition_summary(
    baseline: Mapping[int, dict[str, Any]],
    candidate: Mapping[int, dict[str, Any]],
    indices: Sequence[int],
    threshold: float,
) -> dict[str, Any]:
    old_success = [_success(baseline[index]) for index in indices]
    new_success = [_success(candidate[index]) for index in indices]
    old_abort = [_force_abort(baseline[index], threshold) for index in indices]
    new_abort = [_force_abort(candidate[index], threshold) for index in indices]
    old_force = [_force(baseline[index]) for index in indices]
    new_force = [_force(candidate[index]) for index in indices]
    attempts = sum(
        int(candidate[index].get("safety_summary", {}).get("grasp_plan_attempts", 0))
        for index in indices
    )
    compute_ms = sum(
        float(
            candidate[index]
            .get("safety_summary", {})
            .get("grasp_plan_compute_ms_total", 0.0)
        )
        for index in indices
    )
    return {
        "episode_count": len(indices),
        "success": _binary_change(old_success, new_success, indices),
        "force_abort": _binary_change(old_abort, new_abort, indices),
        "max_contact_force_n": {
            "baseline_mean": _mean(old_force),
            "candidate_mean": _mean(new_force),
            "paired_mean_difference_candidate_minus_baseline": _mean(
                [new - old for old, new in zip(old_force, new_force, strict=True)]
            ),
        },
        "candidate_grasp_planning": {
            "attempts": attempts,
            "compute_ms_total": compute_ms,
            "compute_ms_per_attempt": compute_ms / attempts if attempts else 0.0,
        },
    }


def _binary_change(
    baseline: Sequence[bool],
    candidate: Sequence[bool],
    indices: Sequence[int],
) -> dict[str, Any]:
    baseline_only = [
        index
        for index, old, new in zip(indices, baseline, candidate, strict=True)
        if old and not new
    ]
    candidate_only = [
        index
        for index, old, new in zip(indices, baseline, candidate, strict=True)
        if new and not old
    ]
    return {
        "baseline_count": sum(baseline),
        "candidate_count": sum(candidate),
        "baseline_only_positive_episode_indices": baseline_only,
        "candidate_only_positive_episode_indices": candidate_only,
        "discordant_pairs": len(baseline_only) + len(candidate_only),
    }


def _trace_diagnostic(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    *,
    threshold: float,
    state_tolerance: float,
) -> dict[str, Any]:
    old_trace = _trace_map(baseline)
    new_trace = _trace_map(candidate)
    common_frames = sorted(old_trace.keys() & new_trace.keys())
    first_decision = next(
        (
            frame
            for frame in common_frames
            if _decision_signature(old_trace[frame])
            != _decision_signature(new_trace[frame])
        ),
        None,
    )
    first_state = next(
        (
            frame
            for frame in common_frames
            if _state_diverged(
                old_trace[frame], new_trace[frame], tolerance=state_tolerance
            )
        ),
        None,
    )
    return {
        "episode_index": int(baseline["episode_index"]),
        "baseline_outcome": _binary_outcome(baseline, threshold),
        "candidate_outcome": _binary_outcome(candidate, threshold),
        "baseline_trace_frames": len(old_trace),
        "candidate_trace_frames": len(new_trace),
        "first_state_divergence_frame": first_state,
        "first_decision_divergence_frame": first_decision,
        "state_precedes_decision": (
            first_state is not None
            and (first_decision is None or first_state < first_decision)
        ),
    }


def _trace_map(episode: dict[str, Any]) -> dict[int, dict[str, Any]]:
    return {int(item["frame"]): item for item in episode.get("trace", ())}


def _decision_signature(frame: dict[str, Any]) -> tuple[Any, ...]:
    return (
        frame.get("stage"),
        frame.get("command"),
        int(frame.get("retry_count", 0)),
    )


def _state_diverged(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    *,
    tolerance: float,
) -> bool:
    for key in ("contact_force_n", "ee_position_m", "parcel_position_m"):
        old = baseline.get(key)
        new = candidate.get(key)
        if isinstance(old, list) and isinstance(new, list):
            if len(old) != len(new) or any(
                abs(float(left) - float(right)) > tolerance
                for left, right in zip(old, new, strict=True)
            ):
                return True
        elif old is None or new is None:
            if old != new:
                return True
        elif abs(float(old) - float(new)) > tolerance:
            return True
    return False


def _success_discordant_indices(
    baseline: Mapping[int, dict[str, Any]],
    candidate: Mapping[int, dict[str, Any]],
    indices: Sequence[int],
) -> list[int]:
    return [
        index
        for index in indices
        if _success(baseline[index]) != _success(candidate[index])
    ]


def _binary_outcome(episode: dict[str, Any], threshold: float) -> dict[str, bool]:
    result = episode["result"]
    return {
        "success": bool(result.get("success", False)),
        "dropped": bool(result.get("dropped", False)),
        "force_abort": _force_abort(episode, threshold),
    }


def _success(episode: dict[str, Any]) -> bool:
    return bool(episode["result"].get("success", False))


def _force(episode: dict[str, Any]) -> float:
    return float(episode["result"].get("max_contact_force_n", 0.0))


def _force_abort(episode: dict[str, Any], threshold: float) -> bool:
    return not _success(episode) and _force(episode) > threshold


def _mean(values: Sequence[float]) -> float | None:
    return statistics.fmean(values) if values else None


def _episode_map(
    payload: dict[str, Any], label: str
) -> dict[int, dict[str, Any]]:
    episodes: dict[int, dict[str, Any]] = {}
    for episode in payload.get("episodes", ()):
        episode_index = int(episode["episode_index"])
        if episode_index in episodes:
            raise ValueError(f"{label} repeats episode {episode_index}")
        episodes[episode_index] = episode
    if not episodes:
        raise ValueError(f"{label} has no episodes")
    return episodes
