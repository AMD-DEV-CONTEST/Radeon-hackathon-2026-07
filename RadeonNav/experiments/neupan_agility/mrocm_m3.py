#!/usr/bin/env python3
"""Run a preregistered tire-phase sweep for the AMD long course."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "experiments/neupan_agility/run_radeon_nav.py"
DEFAULT_CHECKPOINT = (
    ROOT
    / "experiment-results/quadrupedal-agility/M-ROCM-6-HISTDATA/TRAIN"
    / "ft1_depth_encoder_epoch6.pt"
)
DEFAULT_OUTPUT = (
    ROOT / "experiment-results/quadrupedal-agility/M-ROCM-3"
)
DEFAULT_PHASES = ("t1", "t2", "t3", "t4")
KNOWN_PHASES = (
    *DEFAULT_PHASES,
    "t3m2",
    "t3m1",
    "t3p1",
    "t3p2",
)
REQUIRED_CHECKS = (
    "live_env_action_contract",
    "rollout_finite",
    "video_created",
    "no_fall_before_success",
    "no_pedestrian_collision",
    "reached_goal",
)
REQUIRED_MARKS = (
    "rough",
    "stairs",
    "seesaw",
    "turn1",
    "combo",
    "bar_avoid",
    "turn2",
    "tire",
    "poles",
)
EXPECTED_GATE_SIDES = {"gate0": "S", "gate1": "N", "gate2": "S", "gate3": "N"}
EXPECTED_TIRE_ASSET_SHA256 = (
    "c3dfad18b7b2a83f231919a0617dc12ec5236e5b4e7a55c6981ea130e8d2275d"
)
EXPECTED_HISTORICAL_RUNNER_SHA256 = (
    "88a25c3142e46e2d19080a09ed25b169eafd604c70a2d40eb50251a5e7fd0468"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def command_for(
    phase: str,
    checkpoint: Path,
    output_dir: Path,
    device: str,
    run_id: str,
) -> tuple[str, ...]:
    return (
        sys.executable,
        str(RUNNER),
        "--seed",
        "7",
        "--device",
        device,
        "--tire-phase",
        phase,
        "--no-video",
        "--depth-encoder-checkpoint",
        str(checkpoint),
        "--tag",
        f"{run_id.lower()}-{phase}",
        "--output-dir",
        str(output_dir),
    )


def run_phase(
    phase: str,
    checkpoint: Path,
    output_dir: Path,
    device: str,
    run_id: str,
    rerun: bool,
) -> tuple[str, str]:
    result_path = output_dir / "result.json"
    if result_path.is_file() and not rerun:
        payload = json.loads(result_path.read_text())
        if "error" not in payload:
            return phase, str(payload["status"])
    output_dir.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        command_for(phase, checkpoint, output_dir, device, run_id),
        cwd=ROOT,
        env=os.environ.copy(),
        text=True,
        capture_output=True,
        check=False,
    )
    if not result_path.is_file():
        raise RuntimeError(
            f"{phase} produced no result\n{completed.stdout}\n{completed.stderr}"
        )
    payload = json.loads(result_path.read_text())
    if "error" in payload:
        raise RuntimeError(f"{phase}: {payload['error']}")
    return phase, str(payload["status"])


def audit_payload(payload: dict) -> tuple[bool, list[str]]:
    failures = [
        f"check:{name}"
        for name in REQUIRED_CHECKS
        if not payload.get("checks", {}).get(name, False)
    ]
    marks = payload.get("metrics", {}).get("segment_marks", {})
    failures.extend(f"mark:{name}" for name in REQUIRED_MARKS if name not in marks)
    contracts = payload.get("contracts", {})
    if contracts.get("gate_sides") != EXPECTED_GATE_SIDES:
        failures.append("gate_sides")
    if contracts.get("dynamic_tire_static_layout_used") is not False:
        failures.append("dynamic_tire_static_layout_used")
    if contracts.get("tire_asset_sha256") != EXPECTED_TIRE_ASSET_SHA256:
        failures.append("tire_asset_sha256")
    if (
        contracts.get("historical_official_runner_sha256")
        != EXPECTED_HISTORICAL_RUNNER_SHA256
    ):
        failures.append("historical_runner_reference")
    if payload.get("device_name") != "AMD Radeon Graphics":
        failures.append("device_name")
    if payload.get("torch_hip_version") is None:
        failures.append("torch_hip_version")
    return not failures, failures


def summarize(args: argparse.Namespace) -> dict:
    rows = []
    eligible = []
    for phase in args.phases:
        result_path = args.output_dir / "SWEEP" / phase / "result.json"
        payload = json.loads(result_path.read_text())
        passed, failures = audit_payload(payload)
        forbidden = int(
            payload.get("metrics", {}).get("forbidden_contact_step_count", 0)
        )
        row = {
            "phase": phase,
            "runner_status": payload.get("status"),
            "mrocm3_gate_passed": passed,
            "gate_failures": failures,
            "reached_step": payload.get("metrics", {}).get("reached_step"),
            "segment_marks": payload.get("metrics", {}).get("segment_marks", {}),
            "gate_sides": payload.get("contracts", {}).get("gate_sides", {}),
            "forbidden_contact_step_count": forbidden,
            "result": str(result_path.relative_to(ROOT)),
        }
        rows.append(row)
        if passed:
            eligible.append((forbidden, args.phases.index(phase), phase))
    selected = min(eligible)[2] if eligible else None
    summary = {
        "run_id": args.run_id,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "status": "PASSED" if selected is not None else "FAILED",
        "authorization": (
            "user explicitly requested continuation after disclosed M-ROCM-2 failure"
        ),
        "scope": args.scope,
        "checkpoint": str(args.checkpoint),
        "checkpoint_sha256": sha256(args.checkpoint),
        "runner": str(RUNNER.relative_to(ROOT)),
        "runner_sha256": sha256(RUNNER),
        "historical_official_runner_sha256": EXPECTED_HISTORICAL_RUNNER_SHA256,
        "tire_asset": "experiments/neupan_agility/assets/tire_jump.xml",
        "tire_asset_sha256": EXPECTED_TIRE_ASSET_SHA256,
        "dynamic_tire_static_layout_used": False,
        "selection_rule": (
            "among strict passes, minimize forbidden-contact steps; "
            "tie-break by preregistered phase order"
        ),
        "phase_order": list(args.phases),
        "selected_phase": selected,
        "phases": rows,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "result.json").write_text(
        json.dumps(summary, indent=2) + "\n"
    )
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--run-id", default="M-ROCM-3")
    parser.add_argument(
        "--scope",
        default="AMD long-course replay plus four archived tire phase variants",
    )
    parser.add_argument(
        "--phases",
        nargs="+",
        choices=KNOWN_PHASES,
        default=list(DEFAULT_PHASES),
    )
    parser.add_argument("--rerun", action="store_true")
    args = parser.parse_args()
    args.checkpoint = args.checkpoint.resolve()
    args.output_dir = args.output_dir.resolve()
    if not args.checkpoint.is_file():
        parser.error(f"missing checkpoint: {args.checkpoint}")
    if args.jobs < 1:
        parser.error("--jobs must be positive")
    return args


def main() -> int:
    args = parse_args()
    failures = []
    complete = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as executor:
        futures = {
            executor.submit(
                run_phase,
                phase,
                args.checkpoint,
                args.output_dir / "SWEEP" / phase,
                args.device,
                args.run_id,
                args.rerun,
            ): phase
            for phase in args.phases
        }
        for future in concurrent.futures.as_completed(futures):
            phase = futures[future]
            try:
                name, status = future.result()
            except Exception as exc:
                failures.append(phase)
                print(f"TECHNICAL_FAILURE {exc}", flush=True)
                continue
            complete += 1
            print(
                f"RESULT {name} runner_status={status} "
                f"progress={complete}/{len(args.phases)}",
                flush=True,
            )
    if failures:
        print("FAILED_PHASES " + " ".join(sorted(failures)), flush=True)
        return 1
    summary = summarize(args)
    print(
        f"VERDICT {summary['status']} selected_phase={summary['selected_phase']}",
        flush=True,
    )
    return 0 if summary["status"] == "PASSED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
