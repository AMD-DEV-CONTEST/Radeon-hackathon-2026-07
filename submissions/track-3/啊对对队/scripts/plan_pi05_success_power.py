#!/usr/bin/env python3
"""Pre-register exact success-count gates for the frozen PI0.5 campaign."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from statistics import NormalDist


def binomial_upper_tail(successes: int, trials: int, probability: float) -> float:
    if trials < 1:
        raise ValueError("trials must be positive")
    if not 0.0 <= probability <= 1.0:
        raise ValueError("probability must be in [0, 1]")
    if successes <= 0:
        return 1.0
    if successes > trials:
        return 0.0
    if probability == 0.0:
        return 0.0
    if probability == 1.0:
        return 1.0
    logs = [
        math.lgamma(trials + 1)
        - math.lgamma(value + 1)
        - math.lgamma(trials - value + 1)
        + value * math.log(probability)
        + (trials - value) * math.log1p(-probability)
        for value in range(successes, trials + 1)
    ]
    maximum = max(logs)
    return min(1.0, math.exp(maximum) * math.fsum(math.exp(value - maximum) for value in logs))


def exact_critical_successes(trials: int, null_probability: float, alpha: float) -> int:
    if not 0.0 < alpha < 1.0:
        raise ValueError("alpha must be in (0, 1)")
    for successes in range(trials + 1):
        if binomial_upper_tail(successes, trials, null_probability) <= alpha:
            return successes
    raise ValueError("no rejection threshold exists for the requested design")


def exact_one_sided_lower_bound(
    successes: int, trials: int, alpha: float
) -> float:
    if not 0 <= successes <= trials:
        raise ValueError("successes must be in [0, trials]")
    if successes == 0:
        return 0.0
    low = 0.0
    high = successes / trials
    for _ in range(80):
        midpoint = (low + high) / 2.0
        if binomial_upper_tail(successes, trials, midpoint) < alpha:
            low = midpoint
        else:
            high = midpoint
    return (low + high) / 2.0


def wilson_interval(successes: int, trials: int, alpha: float) -> tuple[float, float]:
    probability = successes / trials
    z = NormalDist().inv_cdf(1.0 - alpha / 2.0)
    denominator = 1.0 + z * z / trials
    center = (probability + z * z / (2.0 * trials)) / denominator
    half_width = (
        z
        * math.sqrt(
            probability * (1.0 - probability) / trials
            + z * z / (4.0 * trials * trials)
        )
        / denominator
    )
    return center - half_width, center + half_width


def required_trials(
    *,
    null_probability: float,
    alternative_probability: float,
    alpha: float,
    target_power: float,
    maximum_trials: int = 5000,
) -> dict[str, float | int]:
    for trials in range(1, maximum_trials + 1):
        try:
            critical = exact_critical_successes(trials, null_probability, alpha)
        except ValueError:
            continue
        power = binomial_upper_tail(critical, trials, alternative_probability)
        if power >= target_power:
            return {
                "trials": trials,
                "critical_successes": critical,
                "achieved_power": power,
            }
    raise ValueError("maximum_trials is too small to reach target power")


def build_plan(
    *,
    trials: int,
    null_probability: float,
    alpha: float,
    engineering_successes: int,
    alternatives: tuple[float, ...],
) -> dict[str, object]:
    critical = exact_critical_successes(trials, null_probability, alpha)
    rows = []
    for successes in range(engineering_successes, trials + 1):
        lower, upper = wilson_interval(successes, trials, alpha)
        rows.append(
            {
                "successes": successes,
                "trials": trials,
                "rate": successes / trials,
                "wilson_two_sided_95": [lower, upper],
                "exact_one_sided_lower_95": exact_one_sided_lower_bound(
                    successes, trials, alpha
                ),
                "rejects_success_probability_at_most_0_90": successes >= critical,
            }
        )
    sensitivity = []
    for alternative in alternatives:
        sensitivity.append(
            {
                "true_success_probability": alternative,
                "power_at_frozen_trials": binomial_upper_tail(
                    critical, trials, alternative
                ),
                "required_for_80_percent_power": required_trials(
                    null_probability=null_probability,
                    alternative_probability=alternative,
                    alpha=alpha,
                    target_power=0.80,
                ),
                "required_for_90_percent_power": required_trials(
                    null_probability=null_probability,
                    alternative_probability=alternative,
                    alpha=alpha,
                    target_power=0.90,
                ),
            }
        )
    return {
        "schema_version": 1,
        "protocol": "pi05-frozen-success-power-preregistration-v1",
        "primary_endpoint": "complete VLA pick-transport-place-release success",
        "experimental_unit": "one unique frozen parcel episode",
        "test": {
            "name": "one-sided exact binomial",
            "null": f"success_probability <= {null_probability:.2f}",
            "alpha": alpha,
            "trials": trials,
            "critical_successes": critical,
            "critical_rate": critical / trials,
        },
        "engineering_gate": {
            "successes": engineering_successes,
            "trials": trials,
            "rate": engineering_successes / trials,
            "interpretation": "minimum point-estimate gate; not proof that the population success probability exceeds 0.90",
        },
        "success_count_sensitivity": rows,
        "power_sensitivity": sensitivity,
        "claim_boundary": (
            "Frames, diffusion samples, retries, and repeated measurements within an "
            "episode are not independent replicates. A >90% population claim requires "
            "the exact-binomial gate in addition to zero expert fallback and unchanged "
            "safety violations."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trials", type=int, default=105)
    parser.add_argument("--null-probability", type=float, default=0.90)
    parser.add_argument("--alpha", type=float, default=0.05)
    parser.add_argument("--engineering-successes", type=int, default=95)
    parser.add_argument(
        "--alternative",
        type=float,
        action="append",
        default=None,
        help="true probability for power sensitivity; may be repeated",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    payload = build_plan(
        trials=args.trials,
        null_probability=args.null_probability,
        alpha=args.alpha,
        engineering_successes=args.engineering_successes,
        alternatives=tuple(args.alternative or (0.94, 0.95, 0.96, 0.97)),
    )
    rendered = json.dumps(payload, indent=2)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
