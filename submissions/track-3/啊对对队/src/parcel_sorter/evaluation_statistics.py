"""Dependency-free statistics for matched closed-loop robot evaluations."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
import itertools
import math
import random
import statistics
from typing import Any

from .metrics import wilson_interval


def exact_mcnemar_test(
    baseline: Sequence[bool],
    candidate: Sequence[bool],
) -> dict[str, int | float]:
    """Return the two-sided exact McNemar test for paired binary outcomes."""
    if len(baseline) != len(candidate) or not baseline:
        raise ValueError("McNemar test requires non-empty paired outcomes")
    baseline_only = sum(old and not new for old, new in zip(baseline, candidate, strict=True))
    candidate_only = sum(new and not old for old, new in zip(baseline, candidate, strict=True))
    discordant = baseline_only + candidate_only
    if discordant == 0:
        p_value = 1.0
    else:
        tail = sum(
            math.comb(discordant, index)
            for index in range(min(baseline_only, candidate_only) + 1)
        ) / (2**discordant)
        p_value = min(1.0, 2.0 * tail)
    return {
        "pairs": len(baseline),
        "baseline_only_positive": baseline_only,
        "candidate_only_positive": candidate_only,
        "discordant_pairs": discordant,
        "p_value_two_sided_exact": p_value,
    }


def paired_mean_difference(
    baseline: Sequence[float],
    candidate: Sequence[float],
    *,
    bootstrap_samples: int = 10_000,
    permutation_samples: int = 10_000,
    seed: int = 20_260_725,
) -> dict[str, int | float | str]:
    """Estimate candidate-minus-baseline change with paired non-parametric inference."""
    if len(baseline) != len(candidate) or not baseline:
        raise ValueError("paired mean difference requires non-empty paired values")
    if bootstrap_samples < 1 or permutation_samples < 1:
        raise ValueError("resample counts must be positive")
    differences = [
        float(new) - float(old)
        for old, new in zip(baseline, candidate, strict=True)
    ]
    if any(not math.isfinite(value) for value in differences):
        raise ValueError("paired values must be finite")
    observed = statistics.fmean(differences)
    rng = random.Random(seed)
    boot = sorted(
        statistics.fmean(rng.choice(differences) for _ in differences)
        for _ in range(bootstrap_samples)
    )
    low = _quantile(boot, 0.025)
    high = _quantile(boot, 0.975)

    absolute_observed = abs(observed)
    if len(differences) <= 16:
        permuted = (
            abs(
                statistics.fmean(
                    sign * value
                    for sign, value in zip(signs, differences, strict=True)
                )
            )
            for signs in itertools.product((-1.0, 1.0), repeat=len(differences))
        )
        extreme = sum(value >= absolute_observed - 1e-15 for value in permuted)
        trials = 2 ** len(differences)
        p_value = extreme / trials
        method = "exact_sign_flip"
    else:
        extreme = 0
        for _ in range(permutation_samples):
            permuted_mean = statistics.fmean(
                value if rng.getrandbits(1) else -value for value in differences
            )
            extreme += abs(permuted_mean) >= absolute_observed - 1e-15
        p_value = (extreme + 1) / (permutation_samples + 1)
        trials = permutation_samples
        method = "monte_carlo_sign_flip"

    return {
        "pairs": len(differences),
        "mean_difference_candidate_minus_baseline": observed,
        "bootstrap_ci95_low": low,
        "bootstrap_ci95_high": high,
        "bootstrap_samples": bootstrap_samples,
        "permutation_method": method,
        "permutation_trials": trials,
        "p_value_two_sided": p_value,
        "random_seed": seed,
    }


def build_campaign_evaluation(
    runs: Mapping[str, dict[str, Any]],
    reference_id: str,
) -> dict[str, Any]:
    """Build a paper-ready report from two or more matched expert summaries."""
    if reference_id not in runs:
        raise ValueError(f"reference run is missing: {reference_id}")
    if len(runs) < 2:
        raise ValueError("campaign evaluation requires at least two runs")

    episode_maps = {
        run_id: _episode_map(payload, run_id) for run_id, payload in runs.items()
    }
    reference_payload = runs[reference_id]
    reference_episodes = episode_maps[reference_id]
    threshold = _force_threshold(reference_payload)
    for run_id, payload in runs.items():
        if _force_threshold(payload) != threshold:
            raise ValueError(f"{run_id} uses a different contact-force threshold")
        episodes = episode_maps[run_id]
        if episodes.keys() != reference_episodes.keys():
            raise ValueError(f"{run_id} does not contain the reference episode set")
        for episode_index, reference_episode in reference_episodes.items():
            if episodes[episode_index].get("sample") != reference_episode.get("sample"):
                raise ValueError(
                    f"{run_id} episode {episode_index} uses a different randomized sample"
                )

    summaries = {
        run_id: _run_summary(episodes, payload, threshold)
        for run_id, (episodes, payload) in (
            (run_id, (episode_maps[run_id], runs[run_id])) for run_id in runs
        )
    }
    comparisons = {
        run_id: _paired_report(
            reference_episodes,
            episode_maps[run_id],
            threshold,
        )
        for run_id in runs
        if run_id != reference_id
    }
    return {
        "schema_version": 1,
        "design": "matched_episode_multi_group",
        "reference_run_id": reference_id,
        "run_ids": list(runs),
        "episode_count": len(reference_episodes),
        "contact_force_threshold_n": threshold,
        "runs": summaries,
        "comparisons_to_reference": comparisons,
        "interpretation": {
            "binary_test": "two-sided exact McNemar",
            "rate_interval": "two-sided Wilson 95%",
            "continuous_effect": "paired candidate-minus-reference mean",
            "continuous_interval": "deterministic paired bootstrap 95%",
            "continuous_test": "paired sign-flip randomization",
            "multiple_comparison_correction": "not_applied",
        },
    }


def _paired_report(
    baseline: Mapping[int, dict[str, Any]],
    candidate: Mapping[int, dict[str, Any]],
    threshold: float,
) -> dict[str, Any]:
    indices = sorted(baseline)
    report = _paired_report_for_indices(baseline, candidate, indices, threshold)
    profile_indices: dict[str, list[int]] = {}
    for episode_index in indices:
        profile_id = str(baseline[episode_index].get("sample", {}).get("profile_id", "unknown"))
        profile_indices.setdefault(profile_id, []).append(episode_index)
    report["by_profile"] = {
        profile_id: _paired_report_for_indices(
            baseline,
            candidate,
            selected,
            threshold,
        )
        for profile_id, selected in sorted(profile_indices.items())
    }
    return report


def _paired_report_for_indices(
    baseline: Mapping[int, dict[str, Any]],
    candidate: Mapping[int, dict[str, Any]],
    indices: Sequence[int],
    threshold: float,
) -> dict[str, Any]:
    baseline_results = [baseline[index]["result"] for index in indices]
    candidate_results = [candidate[index]["result"] for index in indices]
    binary_metrics = {}
    for name, extractor in (
        ("success", lambda result: bool(result.get("success", False))),
        ("drop", lambda result: bool(result.get("dropped", False))),
        ("force_abort", lambda result: _force_abort(result, threshold)),
    ):
        old = [extractor(result) for result in baseline_results]
        new = [extractor(result) for result in candidate_results]
        binary_metrics[name] = {
            "baseline": _rate_summary(old),
            "candidate": _rate_summary(new),
            "rate_difference_candidate_minus_baseline": (
                sum(new) - sum(old)
            ) / len(indices),
            "mcnemar": exact_mcnemar_test(old, new),
        }

    force_effect = paired_mean_difference(
        [float(result.get("max_contact_force_n", 0.0)) for result in baseline_results],
        [float(result.get("max_contact_force_n", 0.0)) for result in candidate_results],
    )
    duration_effect = paired_mean_difference(
        [float(result.get("duration_seconds", 0.0)) for result in baseline_results],
        [float(result.get("duration_seconds", 0.0)) for result in candidate_results],
    )
    return {
        "episode_count": len(indices),
        "binary_metrics": binary_metrics,
        "max_contact_force_n": force_effect,
        "duration_seconds": duration_effect,
    }


def _run_summary(
    episodes: Mapping[int, dict[str, Any]],
    payload: dict[str, Any],
    threshold: float,
) -> dict[str, Any]:
    records = list(episodes.values())
    overall = _records_summary(records, threshold)
    groups: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        profile_id = str(record.get("sample", {}).get("profile_id", "unknown"))
        groups.setdefault(profile_id, []).append(record)
    by_profile = {
        profile_id: _records_summary(group, threshold)
        for profile_id, group in sorted(groups.items())
    }
    overall["macro_profile_success_rate"] = statistics.fmean(
        item["success"]["rate"] for item in by_profile.values()
    )
    overall["reported_successful_parcels_per_hour"] = float(
        payload.get("summary", {}).get("successful_parcels_per_hour", 0.0)
    )
    return {"overall": overall, "by_profile": by_profile}


def _records_summary(
    records: Sequence[dict[str, Any]],
    threshold: float,
) -> dict[str, Any]:
    results = [record["result"] for record in records]
    force = [float(result.get("max_contact_force_n", 0.0)) for result in results]
    duration = [float(result.get("duration_seconds", 0.0)) for result in results]
    latencies = [
        float(value)
        for result in results
        for value in result.get("inference_latency_ms", ())
    ]
    safety = [record.get("safety_summary", {}) for record in records]
    planning_attempts = sum(int(item.get("grasp_plan_attempts", 0)) for item in safety)
    planning_total_ms = sum(
        float(item.get("grasp_plan_compute_ms_total", 0.0)) for item in safety
    )
    return {
        "episodes": len(records),
        "success": _rate_summary([bool(result.get("success", False)) for result in results]),
        "drop": _rate_summary([bool(result.get("dropped", False)) for result in results]),
        "force_abort": _rate_summary([_force_abort(result, threshold) for result in results]),
        "max_contact_force_n": _distribution(force),
        "duration_seconds": _distribution(duration),
        "inference_latency_ms": _distribution(latencies),
        "grasp_planning": {
            "attempts": planning_attempts,
            "compute_ms_total": planning_total_ms,
            "compute_ms_per_attempt": (
                planning_total_ms / planning_attempts if planning_attempts else 0.0
            ),
        },
    }


def _rate_summary(outcomes: Sequence[bool]) -> dict[str, int | float]:
    positives = sum(outcomes)
    low, high = wilson_interval(positives, len(outcomes))
    return {
        "count": positives,
        "trials": len(outcomes),
        "rate": positives / len(outcomes),
        "ci95_low": low,
        "ci95_high": high,
    }


def _distribution(values: Iterable[float]) -> dict[str, int | float]:
    values = sorted(float(value) for value in values)
    if not values:
        return {"count": 0, "mean": 0.0, "median": 0.0, "p95": 0.0, "max": 0.0}
    if any(not math.isfinite(value) for value in values):
        raise ValueError("distribution values must be finite")
    return {
        "count": len(values),
        "mean": statistics.fmean(values),
        "median": statistics.median(values),
        "p95": _quantile(values, 0.95),
        "max": values[-1],
    }


def _quantile(sorted_values: Sequence[float], probability: float) -> float:
    if not sorted_values:
        raise ValueError("quantile requires at least one value")
    index = max(0, math.ceil(probability * len(sorted_values)) - 1)
    return float(sorted_values[index])


def _episode_map(payload: dict[str, Any], run_id: str) -> dict[int, dict[str, Any]]:
    episodes: dict[int, dict[str, Any]] = {}
    for episode in payload.get("episodes", ()):
        episode_index = int(episode["episode_index"])
        if episode_index in episodes:
            raise ValueError(f"{run_id} repeats episode {episode_index}")
        if not isinstance(episode.get("result"), dict):
            raise ValueError(f"{run_id} episode {episode_index} has no result")
        episodes[episode_index] = episode
    if not episodes:
        raise ValueError(f"{run_id} has no episodes")
    return episodes


def _force_threshold(payload: dict[str, Any]) -> float:
    return float(payload["config"]["task"]["max_contact_force_n"])


def _force_abort(result: dict[str, Any], threshold: float) -> bool:
    return (
        not bool(result.get("success", False))
        and float(result.get("max_contact_force_n", 0.0)) > threshold
    )
