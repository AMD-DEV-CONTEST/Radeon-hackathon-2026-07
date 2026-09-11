"""Paired development gate for bounded mobile SmolVLA arm residual execution."""

from __future__ import annotations

import math
import statistics
from typing import Any

from .metrics import wilson_interval


def evaluate_arm_residual_development_gate(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    *,
    minimum_trials: int = 12,
    placement_margin_m: float = 0.01,
) -> dict[str, Any]:
    """Authorize a new holdout only after paired task, safety, and actuation checks."""

    if minimum_trials < 1 or placement_margin_m < 0.0:
        raise ValueError("gate limits are invalid")
    baseline_runs = _indexed_runs(baseline, "baseline")
    candidate_runs = _indexed_runs(candidate, "candidate")
    if len(candidate_runs) < minimum_trials:
        raise ValueError(f"candidate must contain at least {minimum_trials} trials")
    same_episode_ids = baseline_runs.keys() == candidate_runs.keys()
    if not same_episode_ids:
        raise ValueError("baseline and candidate episode ids differ")
    same_parameters = all(
        baseline_runs[key].get("parameters") == candidate_runs[key].get("parameters")
        for key in baseline_runs
    )
    baseline_successes = sum(bool(run.get("success")) for run in baseline_runs.values())
    candidate_successes = sum(bool(run.get("success")) for run in candidate_runs.values())
    regressions = [
        key
        for key in baseline_runs
        if baseline_runs[key].get("success") and not candidate_runs[key].get("success")
    ]
    recoveries = [
        key
        for key in baseline_runs
        if not baseline_runs[key].get("success") and candidate_runs[key].get("success")
    ]
    candidate_errors = [
        float(run["placement_error_m"])
        for run in candidate_runs.values()
        if run.get("success") and run.get("placement_error_m") is not None
    ]
    baseline_errors = [
        float(run["placement_error_m"])
        for run in baseline_runs.values()
        if run.get("success") and run.get("placement_error_m") is not None
    ]
    baseline_mean_error = statistics.fmean(baseline_errors) if baseline_errors else None
    candidate_mean_error = statistics.fmean(candidate_errors) if candidate_errors else None
    arm_actuated = sum(
        int((run.get("policy") or {}).get("arm_residual", {}).get("applied_physics_steps") or 0)
        > 0
        for run in candidate_runs.values()
    )
    transport_eligible = sum(
        int((run.get("policy") or {}).get("stages", {}).get("transport") or 0) > 0
        for run in candidate_runs.values()
    )
    arm_ik_accepts = sum(
        int((run.get("policy") or {}).get("arm_residual", {}).get("ik_update_accepts") or 0)
        for run in candidate_runs.values()
    )
    arm_ik_rejections = sum(
        int((run.get("policy") or {}).get("arm_residual", {}).get("ik_update_rejections") or 0)
        for run in candidate_runs.values()
    )
    force_violations = sum(
        float((run.get("suction") or {}).get("max_contact_force_n") or 0.0) >= 35.0
        for run in candidate_runs.values()
    )
    checks = {
        "same_parameters": same_parameters,
        "candidate_success_not_worse": candidate_successes >= baseline_successes,
        "no_baseline_success_regression": not regressions,
        "zero_force_violations": force_violations == 0,
        "arm_actuated_every_transport_run": arm_actuated == transport_eligible,
        "arm_ik_accepted": arm_ik_accepts > 0,
        "zero_arm_ik_rejections": arm_ik_rejections == 0,
        "placement_error_within_margin": (
            baseline_mean_error is not None
            and candidate_mean_error is not None
            and candidate_mean_error <= baseline_mean_error + placement_margin_m
        ),
    }
    authorized = all(checks.values())
    return {
        "schema_version": 1,
        "protocol": "mobile-smolvla-anchored-arm-residual-development-gate-v1",
        "status": "holdout_authorized" if authorized else "candidate_rejected",
        "closed_loop_holdout_authorized": authorized,
        "checks": checks,
        "trials": len(candidate_runs),
        "baseline_successes": baseline_successes,
        "candidate_successes": candidate_successes,
        "paired_recoveries": recoveries,
        "paired_regressions": regressions,
        "mean_success_placement_error_m": {
            "baseline": baseline_mean_error,
            "candidate": candidate_mean_error,
        },
        "arm_actuated_run_count": arm_actuated,
        "transport_eligible_run_count": transport_eligible,
        "arm_ik_accepts": arm_ik_accepts,
        "arm_ik_rejections": arm_ik_rejections,
        "force_violation_count": force_violations,
        "claim_boundary": (
            "paired parameter-randomized development gate; not frozen holdout task success "
            "or broad generalization"
        ),
    }


