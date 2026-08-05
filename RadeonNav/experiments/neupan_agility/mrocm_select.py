#!/usr/bin/env python3
"""Run and score the frozen six-probe set for every Phase-B epoch."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE_RUNNER = ROOT / "experiments/neupan_agility/run_source_task.py"
PLANNER_RUNNER = ROOT / "experiments/neupan_agility/run_static_2p5d.py"


@dataclass(frozen=True)
class Probe:
    epoch: int
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
        "waypoint",
        "--onehot-source",
        "gt",
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


def build_probes(
    train_dir: Path, output_dir: Path, device: str
) -> tuple[list[Probe], dict[int, Path]]:
    probes: list[Probe] = []
    checkpoints: dict[int, Path] = {}
    for epoch in range(1, 7):
        checkpoint = (
            train_dir / f"ft1_depth_encoder_epoch{epoch}.pt"
        ).resolve()
        if not checkpoint.is_file():
            raise FileNotFoundError(checkpoint)
        checkpoints[epoch] = checkpoint
        epoch_dir = output_dir / f"ep{epoch}"
        specs = (
            (
                "frame130",
                source_command,
                ("frame", 27, 1.30, checkpoint, epoch_dir / "frame130", device),
            ),
            (
                "tire100",
                source_command,
                ("tire_jump", 7, 1.00, checkpoint, epoch_dir / "tire100", device),
            ),
            (
                "seesaw165",
                source_command,
                ("seesaw", 37, 1.65, checkpoint, epoch_dir / "seesaw165", device),
            ),
            (
                "TF",
                planner_command,
                ("TF", "default", checkpoint, epoch_dir / "TF", device),
            ),
            (
                "DW",
                planner_command,
                ("DW", "default", checkpoint, epoch_dir / "DW", device),
            ),
            (
                "TRCM",
                planner_command,
                ("TR", "commit", checkpoint, epoch_dir / "TRCM", device),
            ),
        )
        for name, builder, builder_args in specs:
            probes.append(
                Probe(
                    epoch=epoch,
                    name=name,
                    command=builder(*builder_args),
                    output_dir=epoch_dir / name,
                )
            )
    return probes, checkpoints


def run_probe(probe: Probe) -> tuple[str, str, float]:
    result_path = probe.output_dir / "result.json"
    if result_path.is_file():
        payload = json.loads(result_path.read_text())
        if "error" not in payload:
            return probe.name, str(payload["status"]), 0.0
    probe.output_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.setdefault("MUJOCO_GL", "egl")
    started = time.monotonic()
    completed = subprocess.run(
        probe.command,
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
            f"ep{probe.epoch}/{probe.name} produced no result after {elapsed:.1f}s\n"
            f"{details}"
        )
    payload = json.loads(result_path.read_text())
    if "error" in payload:
        raise RuntimeError(f"ep{probe.epoch}/{probe.name}: {payload['error']}")
    return probe.name, str(payload["status"]), elapsed


def score(
    probes: list[Probe], checkpoints: dict[int, Path], output_dir: Path
) -> dict:
    rows = []
    for epoch in range(1, 7):
        outcomes = {}
        for probe in (item for item in probes if item.epoch == epoch):
            payload = json.loads((probe.output_dir / "result.json").read_text())
            forbidden = payload.get("metrics", {}).get(
                "forbidden_contact_before_success_steps", []
            )
            outcomes[probe.name] = {
                "status": payload["status"],
                "forbidden_steps": len(forbidden),
                "device_name": payload.get("device_name"),
            }
        rows.append(
            {
                "epoch": epoch,
                "checkpoint": str(checkpoints[epoch]),
                "checkpoint_sha256": sha256(checkpoints[epoch]),
                "pass_count": sum(
                    item["status"] == "PASSED" for item in outcomes.values()
                ),
                "total_forbidden_steps": sum(
                    item["forbidden_steps"] for item in outcomes.values()
                ),
                "outcomes": outcomes,
            }
        )
    selected = min(
        rows,
        key=lambda row: (
            -row["pass_count"],
            row["total_forbidden_steps"],
            row["epoch"],
        ),
    )
    summary = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "criterion": [
            "maximum pass_count",
            "minimum total forbidden_contact_before_success steps",
            "earliest epoch",
        ],
        "epochs": rows,
        "selected_epoch": selected["epoch"],
        "selected_checkpoint": selected["checkpoint"],
        "selected_checkpoint_sha256": selected["checkpoint_sha256"],
    }
    (output_dir / "selection_summary.json").write_text(
        json.dumps(summary, indent=2) + "\n"
    )
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--train-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--device", default="cuda")
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error("--jobs must be positive")
    return args


def main() -> int:
    args = parse_args()
    probes, checkpoints = build_probes(args.train_dir, args.output_dir, args.device)
    failures = []
    complete = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as executor:
        futures = {executor.submit(run_probe, probe): probe for probe in probes}
        for future in concurrent.futures.as_completed(futures):
            probe = futures[future]
            try:
                name, status, elapsed = future.result()
            except Exception as exc:  # preserve all other preregistered probe results
                failures.append(f"ep{probe.epoch}/{probe.name}")
                print(f"TECHNICAL_FAILURE {exc}", flush=True)
                continue
            complete += 1
            print(
                f"RESULT ep{probe.epoch}/{name} status={status} "
                f"elapsed={elapsed:.1f}s progress={complete}/36",
                flush=True,
            )
    if failures:
        print("FAILED_PROBES " + " ".join(sorted(failures)), flush=True)
        return 1
    summary = score(probes, checkpoints, args.output_dir)
    print(f"SELECTED epoch={summary['selected_epoch']}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
