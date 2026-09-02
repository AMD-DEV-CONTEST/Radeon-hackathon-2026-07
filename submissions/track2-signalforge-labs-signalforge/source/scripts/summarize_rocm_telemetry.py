#!/usr/bin/env python3
"""Summarize JSONL telemetry captured by capture_rocm_telemetry.py."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter
from pathlib import Path


METRICS = (
    "cgroup_memory_current_bytes",
    "process_tree_rss_bytes",
    "process_tree_count",
    "gfx_activity_percent",
    "memory_activity_percent",
    "socket_power_watts",
    "temperature_edge_celsius",
    "temperature_hotspot_celsius",
    "temperature_memory_celsius",
    "vram_used_mb",
)


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def summarize(path: Path) -> dict:
    samples = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not samples:
        raise ValueError("telemetry input contains no samples")
    metrics: dict[str, dict[str, float | None]] = {}
    for name in METRICS:
        values = [float(sample[name]) for sample in samples if isinstance(sample.get(name), (int, float))]
        metrics[name] = {
            "observations": len(values),
            "p50": percentile(values, 0.50),
            "p95": percentile(values, 0.95),
            "maximum": max(values) if values else None,
        }
    statuses = Counter(str(sample["throttle_status"]) for sample in samples if sample.get("throttle_status") is not None)
    duration = float(samples[-1].get("monotonic_seconds", 0)) - float(samples[0].get("monotonic_seconds", 0))
    return {
        "schema_version": "signalforge/rocm-telemetry-summary/v1",
        "source": str(path),
        "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "sample_count": len(samples),
        "sampled_duration_seconds": max(duration, 0),
        "first_observed_at": samples[0].get("observed_at"),
        "last_observed_at": samples[-1].get("observed_at"),
        "metrics": metrics,
        "throttle_status_counts": dict(sorted(statuses.items())),
        "interpretation_note": (
            "Throttle labels are reported verbatim by amd-smi and must be interpreted with "
            "temperature, power, clocks, and platform policy rather than alone."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("telemetry", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = summarize(args.telemetry)
    encoded = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")


if __name__ == "__main__":
    main()
