#!/usr/bin/env python3
"""Summarize LIBERO success, confidence intervals, and paired improvements."""

from __future__ import annotations

import argparse
from collections import defaultdict
import json
import math
from pathlib import Path
from statistics import NormalDist
from typing import Any


def wilson_interval(successes: int, trials: int, alpha: float = 0.05) -> tuple[float, float]:
    if trials < 1 or not 0 <= successes <= trials:
        raise ValueError("successes/trials are invalid")
    probability = successes / trials
    z = NormalDist().inv_cdf(1.0 - alpha / 2.0)
    denominator = 1.0 + z * z / trials
    center = (probability + z * z / (2.0 * trials)) / denominator
    half = z * math.sqrt(
        probability * (1.0 - probability) / trials + z * z / (4.0 * trials * trials)
    ) / denominator
    return center - half, center + half


def binomial_upper_tail(successes: int, trials: int, probability: float = 0.5) -> float:
    return min(
        1.0,
        math.fsum(
            math.comb(trials, value)
            * probability**value
            * (1.0 - probability) ** (trials - value)
            for value in range(successes, trials + 1)
        ),
    )


def flatten_successes(payload: dict[str, Any]) -> dict[tuple[str, int, int], bool]:
    flattened: dict[tuple[str, int, int], bool] = {}
    for task in payload["per_task"]:
        suite = str(task["task_group"])
        task_id = int(task["task_id"])
        for episode_id, success in enumerate(task["metrics"]["successes"]):
            key = (suite, task_id, episode_id)
            if key in flattened:
                raise ValueError(f"duplicate episode key {key}")
            flattened[key] = bool(success)
    return flattened


def summarize_successes(outcomes: dict[tuple[str, int, int], bool]) -> dict[str, Any]:
    grouped: dict[str, list[bool]] = defaultdict(list)
    for (suite, _, _), success in outcomes.items():
        grouped[suite].append(success)
    result: dict[str, Any] = {}
    for suite, values in sorted(grouped.items()):
        successes = sum(values)
        lower, upper = wilson_interval(successes, len(values))
        result[suite] = {
            "successes": successes,
            "episodes": len(values),
            "success_percent": 100.0 * successes / len(values),
            "wilson_95_percent": [100.0 * lower, 100.0 * upper],
        }
    values = list(outcomes.values())
    successes = sum(values)
    lower, upper = wilson_interval(successes, len(values))
    result["overall"] = {
        "successes": successes,
        "episodes": len(values),
        "success_percent": 100.0 * successes / len(values),
        "wilson_95_percent": [100.0 * lower, 100.0 * upper],
    }
    return result


def paired_comparison(
    baseline: dict[tuple[str, int, int], bool],
    candidate: dict[tuple[str, int, int], bool],
) -> dict[str, Any]:
    if set(baseline) != set(candidate):
        missing_candidate = sorted(set(baseline) - set(candidate))
        missing_baseline = sorted(set(candidate) - set(baseline))
        raise ValueError(
            "paired episode sets differ: "
            f"candidate missing {len(missing_candidate)}, baseline missing {len(missing_baseline)}"
        )
    wins = sum(not baseline[key] and candidate[key] for key in baseline)
    losses = sum(baseline[key] and not candidate[key] for key in baseline)
    ties = len(baseline) - wins - losses
    discordant = wins + losses
    one_sided_p = 1.0 if discordant == 0 else binomial_upper_tail(wins, discordant)
    difference = 100.0 * (sum(candidate.values()) - sum(baseline.values())) / len(baseline)
    lower, upper = paired_newcombe_interval(baseline, candidate)
    return {
        "episodes": len(baseline),
        "candidate_wins": wins,
        "candidate_losses": losses,
        "ties": ties,
        "difference_percentage_points": difference,
        "paired_difference_95_percent": [100.0 * lower, 100.0 * upper],
        "paired_difference_interval_method": "Newcombe-method-10-Wilson-score",
        "exact_one_sided_mcnemar_p": one_sided_p,
        "superiority_at_alpha_0_05": lower > 0.0 and one_sided_p < 0.05,
    }


def paired_newcombe_interval(
    baseline: dict[tuple[str, int, int], bool],
    candidate: dict[tuple[str, int, int], bool],
    alpha: float = 0.05,
) -> tuple[float, float]:
    """Newcombe method 10 interval for a paired difference in proportions."""
    if set(baseline) != set(candidate):
        raise ValueError("paired episode sets differ")
    trials = len(baseline)
    if trials < 1:
        raise ValueError("paired outcomes are empty")
    baseline_successes = sum(baseline.values())
    candidate_successes = sum(candidate.values())
    both_successes = sum(baseline[key] and candidate[key] for key in baseline)
    baseline_probability = baseline_successes / trials
    candidate_probability = candidate_successes / trials
    baseline_lower, baseline_upper = wilson_interval(baseline_successes, trials, alpha)
    candidate_lower, candidate_upper = wilson_interval(candidate_successes, trials, alpha)
    covariance = both_successes / trials - baseline_probability * candidate_probability
    variance_product = (
        baseline_probability
        * (1.0 - baseline_probability)
        * candidate_probability
        * (1.0 - candidate_probability)
    )
    correlation = covariance / math.sqrt(variance_product) if variance_product > 0 else 0.0
    correlation = min(1.0, max(-1.0, correlation))
    difference = candidate_probability - baseline_probability
    lower_radius = math.sqrt(
        max(
            0.0,
            (candidate_probability - candidate_lower) ** 2
            + (baseline_upper - baseline_probability) ** 2
            - 2.0
            * correlation
            * (candidate_probability - candidate_lower)
            * (baseline_upper - baseline_probability),
        )
    )
    upper_radius = math.sqrt(
        max(
            0.0,
            (candidate_upper - candidate_probability) ** 2
            + (baseline_probability - baseline_lower) ** 2
            - 2.0
            * correlation
            * (candidate_upper - candidate_probability)
            * (baseline_probability - baseline_lower),
        )
    )
    return max(-1.0, difference - lower_radius), min(1.0, difference + upper_radius)


def load_eval(path: Path) -> dict[str, Any]:
    if path.is_dir():
        path = path / "eval_info.json"
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    candidate = flatten_successes(load_eval(args.candidate))
    payload: dict[str, Any] = {
        "schema_version": 1,
        "candidate": summarize_successes(candidate),
        "claim_boundary": (
            "Published aggregate scores are context only. Superiority requires paired episode outcomes "
            "from the same frozen task/init-state units."
        ),
    }
    if args.baseline is not None:
        baseline = flatten_successes(load_eval(args.baseline))
        payload["baseline"] = summarize_successes(baseline)
        payload["paired"] = paired_comparison(baseline, candidate)
    rendered = json.dumps(payload, indent=2, sort_keys=True)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
