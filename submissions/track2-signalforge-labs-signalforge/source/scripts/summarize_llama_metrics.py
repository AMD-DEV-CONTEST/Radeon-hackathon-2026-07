#!/usr/bin/env python3
"""Summarize llama.cpp Prometheus counter deltas for one measured workload."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def parse_metrics(path: Path) -> dict[str, float]:
    values: dict[str, float] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) != 2 or not parts[0].startswith("llamacpp:"):
            continue
        try:
            values[parts[0]] = float(parts[1])
        except ValueError:
            continue
    return values


def summarize(before_path: Path, after_path: Path) -> dict:
    before = parse_metrics(before_path)
    after = parse_metrics(after_path)

    def delta(name: str) -> float:
        return max(after.get(name, 0.0) - before.get(name, 0.0), 0.0)

    prompt_tokens = delta("llamacpp:prompt_tokens_total")
    prompt_seconds = delta("llamacpp:prompt_seconds_total")
    predicted_tokens = delta("llamacpp:tokens_predicted_total")
    predicted_seconds = delta("llamacpp:tokens_predicted_seconds_total")
    return {
        "schema_version": "signalforge/llama-native-metrics/v1",
        "before": str(before_path),
        "after": str(after_path),
        "deltas": {
            "prompt_tokens": prompt_tokens,
            "prompt_seconds": prompt_seconds,
            "predicted_tokens": predicted_tokens,
            "predicted_seconds": predicted_seconds,
            "decode_calls": delta("llamacpp:n_decode_total"),
        },
        "throughput": {
            "prompt_tokens_per_second": prompt_tokens / prompt_seconds if prompt_seconds else 0,
            "predicted_tokens_per_second": predicted_tokens / predicted_seconds if predicted_seconds else 0,
        },
        "final_gauges": {
            name.removeprefix("llamacpp:"): value
            for name, value in sorted(after.items())
            if name in {
                "llamacpp:n_busy_slots_per_decode",
                "llamacpp:n_tokens_max",
                "llamacpp:requests_deferred",
                "llamacpp:requests_processing",
            }
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("before", type=Path)
    parser.add_argument("after", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = summarize(args.before, args.after)
    encoded = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")


if __name__ == "__main__":
    main()
