#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    from .radeon_cloud_execution import (
        execute_cloud_package,
        read_json,
    )
except ImportError:
    from radeon_cloud_execution import (
        execute_cloud_package,
        read_json,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Execute an AAHJ package inside a Radeon Cloud workspace"
    )
    parser.add_argument("package", type=Path)
    parser.add_argument(
        "--result-directory",
        type=Path,
        default=Path("aahj-cloud-result"),
    )
    parser.add_argument(
        "--allow-non-radeon",
        action="store_true",
        help="test-only escape hatch; production runs require Radeon preflight",
    )
    args = parser.parse_args()

    try:
        result = execute_cloud_package(
            args.package,
            result_directory=args.result_directory,
            require_radeon=not args.allow_non_radeon,
        )
        payload = read_json(result)
        print(json.dumps(payload, indent=2, sort_keys=True))
        status = payload["execution_result"]["status"]
        return 0 if status == "succeeded" else 1
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
