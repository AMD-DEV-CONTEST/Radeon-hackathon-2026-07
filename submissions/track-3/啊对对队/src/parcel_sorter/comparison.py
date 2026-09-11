from __future__ import annotations

from typing import Any


def compare_expert_runs(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    *,
    allowed_config_differences: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    baseline_episodes = _episode_map(baseline, "baseline")
    candidate_episodes = _episode_map(candidate, "candidate")
    if baseline_episodes.keys() != candidate_episodes.keys():
        missing = sorted(baseline_episodes.keys() - candidate_episodes.keys())
        extra = sorted(candidate_episodes.keys() - baseline_episodes.keys())
        raise ValueError(
            f"episode sets differ; missing from candidate={missing}, extra={extra}"
        )

    threshold = float(baseline["config"]["task"]["max_contact_force_n"])
    candidate_threshold = float(candidate["config"]["task"]["max_contact_force_n"])
    if candidate_threshold != threshold:
        raise ValueError(
            "contact-force thresholds differ; comparisons require the same safety boundary"
        )
    config_difference_paths = _difference_paths(
        baseline.get("config", {}),
        candidate.get("config", {}),
    )
    if allowed_config_differences is not None:
        allowed = set(allowed_config_differences)
        observed = set(config_difference_paths)
        if observed != allowed:
            missing = sorted(allowed - observed)
            unexpected = sorted(observed - allowed)
            raise ValueError(
                "config differences do not match the experiment contract; "
                f"missing={missing}, unexpected={unexpected}"
            )
    baseline_summary = baseline["summary"]
    candidate_summary = candidate["summary"]
    recovered = []
    regressed = []
    force_improved = []

    for episode_index in sorted(baseline_episodes):
        baseline_episode = baseline_episodes[episode_index]
        candidate_episode = candidate_episodes[episode_index]
        if baseline_episode.get("sample") != candidate_episode.get("sample"):
            raise ValueError(
                f"episode {episode_index} randomization samples differ"
            )
        old = baseline_episode["result"]
        new = candidate_episode["result"]
        if not bool(old["success"]) and bool(new["success"]):
            recovered.append(episode_index)
        if bool(old["success"]) and not bool(new["success"]):
            regressed.append(episode_index)
        old_force = float(old.get("max_contact_force_n", 0.0))
        new_force = float(new.get("max_contact_force_n", 0.0))
        if new_force < old_force:
            force_improved.append(episode_index)

    baseline_force_aborts = _force_abort_indices(baseline_episodes, threshold)
    candidate_force_aborts = _force_abort_indices(candidate_episodes, threshold)
    count = len(baseline_episodes)
    baseline_throughput = float(baseline_summary["successful_parcels_per_hour"])
    candidate_throughput = float(candidate_summary["successful_parcels_per_hour"])
    acceptance = {
        "success_rate_at_least_0_90": float(candidate_summary["success_rate"]) >= 0.90,
        "force_abort_rate_at_most_0_05": len(candidate_force_aborts) / count <= 0.05,
        "drop_rate_not_increased": float(candidate_summary["drop_rate"])
        <= float(baseline_summary["drop_rate"]),
        "throughput_retained_at_least_0_85": candidate_throughput
        >= baseline_throughput * 0.85,
    }

    return {
        "episode_count": count,
        "contact_force_threshold_n": threshold,
        "config_difference_paths": config_difference_paths,
        "baseline_summary": baseline_summary,
        "candidate_summary": candidate_summary,
        "success_rate_delta": float(candidate_summary["success_rate"])
        - float(baseline_summary["success_rate"]),
        "throughput_ratio": (
            candidate_throughput / baseline_throughput if baseline_throughput else 0.0
        ),
        "recovered_episode_indices": recovered,
        "regressed_episode_indices": regressed,
        "force_improved_episode_indices": force_improved,
        "baseline_force_abort_indices": baseline_force_aborts,
        "candidate_force_abort_indices": candidate_force_aborts,
        "baseline_precontact_aabb_guard": _aabb_guard_summary(baseline_episodes),
        "candidate_precontact_aabb_guard": _aabb_guard_summary(candidate_episodes),
        "baseline_approach_velocity_control": _approach_velocity_summary(
            baseline_episodes
        ),
        "candidate_approach_velocity_control": _approach_velocity_summary(
            candidate_episodes
        ),
        "baseline_collision_checked_reset": _collision_checked_reset_summary(
            baseline_episodes
        ),
        "candidate_collision_checked_reset": _collision_checked_reset_summary(
            candidate_episodes
        ),
        "baseline_grasp_planning": _grasp_planning_summary(baseline_episodes),
        "candidate_grasp_planning": _grasp_planning_summary(candidate_episodes),
        "acceptance": acceptance,
        "recommendation": "keep" if all(acceptance.values()) else "repeat_or_reject",
    }


def _aabb_guard_summary(episodes: dict[int, dict[str, Any]]) -> dict[str, Any]:
    """Aggregate optional geometry-filter telemetry without requiring it in old evidence."""
    summaries = [episode.get("safety_summary", {}) for episode in episodes.values()]
    samples = sum(int(item.get("precontact_aabb_guard_samples", 0)) for item in summaries)
    compute_ms = sum(
        float(item.get("precontact_aabb_guard_compute_ms_total", 0.0))
        for item in summaries
    )
    return {
        "enabled": any(bool(item.get("precontact_aabb_guard_enabled", False)) for item in summaries),
        "filter_count": sum(
            int(item.get("precontact_aabb_guard_filter_count", 0)) for item in summaries
        ),
        "max_active_steps": max(
            (int(item.get("precontact_aabb_guard_max_active_steps", 0)) for item in summaries),
            default=0,
        ),
        "samples": samples,
        "compute_ms_total": compute_ms,
        "compute_ms_mean": compute_ms / samples if samples else 0.0,
    }


def _approach_velocity_summary(episodes: dict[int, dict[str, Any]]) -> dict[str, Any]:
    """Aggregate optional operational-space telemetry across matched episodes."""
    summaries = [episode.get("safety_summary", {}) for episode in episodes.values()]
    samples = sum(
        int(item.get("approach_velocity_control_samples", 0)) for item in summaries
    )
    compute_ms = sum(
        float(item.get("approach_velocity_control_compute_ms_total", 0.0))
        for item in summaries
    )
    return {
        "enabled": any(
            bool(item.get("approach_velocity_control_enabled", False))
            for item in summaries
        ),
        "samples": samples,
        "compute_ms_total": compute_ms,
        "compute_ms_mean": compute_ms / samples if samples else 0.0,
        "max_joint_command_rad_s": max(
            (
                float(item.get("approach_velocity_control_max_joint_rad_s", 0.0))
                for item in summaries
            ),
            default=0.0,
        ),
        "max_pose_error_m": max(
            (
                float(item.get("approach_velocity_control_max_pose_error_m", 0.0))
                for item in summaries
            ),
            default=0.0,
        ),
    }


def _collision_checked_reset_summary(
    episodes: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    summaries = [episode.get("safety_summary", {}) for episode in episodes.values()]
    enabled = [
        item for item in summaries if item.get("collision_checked_reset_enabled", False)
    ]
    compute_ms = sum(
        float(item.get("collision_checked_reset_compute_ms", 0.0)) for item in enabled
    )
    return {
        "enabled": bool(enabled),
        "episodes_checked": len(enabled),
        "fallback_episodes": sum(
            bool(item.get("collision_checked_reset_used", False)) for item in enabled
        ),
        "initial_collision_pairs": sum(
            len(item.get("initial_robot_parcel_collisions", ())) for item in enabled
        ),
        "fallback_collision_pairs": sum(
            len(item.get("fallback_robot_parcel_collisions", ())) for item in enabled
        ),
        "compute_ms_total": compute_ms,
        "compute_ms_mean": compute_ms / len(enabled) if enabled else 0.0,
    }


def _grasp_planning_summary(
    episodes: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    summaries = [episode.get("safety_summary", {}) for episode in episodes.values()]
    attempts = sum(int(item.get("grasp_plan_attempts", 0)) for item in summaries)
    compute_ms = sum(
        float(item.get("grasp_plan_compute_ms_total", 0.0)) for item in summaries
    )
    return {
        "configured": any(
            bool(item.get("geometry_aware_grasp_planning_enabled", False))
            for item in summaries
        ),
        "reset_fallback_gate_enabled": any(
            bool(item.get("grasp_planning_reset_fallback_gate_enabled", False))
            for item in summaries
        ),
        "geometry_eligible_episodes": sum(
            bool(item.get("geometry_aware_grasp_planning_geometry_eligible", False))
            for item in summaries
        ),
        "gate_satisfied_episodes": sum(
            item.get("grasp_planning_reset_fallback_gate_satisfied") is True
            for item in summaries
        ),
        "active_episodes": sum(
            bool(item.get("geometry_aware_grasp_planning_active", False))
            for item in summaries
        ),
        "gate_avoided_episodes": sum(
            bool(item.get("grasp_planning_reset_fallback_gate_enabled", False))
            and bool(
                item.get("geometry_aware_grasp_planning_geometry_eligible", False)
            )
            and not bool(item.get("geometry_aware_grasp_planning_active", False))
            for item in summaries
        ),
        "attempts": attempts,
        "compute_ms_total": compute_ms,
        "compute_ms_per_attempt": compute_ms / attempts if attempts else 0.0,
    }


def _difference_paths(
    baseline: Any,
    candidate: Any,
    prefix: str = "",
) -> list[str]:
    if isinstance(baseline, dict) and isinstance(candidate, dict):
        differences = []
        for key in sorted(set(baseline) | set(candidate)):
            path = f"{prefix}.{key}" if prefix else str(key)
            if key not in baseline or key not in candidate:
                differences.append(path)
                continue
            differences.extend(_difference_paths(baseline[key], candidate[key], path))
        return differences
    return [] if baseline == candidate else [prefix or "<root>"]


def _episode_map(payload: dict[str, Any], label: str) -> dict[int, dict[str, Any]]:
    episodes: dict[int, dict[str, Any]] = {}
    for episode in payload.get("episodes", ()):
        episode_index = int(episode["episode_index"])
        if episode_index in episodes:
            raise ValueError(f"{label} repeats episode {episode_index}")
        episodes[episode_index] = episode
    if not episodes:
        raise ValueError(f"{label} has no episodes")
    return episodes


def _force_abort_indices(
    episodes: dict[int, dict[str, Any]],
    threshold: float,
) -> list[int]:
    return sorted(
        episode_index
        for episode_index, episode in episodes.items()
        if not bool(episode["result"]["success"])
        and float(episode["result"].get("max_contact_force_n", 0.0)) > threshold
    )
