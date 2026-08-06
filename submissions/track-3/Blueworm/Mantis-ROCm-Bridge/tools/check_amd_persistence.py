#!/usr/bin/env python3
"""Validate the AMD persistence contract without creating or migrating data."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from mantis_rocm_bridge.amd_persistence import (
    build_persistence_audit,
    load_json,
    validate_durable_output_path,
)
from mantis_rocm_bridge.contracts import ContractError


ROOT = Path(__file__).resolve().parents[1]


def _parse_durable_path(value: str) -> tuple[str, str]:
    label, separator, path = value.partition("=")
    if not separator or not label or not path:
        raise argparse.ArgumentTypeError("expected LABEL=/absolute/path")
    return label, path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--contract",
        type=Path,
        default=ROOT / "configs/amd-persistence-layout-v2.json",
    )
    parser.add_argument(
        "--runtime",
        type=Path,
        default=ROOT / "configs/amd-cloud-runtime-v3.json",
    )
    parser.add_argument(
        "--durable-path",
        action="append",
        default=[],
        type=_parse_durable_path,
        metavar="LABEL=/ABSOLUTE/PATH",
    )
    parser.add_argument(
        "--check-filesystem",
        action="store_true",
        help=(
            "require /workspace/persistent to be the writable symlink to "
            "/persistent"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="optional new JSON receipt path; existing files are never overwritten",
    )
    args = parser.parse_args(argv)

    try:
        paths = dict(args.durable_path)
        if len(paths) != len(args.durable_path):
            raise ContractError("durable path labels must be unique")
        receipt = build_persistence_audit(
            load_json(args.contract),
            runtime=load_json(args.runtime),
            durable_paths=paths,
            check_filesystem=args.check_filesystem,
        )
        if args.output is not None:
            if args.check_filesystem:
                validate_durable_output_path(
                    str(args.output),
                    label="--output",
                )
            payload = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
            with args.output.open("x", encoding="utf-8") as stream:
                stream.write(payload)
    except (ContractError, FileExistsError, OSError, ValueError) as exc:
        print(f"AMD persistence check failed closed: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
