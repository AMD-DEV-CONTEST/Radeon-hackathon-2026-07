#!/usr/bin/env python3
"""Stage-2 AMD Radeon Cloud bootstrap CLI.

Runs at the AMD instance project root. Validates the stage-1 receipt, ensures
Genesis repository is present and clean, installs Genesis, LeRobot 0.4.4, and
model dependencies with accelerator constraints, runs smoke tests (torch HIP,
Genesis import/scene, LeRobot version, numpy/scikit-image, ffmpeg), and writes
a bounded, secret-free JSON receipt.

This never trains. Pass --dry-run to validate and print the planned receipt
and commands without mutating the system or writing a file.

Exit codes: 0 success, 2 verification failure (fail closed).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from mantis_rocm_bridge.amd_cloud_stage2 import (
    ContractError,
    DEFAULT_CONSTRAINTS_PATH,
    run_stage2_bootstrap,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stage1-receipt",
        type=Path,
        required=True,
        help="path to the stage-1 receipt JSON",
    )
    parser.add_argument(
        "--instance-id",
        help="instance ID (default: read from stage-1 receipt)",
    )
    parser.add_argument(
        "--genesis-repo",
        default="https://github.com/Genesis-Embodied-AI/Genesis.git",
        help="Genesis repository URL (default: official GitHub repo)",
    )
    parser.add_argument(
        "--genesis-root",
        default="/workspace/persistent/mantis-track3/src/Genesis",
        help="Genesis installation root under the frozen persistence layout",
    )
    parser.add_argument(
        "--constraints-path",
        help=f"path for the constraints file (default: {DEFAULT_CONSTRAINTS_PATH})",
    )
    parser.add_argument(
        "--receipt",
        type=Path,
        help="where to write the bounded stage-2 receipt (required unless --dry-run)",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="allow replacing an existing receipt (default: refuse)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="validate and print the planned receipt/commands without mutating the system",
    )
    args = parser.parse_args(argv)

    if not args.dry_run and args.receipt is None:
        parser.error("--receipt is required unless --dry-run is set")

    try:
        receipt = run_stage2_bootstrap(
            stage1_receipt_path=args.stage1_receipt,
            receipt_path=args.receipt if not args.dry_run else None,
            instance_id=args.instance_id,
            genesis_repo_url=args.genesis_repo,
            genesis_install_root=args.genesis_root,
            constraints_path=args.constraints_path,
            overwrite=args.overwrite,
            execute=not args.dry_run,
        )
    except ContractError as exc:
        print(f"stage-2 bootstrap failed closed: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(receipt, indent=2, sort_keys=True))
    if not args.dry_run and args.receipt is not None:
        print(f"\nreceipt written: {args.receipt}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
