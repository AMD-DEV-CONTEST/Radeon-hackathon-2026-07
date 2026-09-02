#!/usr/bin/env python3
"""Build or verify the publishable dashboard CPU-overhead evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import statistics
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "signalforge/dashboard-cpu-evidence/v1"
WORKLOAD_SCHEMA = "signalforge/dashboard-workload-cpu/v1"
THRESHOLD_PERCENT = 1.0
BENCHMARK_PATTERN = re.compile(
    r"BenchmarkExecutionDashboardCPUOverhead/(baseline|dashboard)-\d+\s+\d+\s+(\d+)\s+ns/op"
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_benchmark(path: Path) -> dict[str, list[int]]:
    values: dict[str, list[int]] = {"baseline": [], "dashboard": []}
    for condition, nanoseconds in BENCHMARK_PATTERN.findall(path.read_text(encoding="utf-8")):
        values[condition].append(int(nanoseconds))
    if len(values["baseline"]) < 3 or len(values["dashboard"]) < 3:
        raise ValueError("benchmark requires at least three baseline and dashboard observations")
    return values


def build_report(benchmark_path: Path, workload_path: Path) -> dict[str, Any]:
    values = parse_benchmark(benchmark_path)
    workload = json.loads(workload_path.read_text(encoding="utf-8"))
    if workload.get("schema_version") != WORKLOAD_SCHEMA:
        raise ValueError("unexpected workload schema")
    if workload.get("policy", {}).get("protected_bodies_retained") is not False:
        raise ValueError("workload evidence must not retain protected bodies")
    sample = workload.get("sample")
    if not isinstance(sample, dict) or sample.get("condition") != "dashboard":
        raise ValueError("workload evidence requires one dashboard sample")
    complete_cpu = sample.get("complete_journey_cpu_seconds")
    if not isinstance(complete_cpu, (int, float)) or complete_cpu <= 0:
        raise ValueError("complete journey CPU must be positive")
    if not isinstance(sample.get("accepted_attempt"), int):
        raise ValueError("accepted workload attempt is missing")

    baseline_median = statistics.median(values["baseline"])
    dashboard_median = statistics.median(values["dashboard"])
    incremental = dashboard_median - baseline_median
    if incremental <= 0:
        raise ValueError("dashboard benchmark must produce a positive incremental cost")
    overhead = incremental / 1_000_000_000 / complete_cpu * 100
    status = "passed" if overhead < THRESHOLD_PERCENT else "failed"
    return {
        "schema_version": SCHEMA_VERSION,
        "decision": {
            "status": status,
            "threshold_percent": THRESHOLD_PERCENT,
            "measured_upper_bound_percent": round(overhead, 9),
            "method": "median incremental projection ns/op divided by accepted complete-journey CPU",
        },
        "projection_benchmark": {
            "baseline_observations": len(values["baseline"]),
            "dashboard_observations": len(values["dashboard"]),
            "baseline_median_ns_per_op": baseline_median,
            "dashboard_median_ns_per_op": dashboard_median,
            "incremental_median_ns_per_op": incremental,
            "raw_benchmark_sha256": sha256_file(benchmark_path),
        },
        "accepted_radeon_workload": {
            "complete_journey_cpu_seconds": complete_cpu,
            "accepted_attempt": sample["accepted_attempt"],
            "excluded_attempts": len(sample.get("excluded_attempts", [])),
            "model_calls": sample.get("model_calls"),
            "prompt_tokens": sample.get("prompt_tokens"),
            "completion_tokens": sample.get("completion_tokens"),
            "workload_evidence_sha256": sha256_file(workload_path),
        },
        "boundaries": {
            "protected_bodies_retained": False,
            "raw_ab_pairing_used_for_decision": False,
            "model_generation_variance_removed_from_incremental_numerator": True,
            "claim": "execution-plan projection and event handling CPU overhead only",
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--benchmark", type=Path, required=True)
    parser.add_argument("--workload", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    report = build_report(args.benchmark, args.workload)
    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.check:
        if args.output.read_text(encoding="utf-8") != payload:
            raise SystemExit("dashboard CPU evidence is stale")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(json.dumps(report["decision"], sort_keys=True))
    if report["decision"]["status"] != "passed":
        raise SystemExit("dashboard CPU overhead is not below one percent")


if __name__ == "__main__":
    main()
