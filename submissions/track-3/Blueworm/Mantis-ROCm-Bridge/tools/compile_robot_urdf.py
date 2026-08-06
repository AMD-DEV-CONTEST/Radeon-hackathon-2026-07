#!/usr/bin/env python3
"""Inspect a URDF or compile an executable Genesis/LeRobot/ACT/ROCm port bundle."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from mantis_rocm_bridge.contracts import ContractError
from mantis_rocm_bridge.urdf_compiler import (
    compile_port_bundle,
    inspect_urdf,
    verify_bundle,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser(
        "inspect", help="print deterministic Embodiment IR without writing"
    )
    inspect_parser.add_argument("urdf", type=Path)

    compile_parser = subparsers.add_parser(
        "compile", help="compile a new, non-overwriting eleven-file port bundle"
    )
    compile_parser.add_argument("urdf", type=Path)
    compile_parser.add_argument("--semantics", type=Path, required=True)
    compile_parser.add_argument("--task", type=Path, required=True)
    compile_parser.add_argument("--output", type=Path, required=True)

    verify_parser = subparsers.add_parser(
        "verify", help="verify an existing port bundle and its internal manifest"
    )
    verify_parser.add_argument("bundle", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "inspect":
            result = inspect_urdf(args.urdf)
        elif args.command == "compile":
            result = compile_port_bundle(
                args.urdf, args.semantics, args.task, args.output
            )
        else:
            result = verify_bundle(args.bundle)
    except (ContractError, OSError) as exc:
        print(
            json.dumps(
                {
                    "valid": False,
                    "command": args.command,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
                indent=2,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
