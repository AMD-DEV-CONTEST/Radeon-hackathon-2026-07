#!/usr/bin/env python3
"""Summarize a SignalForge model benchmark without discarding raw observations."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import defaultdict
from datetime import datetime
from pathlib import Path


def percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def metrics(observations: list[dict]) -> dict:
    successful = [item for item in observations if item["row"]["success"]]

    def runtime_values(name: str) -> list[float]:
        return [
            float(item["row"].get("runtime", {}).get(name, 0))
            for item in observations
            if float(item["row"].get("runtime", {}).get(name, 0)) > 0
        ]

    durations = [float(item["row"]["duration_ms"]) for item in observations]
    ttft = runtime_values("ttft_ms")
    itl = runtime_values("inter_token_latency_ms")
    throughput = runtime_values("decode_tokens_per_second")
    return {
        "observations": len(observations),
        "successful": len(successful),
        "success_rate": len(successful) / len(observations) if observations else 0,
        "duration_ms_p50": percentile(durations, 0.50),
        "duration_ms_p95": percentile(durations, 0.95),
        "ttft_ms_p50": percentile(ttft, 0.50),
        "ttft_ms_p95": percentile(ttft, 0.95),
        "inter_token_latency_ms_p50": percentile(itl, 0.50),
        "inter_token_latency_ms_p95": percentile(itl, 0.95),
        "decode_tokens_per_second_p50": percentile(throughput, 0.50),
        "decode_tokens_per_second_p95": percentile(throughput, 0.95),
    }


def summarize(path: Path) -> dict:
    payload = path.read_bytes()
    report = json.loads(payload)
    groups: dict[str, list[dict]] = defaultdict(list)
    for item in report["observations"]:
        groups[item["row"]["workload_class"]].append(item)
    started_at = datetime.fromisoformat(report["started_at"].replace("Z", "+00:00"))
    completed_at = datetime.fromisoformat(report["completed_at"].replace("Z", "+00:00"))
    elapsed_seconds = max((completed_at - started_at).total_seconds(), 0.0)
    prompt_tokens = sum(
        float(item["row"].get("runtime", {}).get("prompt_tokens", 0))
        for item in report["observations"]
    )
    completion_tokens = sum(
        float(item["row"].get("runtime", {}).get("completion_tokens", 0))
        for item in report["observations"]
    )
    return {
        "schema_version": "signalforge/model-benchmark-summary/v1",
        "source_report": str(path),
        "source_sha256": hashlib.sha256(payload).hexdigest(),
        "run_id": report["run_id"],
        "benchmark_id": report["benchmark_id"],
        "model_id": report["model_id"],
        "cases_sha256": report["cases_sha256"],
        "repetitions": report["repetitions"],
        "warmup_repetitions": report.get("warmup_repetitions", 0),
        "concurrency": report.get("concurrency", 1),
        "quality_scope": "Deterministic contract checks only; human or independent model review remains required.",
        "aggregate": {
            "measured_wall_seconds": elapsed_seconds,
            "requests_per_second": len(report["observations"]) / elapsed_seconds if elapsed_seconds else 0,
            "prompt_tokens_per_wall_second": prompt_tokens / elapsed_seconds if elapsed_seconds else 0,
            "completion_tokens_per_wall_second": completion_tokens / elapsed_seconds if elapsed_seconds else 0,
        },
        "overall": metrics(report["observations"]),
        "by_workload": {name: metrics(items) for name, items in sorted(groups.items())},
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = summarize(args.report)
    encoded = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")


if __name__ == "__main__":
    main()
