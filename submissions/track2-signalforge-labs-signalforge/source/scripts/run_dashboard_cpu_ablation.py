#!/usr/bin/env python3
"""Measure the CPU overhead of the observational execution dashboard on Linux."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import resource
import statistics
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "signalforge/dashboard-cpu-ablation/v1"
DEFAULT_THRESHOLD_PERCENT = 1.0


def process_ticks(pid: int, proc_root: Path = Path("/proc")) -> int:
    payload = (proc_root / str(pid) / "stat").read_text(encoding="utf-8")
    closing = payload.rfind(")")
    if closing < 0:
        raise ValueError(f"invalid process stat for PID {pid}")
    fields = payload[closing + 2 :].split()
    if len(fields) < 13:
        raise ValueError(f"incomplete process stat for PID {pid}")
    return int(fields[11]) + int(fields[12])


def child_cpu_seconds() -> float:
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    return usage.ru_utime + usage.ru_stime


def canonical_answer_hash(report: dict[str, Any], run_id: str, request_id: str) -> str:
    answer = report.get("result", {}).get("answer")
    if not isinstance(answer, dict):
        raise ValueError("completed report has no answer")

    def normalize(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: normalize(item) for key, item in sorted(value.items())}
        if isinstance(value, list):
            return [normalize(item) for item in value]
        if isinstance(value, str):
            return value.replace(run_id, "<run-id>").replace(request_id, "<request-id>")
        return value

    payload = json.dumps(normalize(answer), separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def run_sample(
    command: list[str],
    model_pid: int,
    clock_ticks: int,
    condition: str,
    pair: int,
    directory: Path,
    max_attempts: int,
) -> dict[str, Any]:
    excluded_attempts: list[dict[str, Any]] = []
    for attempt in range(1, max_attempts + 1):
        run_id = f"dashboard-cpu-{condition}-{pair:02d}-attempt-{attempt:02d}"
        request_id = f"dashboard-request-{condition}-{pair:02d}-attempt-{attempt:02d}"
        report_path = directory / f"{condition}-{pair:02d}-attempt-{attempt:02d}-report.json"
        plan_path = directory / f"{condition}-{pair:02d}-attempt-{attempt:02d}-plan.json"
        invocation = [
            *command,
            "--run-id",
            run_id,
            "--request-id",
            request_id,
            "--format",
            "json",
            "--output",
            str(report_path),
        ]
        if condition == "dashboard":
            invocation.extend(["--execution-plan-output", str(plan_path)])

        model_before = process_ticks(model_pid)
        child_before = child_cpu_seconds()
        wall_started = time.perf_counter()
        completed = subprocess.run(invocation, check=False, capture_output=True, text=True)
        wall_seconds = time.perf_counter() - wall_started
        child_seconds = child_cpu_seconds() - child_before
        model_seconds = (process_ticks(model_pid) - model_before) / clock_ticks
        stderr_hash = hashlib.sha256(completed.stderr.encode()).hexdigest()
        if completed.returncode != 0:
            excluded_attempts.append(
                {
                    "attempt": attempt,
                    "exit_code": completed.returncode,
                    "stderr_sha256": stderr_hash,
                }
            )
            continue

        report = json.loads(report_path.read_text(encoding="utf-8"))
        if report.get("result", {}).get("failure") is not None:
            excluded_attempts.append(
                {
                    "attempt": attempt,
                    "exit_code": completed.returncode,
                    "stderr_sha256": stderr_hash,
                    "governed_failure": True,
                }
            )
            continue
        plan_sha = None
        if condition == "dashboard":
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            if plan.get("status") != "passed" or plan.get("progress_ratio") != 1:
                excluded_attempts.append(
                    {
                        "attempt": attempt,
                        "exit_code": completed.returncode,
                        "stderr_sha256": stderr_hash,
                        "invalid_execution_plan": True,
                    }
                )
                continue
            plan_sha = sha256_file(plan_path)

        metrics = report.get("metrics", {})
        return {
            "condition": condition,
            "pair": pair,
            "accepted_attempt": attempt,
            "excluded_attempts": excluded_attempts,
            "wall_seconds": round(wall_seconds, 6),
            "orchestrator_cpu_seconds": round(child_seconds, 6),
            "model_cpu_seconds": round(model_seconds, 6),
            "complete_journey_cpu_seconds": round(child_seconds + model_seconds, 6),
            "model_calls": metrics.get("model_calls"),
            "prompt_tokens": metrics.get("prompt_tokens"),
            "completion_tokens": metrics.get("completion_tokens"),
            "report_sha256": sha256_file(report_path),
            "answer_sha256": canonical_answer_hash(report, run_id, request_id),
            "execution_plan_sha256": plan_sha,
        }
    raise RuntimeError(
        f"{condition} pair {pair} produced no accepted journey after {max_attempts} attempts"
    )


def summarize(samples: list[dict[str, Any]], threshold_percent: float) -> dict[str, Any]:
    baseline = {sample["pair"]: sample for sample in samples if sample["condition"] == "baseline"}
    dashboard = {sample["pair"]: sample for sample in samples if sample["condition"] == "dashboard"}
    if baseline.keys() != dashboard.keys() or not baseline:
        raise ValueError("every pair requires one baseline and one dashboard sample")
    paired_overheads = []
    for pair in sorted(baseline):
        base_cpu = baseline[pair]["complete_journey_cpu_seconds"]
        dashboard_cpu = dashboard[pair]["complete_journey_cpu_seconds"]
        if base_cpu <= 0:
            raise ValueError(f"baseline CPU must be positive for pair {pair}")
        paired_overheads.append((dashboard_cpu - base_cpu) / base_cpu * 100)
    median_overhead = statistics.median(paired_overheads)
    return {
        "pairs": len(paired_overheads),
        "paired_overhead_percent": [round(value, 6) for value in paired_overheads],
        "median_overhead_percent": round(median_overhead, 6),
        "threshold_percent": threshold_percent,
        "status": "passed" if median_overhead < threshold_percent else "failed",
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-pid", type=int, required=True)
    parser.add_argument("--pairs", type=int, default=3)
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--threshold-percent", type=float, default=DEFAULT_THRESHOLD_PERCENT)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.command and args.command[0] == "--":
        args.command = args.command[1:]
    if not args.command:
        parser.error("a signalforge-run-golden command is required after --")
    if args.pairs < 3 or args.pairs > 12:
        parser.error("--pairs must be between 3 and 12")
    if args.max_attempts < 1 or args.max_attempts > 5:
        parser.error("--max-attempts must be between 1 and 5")
    if args.threshold_percent <= 0:
        parser.error("--threshold-percent must be positive")
    forbidden = {"--run-id", "--request-id", "--output", "--format", "--execution-plan-output"}
    if any(argument in forbidden for argument in args.command):
        parser.error("the base command must not override runner-owned output or identity flags")
    return args


def main() -> None:
    args = parse_args()
    if platform.system() != "Linux":
        raise SystemExit("dashboard CPU ablation requires Linux /proc accounting")
    clock_ticks = int(os.sysconf("SC_CLK_TCK"))
    process_ticks(args.model_pid)
    command_sha = hashlib.sha256(
        json.dumps(args.command, separators=(",", ":")).encode()
    ).hexdigest()
    samples: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="signalforge-dashboard-cpu-") as temporary:
        directory = Path(temporary)
        for pair in range(1, args.pairs + 1):
            order = ("baseline", "dashboard") if pair % 2 else ("dashboard", "baseline")
            for condition in order:
                samples.append(
                    run_sample(
                        args.command,
                        args.model_pid,
                        clock_ticks,
                        condition,
                        pair,
                        directory,
                        args.max_attempts,
                    )
                )
    summary = summarize(samples, args.threshold_percent)
    report = {
        "schema_version": SCHEMA_VERSION,
        "measured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "environment": {
            "os": platform.system().lower(),
            "architecture": platform.machine(),
            "hostname_sha256": hashlib.sha256(platform.node().encode()).hexdigest(),
            "clock_ticks_per_second": clock_ticks,
            "model_pid": args.model_pid,
            "command_sha256": command_sha,
            "runner_sha256": sha256_file(Path(__file__).resolve()),
            "workload_binary_sha256": sha256_file(Path(args.command[0]).resolve()),
        },
        "policy": {
            "measurement": "paired process CPU: orchestrator child plus local model server",
            "order": "alternating AB/BA",
            "protected_bodies_retained": False,
        },
        "samples": samples,
        "summary": summary,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.output.chmod(0o640)
    print(json.dumps(summary, sort_keys=True))
    if summary["status"] != "passed":
        raise SystemExit("dashboard CPU overhead exceeded the accepted threshold")


if __name__ == "__main__":
    main()
