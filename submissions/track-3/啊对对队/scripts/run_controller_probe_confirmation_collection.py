#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import signal
import subprocess
import sys
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from parcel_sorter.grasp_scoring import sha256_file
from scripts.run_grasp_candidate_collection import (
    _validated_output,
    _write_manifest,
    planned_runs,
)


ACTIVATION_POLICY = "all-boxes"
SPLIT = "confirmation"


def run(args: argparse.Namespace) -> dict[str, Any]:
    if min(args.max_candidates, args.repeats) < 1:
        raise ValueError("candidate and repeat budgets must be positive")
    protocol = args.protocol.resolve()
    output_dir = args.output_dir.resolve()
    rows = planned_runs(protocol, SPLIT, output_dir)
    manifest_path = output_dir / SPLIT / "manifest.json"
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "protocol": str(protocol),
        "protocol_sha256": sha256_file(protocol),
        "split": SPLIT,
        "backend": args.backend,
        "max_candidates": args.max_candidates,
        "repeats": args.repeats,
        "planning_activation_policy": ACTIVATION_POLICY,
        "dry_run": args.dry_run,
        "planned_episode_count": len(rows),
        "planned_max_rollouts": len(rows) * args.max_candidates * args.repeats,
        "runs": [],
    }
    labeler = PROJECT_ROOT / "scripts/diagnose_counterfactual_grasp_candidates.py"
    for row in rows:
        output = Path(str(row["output"]))
        command = [
            sys.executable,
            str(labeler),
            "--config",
            str(args.config.resolve()),
            "--profile",
            str(row["profile"]),
            "--episode",
            str(row["episode"]),
            "--backend",
            args.backend,
            "--all-candidates",
            "--max-candidates",
            str(args.max_candidates),
            "--repeats",
            str(args.repeats),
            "--inactive-gate",
            "error",
            "--planning-activation",
            ACTIVATION_POLICY,
            "--output",
            str(output),
        ]
        record = {**row, "command": command, "status": "planned"}
        manifest["runs"].append(record)
        if args.dry_run:
            continue
        if output.exists():
            if not args.resume:
                raise FileExistsError(
                    f"collection output already exists: {output}; pass --resume to audit and skip"
                )
            payload = _validated_output(
                output,
                row,
                backend=args.backend,
                config=args.config,
                max_candidates=args.max_candidates,
                repeats=args.repeats,
                planning_activation_policy=ACTIVATION_POLICY,
            )
            record.update(
                {
                    "status": "reused",
                    "source_status": str(payload["status"]),
                    "sha256": sha256_file(output),
                }
            )
            _write_manifest(manifest_path, manifest)
            continue
        output.parent.mkdir(parents=True, exist_ok=True)
        record["status"] = "running"
        _write_manifest(manifest_path, manifest)
        completed: subprocess.CompletedProcess[Any] | None = None
        accepted_cleanup_failure = False
        try:
            completed = subprocess.run(command, cwd=PROJECT_ROOT, check=False)
            payload = _validated_output(
                output,
                row,
                backend=args.backend,
                config=args.config,
                max_candidates=args.max_candidates,
                repeats=args.repeats,
                planning_activation_policy=ACTIVATION_POLICY,
            )
            if completed.returncode != 0:
                accepted_cleanup_failure = completed.returncode in {
                    128 + signal.SIGSEGV,
                    -signal.SIGSEGV,
                }
                if not accepted_cleanup_failure:
                    raise subprocess.CalledProcessError(completed.returncode, command)
        except BaseException:
            record["status"] = "failed"
            if completed is not None:
                record["child_returncode"] = completed.returncode
            _write_manifest(manifest_path, manifest)
            raise
        record.update(
            {
                "status": "complete",
                "source_status": str(payload["status"]),
                "child_returncode": completed.returncode,
                "accepted_cleanup_failure": accepted_cleanup_failure,
                "sha256": sha256_file(output),
            }
        )
        _write_manifest(manifest_path, manifest)
    if args.dry_run:
        return manifest
    manifest["complete_episode_count"] = sum(
        row["status"] in {"complete", "reused"} for row in manifest["runs"]
    )
    _write_manifest(manifest_path, manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect the frozen V5 independent confirmation population.")
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=PROJECT_ROOT / "configs/catalog_v2.toml")
    parser.add_argument("--backend", choices=("cpu", "rocm"), default="rocm")
    parser.add_argument("--max-candidates", type=int, default=6)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    result = run(args)
    print(json.dumps({
        "split": result["split"],
        "dry_run": result["dry_run"],
        "planned_episode_count": result["planned_episode_count"],
        "planned_max_rollouts": result["planned_max_rollouts"],
        "planning_activation_policy": result["planning_activation_policy"],
        "manifest": str(args.output_dir.resolve() / SPLIT / "manifest.json"),
    }, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
