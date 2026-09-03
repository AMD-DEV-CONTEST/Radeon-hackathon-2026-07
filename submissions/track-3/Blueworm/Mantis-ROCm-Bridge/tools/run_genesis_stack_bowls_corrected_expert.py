#!/usr/bin/env python3
"""Run one frozen WP-G3-CORR-010 corrected-expert stage.

This wrapper makes ``coupled_descent_slerp`` and both governing contracts
mandatory. It exposes only the three permitted operations: no-capture
diagnostic, collection probe, and hash-bound replay capture.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]
CORE_TOOL = ROOT / "tools/run_genesis_stack_bowls_scripted_g1.py"
R3_CONTRACT = (
    ROOT / "configs/g3-left-interbowl-coupled-descent-dynamic-v3.json"
)
CORRECTED_CONTRACT = ROOT / "configs/g3-corrected-expert-coverage-v4.json"
EXECUTION_AUTHORIZATION = (
    ROOT / "configs/g3-corrected-expert-execution-authorization-v5.json"
)
SCHEDULE_ID = "coupled_descent_slerp"
DIAGNOSTIC_SEEDS = (1285, 1290, 1295, 1298)
COLLECTION_SEEDS = (
    1251,
    1254,
    1255,
    1256,
    1266,
    1281,
    1299,
    1301,
    1302,
    1313,
    1316,
    1323,
    1360,
    1362,
    1375,
    1376,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("mantis_urdf", type=Path)
    parser.add_argument("bowl_asset_root", type=Path)
    parser.add_argument("--ops-root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument(
        "--phase",
        choices=("diagnostic", "probe", "capture"),
        required=True,
    )
    parser.add_argument("--replay-plan", type=Path)
    parser.add_argument("--probe-max-policy-steps", type=int, default=2400)
    parser.add_argument(
        "--core-tool",
        type=Path,
        default=CORE_TOOL,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--r3-contract",
        type=Path,
        default=R3_CONTRACT,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--corrected-contract",
        type=Path,
        default=CORRECTED_CONTRACT,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--execution-authorization",
        type=Path,
        default=EXECUTION_AUTHORIZATION,
        help=argparse.SUPPRESS,
    )
    return parser


def validate_args(args: argparse.Namespace) -> None:
    if args.seed in DIAGNOSTIC_SEEDS:
        if args.phase != "diagnostic":
            raise ValueError("diagnostic seeds require phase=diagnostic")
    elif args.seed in COLLECTION_SEEDS:
        if args.phase not in {"probe", "capture"}:
            raise ValueError("collection seeds require phase=probe or capture")
    else:
        raise ValueError("seed is outside frozen corrected-expert panels")
    if args.phase == "capture":
        if args.replay_plan is None or not args.replay_plan.is_file():
            raise ValueError("capture requires an existing --replay-plan")
    elif args.replay_plan is not None:
        raise ValueError("--replay-plan is valid only for phase=capture")
    if args.probe_max_policy_steps < 1200:
        raise ValueError("--probe-max-policy-steps must be at least 1200")
    for path, label in (
        (args.mantis_urdf, "Mantis URDF"),
        (
            args.bowl_asset_root
            / "urdf/robotwin_002_bowl_model3.urdf",
            "bowl URDF",
        ),
        (args.core_tool, "core tool"),
        (args.r3_contract, "R3 contract"),
        (args.corrected_contract, "corrected-expert contract"),
        (args.execution_authorization, "execution authorization"),
    ):
        if not path.is_file():
            raise ValueError(f"{label} does not exist: {path}")


def build_core_command(
    args: argparse.Namespace,
    *,
    python_executable: str = sys.executable,
) -> list[str]:
    validate_args(args)
    generation_mode = "replay" if args.phase == "capture" else "probe"
    command = [
        python_executable,
        str(args.core_tool),
        str(args.mantis_urdf),
        str(args.bowl_asset_root),
        "--ops-root",
        str(args.ops_root),
        "--run-id",
        args.run_id,
        "--backend",
        "cpu",
        "--generation-mode",
        generation_mode,
        "--seed",
        str(args.seed),
        "--probe-max-policy-steps",
        str(args.probe_max_policy_steps),
        "--consecutive-left-orientation-schedule",
        SCHEDULE_ID,
        "--consecutive-left-dynamic-contract",
        str(args.r3_contract),
        "--corrected-expert-contract",
        str(args.corrected_contract),
        "--corrected-expert-authorization",
        str(args.execution_authorization),
    ]
    if args.phase == "capture":
        assert args.replay_plan is not None
        command.extend(["--replay-plan", str(args.replay_plan), "--capture"])
    return command


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        command = build_core_command(args)
    except ValueError as error:
        parser.error(str(error))
    environment = os.environ.copy()
    environment["CUDA_VISIBLE_DEVICES"] = ""
    environment["PYTHONPATH"] = str(ROOT / "src")
    return subprocess.run(
        command,
        cwd=ROOT,
        env=environment,
        check=False,
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
