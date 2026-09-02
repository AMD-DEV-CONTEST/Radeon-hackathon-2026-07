#!/usr/bin/env python3
"""Capture a hash-bound accepted Radeon workload CPU denominator for dashboard evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_dashboard_cpu_ablation import (
    child_cpu_seconds,
    process_ticks,
    run_sample,
    sha256_file,
)

SCHEMA_VERSION = "signalforge/dashboard-workload-cpu/v1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-pid", type=int, required=True)
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.command and args.command[0] == "--":
        args.command = args.command[1:]
    if not args.command:
        parser.error("a signalforge-run-golden command is required after --")
    if args.max_attempts < 1 or args.max_attempts > 5:
        parser.error("--max-attempts must be between 1 and 5")
    forbidden = {"--run-id", "--request-id", "--output", "--format", "--execution-plan-output"}
    if any(argument in forbidden for argument in args.command):
        parser.error("the base command must not override runner-owned output or identity flags")
    return args


def main() -> None:
    args = parse_args()
    if platform.system() != "Linux":
        raise SystemExit("dashboard workload CPU capture requires Linux /proc accounting")
    clock_ticks = int(os.sysconf("SC_CLK_TCK"))
    process_ticks(args.model_pid)
    child_cpu_seconds()
    with tempfile.TemporaryDirectory(prefix="signalforge-dashboard-workload-") as temporary:
        sample = run_sample(
            args.command,
            args.model_pid,
            clock_ticks,
            "dashboard",
            1,
            Path(temporary),
            args.max_attempts,
        )
    report = {
        "schema_version": SCHEMA_VERSION,
        "measured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "environment": {
            "os": platform.system().lower(),
            "architecture": platform.machine(),
            "hostname_sha256": hashlib.sha256(platform.node().encode()).hexdigest(),
            "clock_ticks_per_second": clock_ticks,
            "model_pid": args.model_pid,
            "command_sha256": hashlib.sha256(
                json.dumps(args.command, separators=(",", ":")).encode()
            ).hexdigest(),
            "capture_runner_sha256": sha256_file(Path(__file__).resolve()),
            "sample_runner_sha256": sha256_file(
                Path(__file__).with_name("run_dashboard_cpu_ablation.py").resolve()
            ),
            "workload_binary_sha256": sha256_file(Path(args.command[0]).resolve()),
        },
        "policy": {
            "measurement": "accepted complete-journey process CPU: orchestrator child plus local model server",
            "condition": "dashboard_enabled",
            "protected_bodies_retained": False,
            "failed_attempts_excluded_and_disclosed": True,
        },
        "sample": sample,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.output.chmod(0o640)
    print(
        json.dumps(
            {
                "accepted_attempt": sample["accepted_attempt"],
                "complete_journey_cpu_seconds": sample["complete_journey_cpu_seconds"],
                "model_calls": sample["model_calls"],
                "status": "captured",
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
