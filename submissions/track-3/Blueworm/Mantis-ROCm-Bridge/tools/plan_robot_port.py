#!/usr/bin/env python3
"""Validate or plan one robot-port profile without executing the port."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from mantis_rocm_bridge.contracts import ContractError
from mantis_rocm_bridge.port_profile import (
    build_port_plan,
    load_port_profile,
    profile_validation_summary,
)


ROOT = Path(__file__).resolve().parents[1]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Read a robot-port profile and print structural/reference validation "
            "or its declared stage plan. This command never starts simulation, "
            "collection, training, inference, or remote work."
        )
    )
    parser.add_argument("command", choices=("validate", "plan"))
    parser.add_argument("profile", type=Path)
    parser.add_argument(
        "--project-root",
        type=Path,
        default=ROOT,
        help="local root used only to resolve safe project-relative references",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        profile = load_port_profile(args.profile)
        if args.command == "validate":
            result = profile_validation_summary(profile, args.project_root)
        else:
            result = build_port_plan(profile, args.project_root)
    except ContractError as exc:
        print(
            json.dumps(
                {
                    "valid": False,
                    "error_type": "ContractError",
                    "error": str(exc),
                },
                indent=2,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
