from __future__ import annotations

import math
from typing import Any, Mapping, Sequence


def _finite_float(value: Any, name: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _integer(value: Any, name: str) -> int:
    result = int(value)
    if result < 0:
        raise ValueError(f"{name} must be non-negative")
    return result


def audit_grasp_scorer_candidate(
    name: str,
    payload: Mapping[str, Any],
    *,
    expected_group_count: int,
    expected_profile_group_count: int,
    expected_profiles: Sequence[str],
    max_warm_p95_ms: float,
) -> dict[str, Any]:
    if not name:
        raise ValueError("candidate name cannot be empty")
    if expected_group_count < 1 or expected_profile_group_count < 1:
        raise ValueError("expected group counts must be positive")
    if max_warm_p95_ms <= 0:
        raise ValueError("latency threshold must be positive")
    if str(payload.get("split")) != "development":
        raise ValueError(f"candidate {name} was not evaluated on development")
    evaluation = payload.get("evaluation")
    latency = payload.get("latency")
    if not isinstance(evaluation, Mapping) or not isinstance(latency, Mapping):
        raise ValueError(f"candidate {name} has no evaluation or latency record")

    group_count = _integer(evaluation.get("group_count"), "group_count")
    model_successes = _integer(
        evaluation.get("model_successes"), "model_successes"
    )
    model_safety_aborts = _integer(
        evaluation.get("model_safety_aborts"), "model_safety_aborts"
    )
    baseline_successes = _integer(
        evaluation.get("baseline_successes"), "baseline_successes"
    )
    baseline_safety_aborts = _integer(
        evaluation.get("baseline_safety_aborts"), "baseline_safety_aborts"
    )
    model_mean_force_n = _finite_float(
        evaluation.get("model_mean_force_n"), "model_mean_force_n"
    )
    model_mean_duration_seconds = _finite_float(
        evaluation.get("model_mean_duration_seconds"),
        "model_mean_duration_seconds",
    )
    warm_p95_ms = _finite_float(
        latency.get("steady_batch_p95_ms"), "steady_batch_p95_ms"
    )

    per_profile = evaluation.get("per_profile")
    if not isinstance(per_profile, Mapping):
        raise ValueError(f"candidate {name} has no per-profile evaluation")
    expected = tuple(sorted(str(profile) for profile in expected_profiles))
    observed = tuple(sorted(str(profile) for profile in per_profile))
    if observed != expected:
        raise ValueError(
            f"candidate {name} profile set differs: {observed} != {expected}"
        )
    profile_audit: dict[str, Any] = {}
    profile_regressions = []
    for profile in expected:
        row = per_profile[profile]
        if not isinstance(row, Mapping):
            raise ValueError(f"candidate {name} profile {profile} is not a mapping")
        profile_groups = _integer(row.get("group_count"), "profile group_count")
        model_aborts = _integer(
            row.get("model_safety_aborts"), "profile model_safety_aborts"
        )
        baseline_aborts = _integer(
            row.get("baseline_safety_aborts"), "profile baseline_safety_aborts"
        )
        if model_aborts > baseline_aborts:
            profile_regressions.append(profile)
        profile_audit[profile] = {
            "group_count": profile_groups,
            "expected_group_count": expected_profile_group_count,
            "complete": profile_groups == expected_profile_group_count,
            "model_safety_aborts": model_aborts,
            "baseline_safety_aborts": baseline_aborts,
            "safety_regression": model_aborts > baseline_aborts,
        }

    if sum(row["group_count"] for row in profile_audit.values()) != group_count:
        raise ValueError(f"candidate {name} profile group counts do not sum")
    if (
        sum(row["model_safety_aborts"] for row in profile_audit.values())
        != model_safety_aborts
    ):
        raise ValueError(f"candidate {name} profile model aborts do not sum")
    if (
        sum(row["baseline_safety_aborts"] for row in profile_audit.values())
        != baseline_safety_aborts
    ):
        raise ValueError(f"candidate {name} profile baseline aborts do not sum")

    reasons = []
    if group_count != expected_group_count:
        reasons.append("incomplete_development_groups")
    if any(not row["complete"] for row in profile_audit.values()):
        reasons.append("incomplete_profile_groups")
    if profile_regressions:
        reasons.append("per_profile_safety_regression")
    if not (
        model_safety_aborts < baseline_safety_aborts
        or model_successes > baseline_successes
    ):
        reasons.append("no_task_or_safety_improvement")
    if warm_p95_ms >= max_warm_p95_ms:
        reasons.append("radeon_latency_gate_failed")
    return {
        "name": name,
        "passes": not reasons,
        "reasons": reasons,
        "dataset_sha256": str(payload.get("dataset_sha256", "")),
        "checkpoint_sha256": str(payload.get("checkpoint_sha256", "")),
        "group_count": group_count,
        "model_successes": model_successes,
        "model_safety_aborts": model_safety_aborts,
        "baseline_successes": baseline_successes,
        "baseline_safety_aborts": baseline_safety_aborts,
        "model_mean_force_n": model_mean_force_n,
        "model_mean_duration_seconds": model_mean_duration_seconds,
        "warm_p95_ms": warm_p95_ms,
        "profile_regressions": profile_regressions,
        "per_profile": profile_audit,
    }


def select_grasp_scorer_candidate(
    candidates: Sequence[tuple[str, Mapping[str, Any]]],
    *,
    expected_group_count: int = 16,
    expected_profile_group_count: int = 4,
    expected_profiles: Sequence[str] = (
        "medium_carton",
        "shoe_box_proxy",
        "large_narrow_carton",
        "near_limit_box",
    ),
    max_warm_p95_ms: float = 5.0,
) -> dict[str, Any]:
    if not candidates:
        raise ValueError("provide at least one grasp scorer candidate")
    names = [name for name, _payload in candidates]
    if len(set(names)) != len(names):
        raise ValueError("grasp scorer candidate names must be unique")
    audits = [
        audit_grasp_scorer_candidate(
            name,
            payload,
            expected_group_count=expected_group_count,
            expected_profile_group_count=expected_profile_group_count,
            expected_profiles=expected_profiles,
            max_warm_p95_ms=max_warm_p95_ms,
        )
        for name, payload in candidates
    ]
    dataset_hashes = {row["dataset_sha256"] for row in audits}
    if "" in dataset_hashes or len(dataset_hashes) != 1:
        raise ValueError("candidates were not evaluated on the same dataset")
    eligible = [row for row in audits if row["passes"]]
    if not eligible:
        return {
            "schema_version": "1.0",
            "status": "no_promotion",
            "selected": None,
            "holdout_opened": False,
            "candidates": audits,
        }
    selected = min(
        eligible,
        key=lambda row: (
            int(row["model_safety_aborts"]),
            -int(row["model_successes"]),
            float(row["model_mean_force_n"]),
            float(row["model_mean_duration_seconds"]),
            float(row["warm_p95_ms"]),
            str(row["name"]),
        ),
    )
    return {
        "schema_version": "1.0",
        "status": "promoted",
        "selected": selected["name"],
        "selected_checkpoint_sha256": selected["checkpoint_sha256"],
        "holdout_opened": False,
        "candidates": audits,
    }
