"""Descriptive analysis for nested same-episode execution repeats."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import hashlib
import json
import math
import statistics
from typing import Any


def analyze_repeatability_campaign(
    schedule: dict[str, Any],
    summaries: Mapping[tuple[int, str], dict[str, Any]],
) -> dict[str, Any]:
    """Validate and summarize repeats without treating them as independent samples."""
    blocks = schedule.get("blocks", [])
    conditions = tuple(schedule.get("conditions", ()))
    if not blocks or len(conditions) != 2:
        raise ValueError("schedule requires blocks and exactly two conditions")
    expected_keys = {
        (int(block["run_index"]), condition)
        for block in blocks
        for condition in conditions
    }
    if set(summaries) != expected_keys:
        missing = sorted(expected_keys - set(summaries))
        extra = sorted(set(summaries) - expected_keys)
        raise ValueError(f"repeat summaries differ from schedule; missing={missing}, extra={extra}")

    records: dict[int, dict[str, list[dict[str, Any]]]] = {}
    canonical_samples: dict[int, dict[str, Any]] = {}
    threshold: float | None = None
    first_condition_counts = {condition: 0 for condition in conditions}
    for block in blocks:
        run_index = int(block["run_index"])
        episode_id = int(block["episode_id"])
        first_condition_counts[str(block["condition_order"][0])] += 1
        for condition in conditions:
            payload = summaries[(run_index, condition)]
            episodes = payload.get("episodes", [])
            if len(episodes) != 1 or int(episodes[0]["episode_index"]) != episode_id:
                raise ValueError(
                    f"run {run_index} condition {condition} does not contain episode {episode_id}"
                )
            observed_threshold = float(
                payload["config"]["task"]["max_contact_force_n"]
            )
            if threshold is None:
                threshold = observed_threshold
            elif observed_threshold != threshold:
                raise ValueError("contact-force thresholds differ across repeats")
            episode = episodes[0]
            sample = episode.get("sample")
            if not isinstance(sample, dict):
                raise ValueError(f"episode {episode_id} has no randomized sample")
            if episode_id in canonical_samples and sample != canonical_samples[episode_id]:
                raise ValueError(f"episode {episode_id} sample changed across repeats")
            canonical_samples.setdefault(episode_id, sample)
            observation = {
                "run_index": run_index,
                "repeat_index": int(block["repeat_index"]),
                "condition_position": block["condition_order"].index(condition) + 1,
                "episode": episode,
            }
            records.setdefault(episode_id, {}).setdefault(condition, []).append(
                observation
            )

    if threshold is None:
        raise ValueError("repeatability campaign has no observations")
    episode_reports = {}
    for episode_id, condition_records in sorted(records.items()):
        if set(condition_records) != set(conditions):
            raise ValueError(f"episode {episode_id} is missing a condition")
        profile_id = str(canonical_samples[episode_id].get("profile_id", "unknown"))
        episode_reports[str(episode_id)] = {
            "profile_id": profile_id,
            "sample_sha256": _canonical_sha256(canonical_samples[episode_id]),
            "conditions": {
                condition: _condition_summary(
                    sorted(
                        condition_records[condition],
                        key=lambda item: item["repeat_index"],
                    ),
                    threshold,
                )
                for condition in conditions
            },
        }

    instability = {
        condition: {
            "success_unstable_episode_ids": _unstable_episode_ids(
                episode_reports, condition, "success_sequence"
            ),
            "force_abort_unstable_episode_ids": _unstable_episode_ids(
                episode_reports, condition, "force_abort_sequence"
            ),
            "planner_activation_unstable_episode_ids": _unstable_episode_ids(
                episode_reports, condition, "planner_active_sequence"
            ),
        }
        for condition in conditions
    }
    return {
        "schema_version": 1,
        "design": "blocked_nested_same_episode_execution_repeats",
        "schedule_seed": int(schedule["schedule_seed"]),
        "experimental_unit_count": len(episode_reports),
        "nested_repeats_per_episode_condition": int(
            schedule["repeats_per_episode_condition"]
        ),
        "total_execution_observations": len(expected_keys),
        "conditions": list(conditions),
        "condition_first_counts": first_condition_counts,
        "contact_force_threshold_n": threshold,
        "inference_boundary": (
            "descriptive_repeatability_only_nested_repeats_are_not_independent_samples"
        ),
        "episodes": episode_reports,
        "instability": instability,
    }


def _condition_summary(
    observations: Sequence[dict[str, Any]], threshold: float
) -> dict[str, Any]:
    results = [item["episode"]["result"] for item in observations]
    safety = [item["episode"].get("safety_summary", {}) for item in observations]
    successes = [bool(item.get("success", False)) for item in results]
    force_aborts = [
        not bool(item.get("success", False))
        and float(item.get("max_contact_force_n", 0.0)) > threshold
        for item in results
    ]
    drops = [bool(item.get("dropped", False)) for item in results]
    forces = [float(item.get("max_contact_force_n", 0.0)) for item in results]
    active = [
        bool(item.get("geometry_aware_grasp_planning_active", False))
        for item in safety
    ]
    attempts = [int(item.get("grasp_plan_attempts", 0)) for item in safety]
    positions = [int(item["condition_position"]) for item in observations]
    return {
        "repeats": len(observations),
        "run_indices": [item["run_index"] for item in observations],
        "condition_positions": positions,
        "success_count": sum(successes),
        "success_sequence": successes,
        "force_abort_count": sum(force_aborts),
        "force_abort_sequence": force_aborts,
        "drop_count": sum(drops),
        "drop_sequence": drops,
        "max_contact_force_n": _distribution(forces),
        "planner_active_count": sum(active),
        "planner_active_sequence": active,
        "grasp_plan_attempts_total": sum(attempts),
        "by_condition_position": {
            str(position): _position_summary(
                positions, successes, force_aborts, position
            )
            for position in sorted(set(positions))
        },
        "terminal_stage_sequence": [
            str(item["episode"].get("terminal_stage", "unknown"))
            for item in observations
        ],
    }


def _position_summary(
    positions: Sequence[int],
    successes: Sequence[bool],
    force_aborts: Sequence[bool],
    selected_position: int,
) -> dict[str, int]:
    selected = [
        index for index, position in enumerate(positions) if position == selected_position
    ]
    return {
        "trials": len(selected),
        "success_count": sum(successes[index] for index in selected),
        "force_abort_count": sum(force_aborts[index] for index in selected),
    }


def _unstable_episode_ids(
    reports: Mapping[str, dict[str, Any]], condition: str, key: str
) -> list[int]:
    return [
        int(episode_id)
        for episode_id, report in reports.items()
        if len(set(report["conditions"][condition][key])) > 1
    ]


def _distribution(values: Sequence[float]) -> dict[str, float | int]:
    if not values or any(not math.isfinite(value) for value in values):
        raise ValueError("force distribution requires finite values")
    return {
        "count": len(values),
        "mean": statistics.fmean(values),
        "median": statistics.median(values),
        "minimum": min(values),
        "maximum": max(values),
        "population_stddev": statistics.pstdev(values),
    }


def _canonical_sha256(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