def evaluate_arm_residual_holdout_gate(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    *,
    minimum_trials: int = 100,
    target_success_rate: float = 0.80,
    noninferiority_margin: float = 0.05,
    placement_margin_m: float = 0.01,
) -> dict[str, Any]:
    """Evaluate a frozen paired holdout without reusing development outcomes."""

    if minimum_trials < 100:
        raise ValueError("holdout gate requires at least 100 trials")
    if not 0.0 < target_success_rate <= 1.0:
        raise ValueError("target success rate must be in (0, 1]")
    if not 0.0 <= noninferiority_margin < 1.0 or placement_margin_m < 0.0:
        raise ValueError("holdout gate margins are invalid")
    baseline_runs = _indexed_runs(baseline, "baseline")
    candidate_runs = _indexed_runs(candidate, "candidate")
    if len(candidate_runs) < minimum_trials:
        raise ValueError(f"candidate must contain at least {minimum_trials} trials")
    if baseline_runs.keys() != candidate_runs.keys():
        raise ValueError("baseline and candidate episode ids differ")
    same_parameters = all(
        baseline_runs[key].get("parameters") == candidate_runs[key].get("parameters")
        for key in baseline_runs
    )
    if not same_parameters:
        raise ValueError("baseline and candidate physical parameters differ")

    trials = len(candidate_runs)
    baseline_successes = sum(bool(run.get("success")) for run in baseline_runs.values())
    candidate_successes = sum(bool(run.get("success")) for run in candidate_runs.values())
    baseline_rate = baseline_successes / trials
    candidate_rate = candidate_successes / trials
    baseline_wilson = wilson_interval(baseline_successes, trials)
    candidate_wilson = wilson_interval(candidate_successes, trials)
    paired = {
        "both_success": 0,
        "both_failure": 0,
        "candidate_recovery": 0,
        "candidate_regression": 0,
    }
    regressions = []
    recoveries = []
    for episode_id in baseline_runs:
        baseline_success = bool(baseline_runs[episode_id].get("success"))
        candidate_success = bool(candidate_runs[episode_id].get("success"))
        if baseline_success and candidate_success:
            paired["both_success"] += 1
        elif not baseline_success and not candidate_success:
            paired["both_failure"] += 1
        elif candidate_success:
            paired["candidate_recovery"] += 1
            recoveries.append(episode_id)
        else:
            paired["candidate_regression"] += 1
            regressions.append(episode_id)

    paired_placement_deltas = [
        float(candidate_runs[episode_id]["placement_error_m"])
        - float(baseline_runs[episode_id]["placement_error_m"])
        for episode_id in baseline_runs
        if baseline_runs[episode_id].get("success")
        and candidate_runs[episode_id].get("success")
        and baseline_runs[episode_id].get("placement_error_m") is not None
        and candidate_runs[episode_id].get("placement_error_m") is not None
    ]

    baseline_errors = _successful_placement_errors(baseline_runs)
    candidate_errors = _successful_placement_errors(candidate_runs)
    baseline_mean_error = statistics.fmean(baseline_errors) if baseline_errors else None
    candidate_mean_error = statistics.fmean(candidate_errors) if candidate_errors else None
    transport_eligible = sum(_transport_eligible(run) for run in candidate_runs.values())
    arm_actuated = sum(_arm_actuated(run) for run in candidate_runs.values())
    arm_ik_attempts = sum(_arm_metric(run, "ik_update_attempts") for run in candidate_runs.values())
    arm_ik_accepts = sum(_arm_metric(run, "ik_update_accepts") for run in candidate_runs.values())
    arm_ik_rejections = sum(_arm_metric(run, "ik_update_rejections") for run in candidate_runs.values())
    force_violations = sum(_force_violation(run) for run in candidate_runs.values())
    single_radeon_rocm = sum(_single_radeon_rocm(run) for run in candidate_runs.values())
    checks = {
        "same_parameters": same_parameters,
        "target_success_rate": candidate_rate >= target_success_rate,
        "point_estimate_noninferiority": (
            candidate_rate + noninferiority_margin >= baseline_rate
        ),
        "wilson_noninferiority": (
            candidate_wilson[0] + noninferiority_margin >= baseline_wilson[0]
        ),
        "zero_force_violations": force_violations == 0,
        "arm_actuated_every_transport_run": arm_actuated == transport_eligible,
        "arm_ik_accepted": arm_ik_accepts > 0,
        "zero_arm_ik_rejections": arm_ik_rejections == 0,
        "single_radeon_rocm_every_run": single_radeon_rocm == trials,
        "placement_error_within_margin": (
            baseline_mean_error is not None
            and candidate_mean_error is not None
            and candidate_mean_error <= baseline_mean_error + placement_margin_m
        ),
    }
    promoted = all(checks.values())
    return {
        "schema_version": 1,
        "protocol": "mobile-smolvla-anchored-arm-residual-frozen-holdout-v1",
        "status": "promoted" if promoted else "completed_not_promoted",
        "promoted": promoted,
        "checks": checks,
        "trials": trials,
        "baseline": {
            "successes": baseline_successes,
            "success_rate": baseline_rate,
            "wilson_95": list(baseline_wilson),
            "mean_success_placement_error_m": baseline_mean_error,
        },
        "candidate": {
            "successes": candidate_successes,
            "success_rate": candidate_rate,
            "wilson_95": list(candidate_wilson),
            "mean_success_placement_error_m": candidate_mean_error,
            "force_violation_count": force_violations,
            "arm_actuated_run_count": arm_actuated,
            "transport_eligible_run_count": transport_eligible,
            "arm_ik_attempts": arm_ik_attempts,
            "arm_ik_accepts": arm_ik_accepts,
            "arm_ik_rejections": arm_ik_rejections,
            "single_radeon_rocm_run_count": single_radeon_rocm,
        },
        "paired": paired,
        "paired_statistics": {
            "success_rate_delta": candidate_rate - baseline_rate,
            "mcnemar_exact_two_sided_p": _exact_mcnemar_two_sided(
                paired["candidate_recovery"], paired["candidate_regression"]
            ),
            "common_success_placement_pairs": len(paired_placement_deltas),
            "mean_placement_error_delta_m": (
                statistics.fmean(paired_placement_deltas)
                if paired_placement_deltas
                else None
            ),
            "median_placement_error_delta_m": (
                statistics.median(paired_placement_deltas)
                if paired_placement_deltas
                else None
            ),
        },
        "paired_recoveries": recoveries,
        "paired_regressions": regressions,
        "thresholds": {
            "minimum_trials": minimum_trials,
            "target_success_rate": target_success_rate,
            "noninferiority_margin": noninferiority_margin,
            "placement_margin_m": placement_margin_m,
            "force_limit_n": 35.0,
        },
        "claim_boundary": (
            "frozen parameter-randomized holdout for the anchored transport arm residual; "
            "not unseen-geometry, dual-arm load sharing, sim-to-real, or full-action VLA"
        ),
    }
