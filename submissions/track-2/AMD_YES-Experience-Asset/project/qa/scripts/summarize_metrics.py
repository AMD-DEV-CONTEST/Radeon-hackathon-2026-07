#!/usr/bin/env python3
"""Summarize retained JSONL run records without applying private thresholds."""

from __future__ import annotations

import argparse
import json
import math
import pathlib
import statistics
import sys

METRICS = (
    "ttft_ms",
    "e2e_latency_ms",
    "output_tps",
    "peak_vram_mib",
    "model_call_count",
    "question_rounds",
    "time_to_first_artifact_ms",
)
SCENARIOS = {"interactive", "background", "stress"}


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    rank = max(1, math.ceil(fraction * len(ordered)))
    return ordered[rank - 1]


def summarize(records: list[dict]) -> dict:
    if not records:
        raise ValueError("no records")
    scenarios = {record.get("scenario_type") for record in records}
    if len(scenarios) != 1 or not scenarios.issubset(SCENARIOS):
        raise ValueError("each summary must contain exactly one valid scenario_type")
    for index, record in enumerate(records):
        if not isinstance(record.get("success"), bool) or not record.get("run_id") or not record.get("terminal_state"):
            raise ValueError(f"record {index} lacks run_id/success/terminal_state")
    success_count = sum(record["success"] for record in records)
    result = {
        "scenario_type": next(iter(scenarios)),
        "sample_size": len(records),
        "success_count": success_count,
        "failure_count": len(records) - success_count,
        "failure_rate": (len(records) - success_count) / len(records),
        "metrics": {},
    }
    for name in METRICS:
        values = [float(record[name]) for record in records if isinstance(record.get(name), (int, float)) and not isinstance(record.get(name), bool)]
        if values:
            result["metrics"][name] = {
                "n": len(values),
                "mean": statistics.fmean(values),
                "median": statistics.median(values),
                "p95": percentile(values, 0.95),
                "min": min(values),
                "max": max(values),
            }
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("records", help="one JSON object per line")
    parser.add_argument("--output")
    args = parser.parse_args()
    try:
        rows = [json.loads(line) for line in pathlib.Path(args.records).read_text(encoding="utf-8").splitlines() if line.strip()]
        result = summarize(rows)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"FAIL AC-20/21/28: {exc}", file=sys.stderr)
        return 1
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        pathlib.Path(args.output).write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
