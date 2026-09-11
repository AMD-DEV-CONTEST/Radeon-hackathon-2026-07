#!/usr/bin/env python3
"""Advance frozen LIBERO cadence evaluation, then launch B3-SW without overlap."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import time
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_status(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def process_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def plan_next_actions(selection: dict[str, Any]) -> list[str]:
    status = selection.get("status")
    if status == "candidate_frozen":
        if not bool(selection.get("candidate_strictly_better")) or not bool(
            selection.get("confirmation_may_start")
        ):
            raise ValueError("candidate_frozen lacks confirmation authorization")
        return ["run_confirmation", "launch_b3_sw"]
    if status == "control_retained":
        return ["skip_confirmation", "launch_b3_sw"]
    raise ValueError(f"development selection is incomplete or invalid: {status}")


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    persistence = Path("/workspace/persistence/parcel-sorter-opt-v1")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--development-pid", type=int, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument(
        "--development-output",
        type=Path,
        default=persistence / "outputs" / "pi05-libero-action-steps-development-v1",
    )
    parser.add_argument("--baseline-output", type=Path, required=True)
    parser.add_argument(
        "--confirmation-config",
        type=Path,
        default=(
            persistence
            / "artifacts"
            / "pi05-libero-action-steps-confirmation-protocol-v1"
            / "pi05_libero_action_steps_confirmation_v1.json"
        ),
    )
    parser.add_argument(
        "--confirmation-output",
        type=Path,
        default=persistence / "outputs" / "pi05-libero-action-steps-confirmation-v1",
    )
    parser.add_argument(
        "--decision-root",
        type=Path,
        default=persistence / "artifacts" / "pi05-libero-action-steps-to-b3-sw-v1",
    )
    parser.add_argument("--python", type=Path, default=Path("/workspace/rdna/bin/python"))
    parser.add_argument("--poll-seconds", type=float, default=30.0)
    parser.add_argument("--b3-version", default="v1")
    args = parser.parse_args()

    status_path = args.decision_root / "DECISION.json"
    if args.decision_root.exists() and any(args.decision_root.iterdir()):
        raise FileExistsError(f"decision root is not empty: {args.decision_root}")
    write_status(
        status_path,
        {
            "schema_version": 1,
            "protocol_id": "pi05-libero-action-steps-to-b3-sw-v1",
            "stage": "waiting_for_development",
            "development_pid": args.development_pid,
            "automatic_confirmation": True,
            "automatic_b3_sw_launch": True,
        },
    )

    try:
        while process_exists(args.development_pid):
            time.sleep(args.poll_seconds)
        development_summary = args.development_output / "DEVELOPMENT_SUMMARY.json"
        if not development_summary.is_file():
            raise RuntimeError("development process ended without DEVELOPMENT_SUMMARY.json")
        development = load_json(development_summary)
        selection = development.get("selection") or {}
        actions = plan_next_actions(selection)
        write_status(
            status_path,
            {
                "schema_version": 1,
                "protocol_id": "pi05-libero-action-steps-to-b3-sw-v1",
                "stage": "development_complete",
                "development_pid": args.development_pid,
                "development_summary": str(development_summary),
                "selection": selection,
                "planned_actions": actions,
            },
        )

        confirmation_summary = None
        if actions[0] == "run_confirmation":
            write_status(
                status_path,
                {
                    "schema_version": 1,
                    "protocol_id": "pi05-libero-action-steps-to-b3-sw-v1",
                    "stage": "confirmation_running",
                    "selection": selection,
                    "confirmation_output": str(args.confirmation_output),
                },
            )
            command = [
                str(args.python),
                str(root / "scripts" / "run_pi05_libero_action_steps_confirmation_rocm.py"),
                "--checkpoint",
                str(args.checkpoint),
                "--manifest",
                str(args.manifest),
                "--development-summary",
                str(development_summary),
                "--baseline-output",
                str(args.baseline_output),
                "--config",
                str(args.confirmation_config),
                "--output-root",
                str(args.confirmation_output),
                "--seed",
                "20260729",
            ]
            subprocess.run(command, check=True)
            confirmation_summary = args.confirmation_output / "CONFIRMATION_SUMMARY.json"
            if not confirmation_summary.is_file():
                raise RuntimeError("confirmation completed without CONFIRMATION_SUMMARY.json")

        b3_command = [
            "bash",
            str(root / "scripts" / "launch_mobile_pi05_b3_sw_pipeline_rocm.sh"),
            args.b3_version,
        ]
        launched = subprocess.run(
            b3_command, check=True, capture_output=True, text=True
        )
        write_status(
            status_path,
            {
                "schema_version": 1,
                "protocol_id": "pi05-libero-action-steps-to-b3-sw-v1",
                "stage": "b3_sw_started",
                "selection": selection,
                "confirmation_summary": (
                    None if confirmation_summary is None else str(confirmation_summary)
                ),
                "b3_launch": launched.stdout.strip(),
            },
        )
        return 0
    except Exception as error:
        write_status(
            status_path,
            {
                "schema_version": 1,
                "protocol_id": "pi05-libero-action-steps-to-b3-sw-v1",
                "stage": "failed",
                "error_type": type(error).__name__,
                "error": str(error),
            },
        )
        raise


if __name__ == "__main__":
    raise SystemExit(main())