def _indexed_runs(payload: dict[str, Any], name: str) -> dict[str, dict[str, Any]]:
    if payload.get("status") != "passed":
        raise ValueError(f"{name} campaign audit did not pass")
    runs = payload.get("runs")
    if not isinstance(runs, list) or not runs:
        raise ValueError(f"{name} campaign has no runs")
    indexed = {str(run.get("episode_id")): run for run in runs}
    if "" in indexed or len(indexed) != len(runs):
        raise ValueError(f"{name} campaign episode ids are invalid")
    return indexed


def _successful_placement_errors(
    runs: dict[str, dict[str, Any]],
) -> list[float]:
    return [
        float(run["placement_error_m"])
        for run in runs.values()
        if run.get("success") and run.get("placement_error_m") is not None
    ]


def _arm_metric(run: dict[str, Any], name: str) -> int:
    return int((run.get("policy") or {}).get("arm_residual", {}).get(name) or 0)


def _transport_eligible(run: dict[str, Any]) -> int:
    return int((run.get("policy") or {}).get("stages", {}).get("transport") or 0) > 0


def _arm_actuated(run: dict[str, Any]) -> int:
    return _arm_metric(run, "applied_physics_steps") > 0


def _force_violation(run: dict[str, Any]) -> int:
    return int(float((run.get("suction") or {}).get("max_contact_force_n") or 0.0) >= 35.0)


def _single_radeon_rocm(run: dict[str, Any]) -> int:
    runtime = run.get("runtime") or {}
    return int(
        bool(runtime.get("rocm"))
        and runtime.get("gpu_count") == 1
        and str(runtime.get("gpu_name", "")).startswith("AMD Radeon")
        and runtime.get("cuda") is None
    )


def _exact_mcnemar_two_sided(recoveries: int, regressions: int) -> float:
    """Return the exact two-sided sign-test form of McNemar's test."""

    if recoveries < 0 or regressions < 0:
        raise ValueError("paired discordance counts cannot be negative")
    discordant = recoveries + regressions
    if discordant == 0:
        return 1.0
    tail = sum(
        math.comb(discordant, index) for index in range(min(recoveries, regressions) + 1)
    ) / (2**discordant)
    return min(1.0, 2.0 * tail)
