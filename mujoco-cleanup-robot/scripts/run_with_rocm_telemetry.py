"""Run an arbitrary command with append-only ROCm telemetry."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from realtime_cleanup.rocm_telemetry import (  # noqa: E402
    build_rocm_smi_command,
    run_with_rocm_telemetry,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a command while sampling ROCm GPU metrics into JSONL.",
    )
    parser.add_argument("--output", type=Path, required=True, help="append-only JSONL path")
    parser.add_argument("--job", required=True, help="job identifier stored in every sample")
    parser.add_argument("--stage", default="run", help="stage identifier stored in every sample")
    parser.add_argument("--interval", type=float, default=1.0, help="sample interval in seconds")
    parser.add_argument(
        "--format",
        choices=("json", "csv"),
        default="json",
        dest="output_format",
        help="structured rocm-smi output format",
    )
    parser.add_argument("--rocm-smi", default="rocm-smi", help="rocm-smi executable")
    parser.add_argument(
        "--command-timeout",
        type=float,
        default=10.0,
        help="maximum seconds for one rocm-smi query",
    )
    parser.add_argument(
        "--termination-grace",
        type=float,
        default=5.0,
        help="seconds before a signaled child is killed",
    )
    parser.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help="command to run; place it after --",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    command = list(args.command)
    if command and command[0] == "--":
        command.pop(0)
    if not command:
        _parser().error("a command is required after --")

    returncode = run_with_rocm_telemetry(
        command,
        output=args.output,
        job=args.job,
        stage=args.stage,
        interval=args.interval,
        telemetry_command=build_rocm_smi_command(
            args.rocm_smi,
            output_format=args.output_format,
        ),
        output_format=args.output_format,
        command_timeout=args.command_timeout,
        termination_grace=args.termination_grace,
    )
    return 128 - returncode if returncode < 0 else returncode


if __name__ == "__main__":
    raise SystemExit(main())
