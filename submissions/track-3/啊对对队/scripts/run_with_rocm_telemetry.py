#!/usr/bin/env python3
"""Run a command while recording Radeon power, utilization, and VRAM."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess

from parcel_sorter.rocm_telemetry import RocmTelemetryRecorder


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--interval-seconds", type=float, default=1.0)
    parser.add_argument("--gpu-id", default="card0")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        parser.error("a command is required after --")

    args.output.mkdir(parents=True, exist_ok=True)
    raw_path = args.output / "rocm-telemetry.jsonl"
    with RocmTelemetryRecorder(
        raw_path,
        interval_seconds=args.interval_seconds,
        gpu_id=args.gpu_id,
    ) as recorder:
        completed = subprocess.run(command)
    summary = recorder.summary()
    summary["command"] = command
    summary["command_returncode"] = completed.returncode
    summary_path = args.output / "rocm-telemetry-summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, sort_keys=True))
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
