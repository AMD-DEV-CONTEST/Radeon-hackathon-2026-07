#!/usr/bin/env python3
"""Replay the frozen FT2-FINAL 30-run gate with the selected ROCm encoder."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import subprocess
import sys
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE_RUNNER = ROOT / "experiments/neupan_agility/run_source_task.py"
PLANNER_RUNNER = ROOT / "experiments/neupan_agility/run_static_2p5d.py"
TASKS = ("bar_jump", "frame", "seesaw", "tire_jump")
GRID_TASKS = ("frame", "seesaw", "tire_jump")
GRID_POINTS = (
    (0.60, 7),
    (0.95, 17),
    (1.00, 7),
    (1.30, 27),
    (1.65, 37),
    (2.00, 47),
)
COMMON_REQUIRED_CHECKS = (
    "live_env_action_contract",
    "policy_io_contract",
    "rollout_finite",
    "step_count",
    "video_created",
    "no_early_termination_before_success",
)


@dataclass(frozen=True)
class Gate:
    name: str
    command: tuple[str, ...]
    output_dir: Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def source_command(
    task: str,
    seed: int,
    friction: float,
    yaw_source: str,
    onehot_source: str,
    checkpoint: Path,
    output_dir: Path,
    device: str,
) -> tuple[str, ...]:
    return (
        sys.executable,
        str(SOURCE_RUNNER),
        "--task",
        task,
        "--seed",
        str(seed),
        "--friction",
        str(friction),
        "--high-branch",
        "student",
        "--precision",
        "float16",
        "--yaw-source",
        yaw_source,
        "--onehot-source",
        onehot_source,
        "--device",
        device,
        "--depth-encoder-checkpoint",
        str(checkpoint),
        "--output-dir",
        str(output_dir),
    )


def planner_command(
    scenario: str,
    jump_feed: str,
    checkpoint: Path,
    output_dir: Path,
    device: str,
) -> tuple[str, ...]:
    return (
        sys.executable,
        str(PLANNER_RUNNER),
        "--scenario",
        scenario,
        "--jump-feed",
        jump_feed,
        "--seed",
        "7",
        "--device",
        device,
        "--depth-encoder-checkpoint",
        str(checkpoint),
        "--output-dir",
        str(output_dir),
    )


def build_gates(
    checkpoint: Path, output_dir: Path, device: str
) -> list[Gate]:
    gates: list[Gate] = []
    for task in GRID_TASKS:
        for friction, seed in GRID_POINTS:
            name = f"grid_{task}_mu{friction:.2f}"
            run_dir = output_dir / name
            gates.append(
                Gate(
                    name,
                    source_command(
                        task,
                        seed,
                        friction,
                        "waypoint",
                        "gt",
                        checkpoint,
                        run_dir,
                        device,
                    ),
                    run_dir,
                )
            )
    for cell, yaw_source in (("cellA", "depth"), ("cellB", "waypoint")):
        for task in TASKS:
            name = f"{cell}_{task}"
            run_dir = output_dir / name
            gates.append(
                Gate(
                    name,
                    source_command(
                        task,
                        7,
                        1.0,
                        yaw_source,
                        "depth",
                        checkpoint,
                        run_dir,
                        device,
                    ),
                    run_dir,
                )
            )
    for name, scenario, jump_feed in (
        ("p401_DW", "DW", "default"),
        ("p401_TF", "TF", "default"),
        ("p401_TS", "TS", "default"),
        ("p402_TRCM", "TR", "commit"),
    ):
        run_dir = output_dir / name
        gates.append(
            Gate(
                name,
                planner_command(
                    scenario, jump_feed, checkpoint, run_dir, device
                ),
                run_dir,
            )
        )
    if len(gates) != 30:
        raise AssertionError(f"expected 30 gates, built {len(gates)}")
    return gates


def run_gate(gate: Gate) -> tuple[str, str, float]:
    result_path = gate.output_dir / "result.json"
    if result_path.is_file():
        payload = json.loads(result_path.read_text())
        if "error" not in payload:
            return gate.name, str(payload["status"]), 0.0
    gate.output_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.setdefault("MUJOCO_GL", "egl")
    started = time.monotonic()
    completed = subprocess.run(
        gate.command,
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    elapsed = time.monotonic() - started
    if not result_path.is_file():
        details = "\n".join(
            part for part in (completed.stdout.strip(), completed.stderr.strip()) if part
        )
        raise RuntimeError(
            f"{gate.name} produced no result after {elapsed:.1f}s\n{details}"
        )
    payload = json.loads(result_path.read_text())
    if "error" in payload:
        raise RuntimeError(f"{gate.name}: {payload['error']}")
    return gate.name, str(payload["status"]), elapsed


def summarize(
    gates: list[Gate],
    checkpoint: Path,
    baseline_dir: Path,
    output_dir: Path,
) -> dict:
    outcomes = {}
    regressions = []
    improvements = []
    contract_failures = []
    for gate in gates:
        current = json.loads((gate.output_dir / "result.json").read_text())
        baseline_path = baseline_dir / gate.name / "result.json"
        if not baseline_path.is_file():
            raise FileNotFoundError(baseline_path)
        baseline = json.loads(baseline_path.read_text())
        current_status = str(current["status"])
        baseline_status = str(baseline["status"])
        if baseline_status == "PASSED" and current_status != "PASSED":
            regressions.append(gate.name)
        if baseline_status != "PASSED" and current_status == "PASSED":
            improvements.append(gate.name)
        failed_common = [
            check
            for check in COMMON_REQUIRED_CHECKS
            if not current.get("checks", {}).get(check, False)
        ]
        if failed_common:
            contract_failures.append(
                {"gate": gate.name, "failed_checks": failed_common}
            )
        outcomes[gate.name] = {
            "baseline_status": baseline_status,
            "rocm_status": current_status,
            "device_name": current.get("device_name"),
            "forbidden_steps": len(
                current.get("metrics", {}).get(
                    "forbidden_contact_before_success_steps", []
                )
            ),
        }
    baseline_counts = Counter(
        item["baseline_status"] for item in outcomes.values()
    )
    rocm_counts = Counter(item["rocm_status"] for item in outcomes.values())
    summary = {
        "run_id": "M-ROCM-2",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "status": (
            "PASSED" if not regressions and not contract_failures else "FAILED"
        ),
        "checkpoint": str(checkpoint),
        "checkpoint_sha256": sha256(checkpoint),
        "gate_count": len(gates),
        "baseline_counts": dict(baseline_counts),
        "rocm_counts": dict(rocm_counts),
        "regressions": regressions,
        "improvements": improvements,
        "contract_failures": contract_failures,
        "outcomes": outcomes,
    }
    (output_dir.parent / "result.json").write_text(
        json.dumps(summary, indent=2) + "\n"
    )
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--baseline-dir", type=Path, required=True)
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--device", default="cuda")
    args = parser.parse_args()
    args.checkpoint = args.checkpoint.resolve()
    if not args.checkpoint.is_file():
        parser.error(f"missing checkpoint: {args.checkpoint}")
    if not args.baseline_dir.is_dir():
        parser.error(f"missing baseline directory: {args.baseline_dir}")
    if args.jobs < 1:
        parser.error("--jobs must be positive")
    return args


def main() -> int:
    args = parse_args()
    gates = build_gates(args.checkpoint, args.output_dir, args.device)
    failures = []
    complete = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as executor:
        futures = {executor.submit(run_gate, gate): gate for gate in gates}
        for future in concurrent.futures.as_completed(futures):
            gate = futures[future]
            try:
                name, status, elapsed = future.result()
            except Exception as exc:  # preserve the other frozen gate results
                failures.append(gate.name)
                print(f"TECHNICAL_FAILURE {exc}", flush=True)
                continue
            complete += 1
            print(
                f"RESULT {name} status={status} elapsed={elapsed:.1f}s "
                f"progress={complete}/30",
                flush=True,
            )
    if failures:
        print("FAILED_GATES " + " ".join(sorted(failures)), flush=True)
        return 1
    summary = summarize(
        gates, args.checkpoint, args.baseline_dir, args.output_dir
    )
    print(
        f"VERDICT {summary['status']} regressions={len(summary['regressions'])} "
        f"improvements={len(summary['improvements'])}",
        flush=True,
    )
    return 0 if summary["status"] == "PASSED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
