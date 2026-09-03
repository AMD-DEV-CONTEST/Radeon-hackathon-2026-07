#!/usr/bin/env python3
"""Run one frozen WP-G3-CORR-012 support-contact CPU probe."""
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
DIAGNOSTIC_CONTRACT = (
    ROOT / "configs/g3-level1-support-contact-observability-v11.json"
)
EXECUTION_AUTHORIZATION = (
    ROOT / "configs/g3-level1-support-contact-execution-authorization-v12.json"
)
SCHEDULE_ID = "coupled_descent_slerp"
DIAGNOSTIC_SEEDS = (1602, 1610, 1613, 1622, 1630, 1635, 1658, 1667)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("mantis_urdf", type=Path)
    parser.add_argument("bowl_asset_root", type=Path)
    parser.add_argument("--ops-root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--seed", type=int, required=True)
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
        "--diagnostic-contract",
        type=Path,
        default=DIAGNOSTIC_CONTRACT,
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
    if args.seed not in DIAGNOSTIC_SEEDS:
        raise ValueError("seed is outside frozen support-contact panel")
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
        (args.diagnostic_contract, "diagnostic contract"),
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
    return [
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
        "probe",
        "--seed",
        str(args.seed),
        "--probe-max-policy-steps",
        str(args.probe_max_policy_steps),
        "--consecutive-left-orientation-schedule",
        SCHEDULE_ID,
        "--consecutive-left-dynamic-contract",
        str(args.r3_contract),
        "--level1-release-diagnostic-contract",
        str(args.diagnostic_contract),
        "--level1-release-diagnostic-authorization",
        str(args.execution_authorization),
    ]


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
