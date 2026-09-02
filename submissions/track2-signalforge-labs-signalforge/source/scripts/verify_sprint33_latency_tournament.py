#!/usr/bin/env python3
"""Verify the privacy-safe aggregate of the Sprint 33 Radeon tournament."""

from __future__ import annotations

import argparse
import json
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "evidence" / "sprint33-latency-tournament.json"
MODE_IDS = {
    "baseline_context_concurrency_2",
    "local_context_concurrency_4",
    "hybrid_context_concurrency_4",
}
FORBIDDEN_KEYS = {
    "case_metrics",
    "journey_id",
    "prompt",
    "reasoning",
    "response",
    "source_excerpt",
}


def decimal(value: Any) -> Decimal:
    return Decimal(str(value))


def rounded(value: Decimal, places: str) -> Decimal:
    return value.quantize(Decimal(places), rounding=ROUND_HALF_UP)


def find_forbidden_keys(value: Any, location: str = "$") -> list[str]:
    findings: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_location = f"{location}.{key}"
            if key in FORBIDDEN_KEYS:
                findings.append(child_location)
            findings.extend(find_forbidden_keys(child, child_location))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            findings.extend(find_forbidden_keys(child, f"{location}[{index}]"))
    return findings


def verify(payload: dict[str, Any]) -> dict[str, Any]:
    failures: list[str] = []
    if payload.get("schema_version") != "signalforge/public-latency-tournament/v1":
        failures.append("unexpected schema_version")

    population = payload.get("population", {})
    if population.get("sample_size_per_mode") != 8:
        failures.append("sample_size_per_mode must equal 8")
    if population.get("sealed_populations_opened") is not False:
        failures.append("sealed_populations_opened must be false")
    if population.get("raw_bodies_published") is not False:
        failures.append("raw_bodies_published must be false")

    forbidden = find_forbidden_keys(payload)
    if forbidden:
        failures.append(f"forbidden raw or per-case fields: {', '.join(forbidden)}")

    modes = payload.get("modes", {})
    if set(modes) != MODE_IDS:
        failures.append("mode inventory differs from the frozen three-mode tournament")
        return {"status": "failed", "failures": failures}

    for mode_id, mode in modes.items():
        if mode.get("runtime_passed") != 8 or mode.get("contracts_passed") != 8:
            failures.append(f"{mode_id} did not preserve 8/8 runtime and contract passes")

    baseline = modes["baseline_context_concurrency_2"]
    local = modes["local_context_concurrency_4"]
    hybrid = modes["hybrid_context_concurrency_4"]
    comparisons = payload.get("comparisons", {})
    local_comparison = comparisons.get("local4_vs_baseline", {})
    hybrid_comparison = comparisons.get("hybrid4_vs_baseline", {})

    recomputed = {
        "local4_vs_baseline": {
            "aggregate_speedup": rounded(
                decimal(baseline["duration_total_ms"]) / decimal(local["duration_total_ms"]),
                "0.0001",
            ),
            "p50_reduction_percent": rounded(
                (Decimal(1) - decimal(local["duration_p50_ms"]) / decimal(baseline["duration_p50_ms"]))
                * Decimal(100),
                "0.01",
            ),
            "model_call_delta": local["model_calls"] - baseline["model_calls"],
            "prompt_token_delta": local["prompt_tokens"] - baseline["prompt_tokens"],
            "completion_token_delta": local["completion_tokens"] - baseline["completion_tokens"],
        },
        "hybrid4_vs_baseline": {
            "aggregate_speedup": rounded(
                decimal(baseline["duration_total_ms"]) / decimal(hybrid["duration_total_ms"]),
                "0.0001",
            ),
            "p50_reduction_percent": rounded(
                (Decimal(1) - decimal(hybrid["duration_p50_ms"]) / decimal(baseline["duration_p50_ms"]))
                * Decimal(100),
                "0.01",
            ),
            "successful_radeon_calls": (
                hybrid["provider_calls"]["radeon-vllm"]
                - hybrid["failed_provider_calls"]["radeon-vllm"]
            ),
            "failed_radeon_calls_recovered": hybrid["failed_provider_calls"]["radeon-vllm"],
        },
    }

    for comparison_id, expected_values in recomputed.items():
        published = comparisons.get(comparison_id, {})
        for key, expected in expected_values.items():
            actual = published.get(key)
            if isinstance(expected, Decimal):
                matches = actual is not None and decimal(actual) == expected
            else:
                matches = actual == expected
            if not matches:
                failures.append(
                    f"{comparison_id}.{key}: published={actual!r}, recomputed={str(expected)!r}"
                )

    if payload.get("decision", {}).get("interactive_default") != "local_context_concurrency_4":
        failures.append("interactive_default must remain the measured local four-worker mode")

    return {
        "schema_version": "signalforge/public-latency-tournament-verification/v1",
        "status": "passed" if not failures else "failed",
        "failures": failures,
        "recomputed": {
            comparison: {key: str(value) for key, value in values.items()}
            for comparison, values in recomputed.items()
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    args = parser.parse_args()
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    report = verify(payload)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
