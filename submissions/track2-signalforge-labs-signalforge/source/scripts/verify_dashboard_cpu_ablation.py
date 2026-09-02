#!/usr/bin/env python3
"""Verify the publishable SignalForge dashboard CPU-ablation evidence."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "signalforge/dashboard-cpu-ablation/v1"
MAX_THRESHOLD_PERCENT = 1.0
MIN_PAIRS = 3
EXPECTED_MODEL_CALLS = 10
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def verify_report(report: dict[str, Any]) -> dict[str, Any]:
    require(report.get("schema_version") == SCHEMA_VERSION, "unexpected schema_version")

    environment = report.get("environment")
    require(isinstance(environment, dict), "environment must be an object")
    require(environment.get("os") == "linux", "measurement must run on Linux")
    require(environment.get("architecture") in {"x86_64", "amd64"}, "measurement must be amd64")
    require(
        isinstance(environment.get("clock_ticks_per_second"), int)
        and environment["clock_ticks_per_second"] > 0,
        "clock_ticks_per_second must be positive",
    )
    for field in (
        "hostname_sha256",
        "command_sha256",
        "runner_sha256",
        "workload_binary_sha256",
    ):
        require(
            isinstance(environment.get(field), str)
            and SHA256_PATTERN.fullmatch(environment[field]) is not None,
            f"{field} must be a SHA-256 digest",
        )

    policy = report.get("policy")
    require(isinstance(policy, dict), "policy must be an object")
    require(policy.get("order") == "alternating AB/BA", "AB/BA order is required")
    require(
        policy.get("protected_bodies_retained") is False,
        "publishable evidence must not retain protected bodies",
    )

    summary = report.get("summary")
    require(isinstance(summary, dict), "summary must be an object")
    pairs = summary.get("pairs")
    require(isinstance(pairs, int) and pairs >= MIN_PAIRS, "at least three pairs are required")
    threshold = summary.get("threshold_percent")
    require(
        isinstance(threshold, (int, float))
        and 0 < float(threshold) <= MAX_THRESHOLD_PERCENT,
        "threshold_percent must be positive and no greater than one percent",
    )
    median = summary.get("median_overhead_percent")
    require(isinstance(median, (int, float)), "median_overhead_percent must be numeric")
    require(summary.get("status") == "passed", "dashboard CPU ablation did not pass")
    require(float(median) < float(threshold), "median overhead is not below the threshold")
    overheads = summary.get("paired_overhead_percent")
    require(
        isinstance(overheads, list)
        and len(overheads) == pairs
        and all(isinstance(value, (int, float)) for value in overheads),
        "paired overheads must contain one numeric value per pair",
    )

    samples = report.get("samples")
    require(isinstance(samples, list) and len(samples) == pairs * 2, "two samples per pair required")
    seen: set[tuple[int, str]] = set()
    for sample in samples:
        require(isinstance(sample, dict), "each sample must be an object")
        pair = sample.get("pair")
        condition = sample.get("condition")
        require(
            isinstance(pair, int) and 1 <= pair <= pairs,
            "sample pair is outside the declared range",
        )
        require(condition in {"baseline", "dashboard"}, "invalid sample condition")
        identity = (pair, condition)
        require(identity not in seen, "duplicate pair/condition sample")
        seen.add(identity)
        require(
            isinstance(sample.get("complete_journey_cpu_seconds"), (int, float))
            and sample["complete_journey_cpu_seconds"] > 0,
            "complete journey CPU must be positive",
        )
        require(sample.get("model_calls") == EXPECTED_MODEL_CALLS, "unexpected model call count")
        accepted_attempt = sample.get("accepted_attempt")
        require(
            isinstance(accepted_attempt, int) and 1 <= accepted_attempt <= 5,
            "accepted_attempt must be between one and five",
        )
        excluded_attempts = sample.get("excluded_attempts")
        require(
            isinstance(excluded_attempts, list)
            and len(excluded_attempts) == accepted_attempt - 1,
            "excluded_attempts must account for every prior attempt",
        )
        for excluded in excluded_attempts:
            require(isinstance(excluded, dict), "excluded attempt must be an object")
            require(
                isinstance(excluded.get("attempt"), int)
                and 1 <= excluded["attempt"] < accepted_attempt,
                "excluded attempt index is invalid",
            )
            require(
                isinstance(excluded.get("exit_code"), int),
                "excluded attempt requires an exit code",
            )
            require(
                isinstance(excluded.get("stderr_sha256"), str)
                and SHA256_PATTERN.fullmatch(excluded["stderr_sha256"]) is not None,
                "excluded attempt requires a stderr digest",
            )
        for field in ("report_sha256", "answer_sha256"):
            require(
                isinstance(sample.get(field), str)
                and SHA256_PATTERN.fullmatch(sample[field]) is not None,
                f"{field} must be a SHA-256 digest",
            )
        plan_hash = sample.get("execution_plan_sha256")
        if condition == "dashboard":
            require(
                isinstance(plan_hash, str) and SHA256_PATTERN.fullmatch(plan_hash) is not None,
                "dashboard samples require an execution-plan digest",
            )
        else:
            require(plan_hash is None, "baseline samples must not emit execution plans")

    expected = {
        (pair, condition)
        for pair in range(1, pairs + 1)
        for condition in ("baseline", "dashboard")
    }
    require(seen == expected, "sample population is incomplete")
    return {
        "schema_version": SCHEMA_VERSION,
        "pairs": pairs,
        "samples": len(samples),
        "median_overhead_percent": median,
        "threshold_percent": threshold,
        "status": "passed",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    payload = json.loads(args.report.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit("dashboard CPU evidence must be a JSON object")
    print(json.dumps(verify_report(payload), sort_keys=True))


if __name__ == "__main__":
    main()
