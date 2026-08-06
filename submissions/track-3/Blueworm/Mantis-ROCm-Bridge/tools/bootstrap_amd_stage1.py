#!/usr/bin/env python3
"""Stage-1 AMD Radeon Cloud bootstrap CLI.

Runs at the AMD instance project root. Validates the stage-0 inventory, checks
exactly one GPU and a ROCm tool, strictly verifies the official ROCm wheel
paths and SHA-256 digests, creates the persistence-contract venv, installs the ROCm
PyTorch stack from the local wheels only (--no-index), and writes a bounded,
secret-free JSON receipt plus pip freeze and a torch HIP/device smoke.

This never trains and never installs Genesis or LeRobot (stage 2). Pass
--dry-run to validate and print the planned receipt and commands without
mutating the system or writing a file.

Exit codes: 0 success, 2 verification failure (fail closed).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from mantis_rocm_bridge.amd_cloud_bootstrap import (
    ContractError,
    run_stage1_bootstrap,
)


ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=ROOT / "configs/amd-cloud-runtime-v3.json",
        help="path to the AMD cloud runtime config (default: repo config)",
    )
    parser.add_argument(
        "--venv",
        type=Path,
        help="venv path (default: platform.virtual_environment from the config)",
    )
    parser.add_argument(
        "--find-links-root",
        type=Path,
        default=Path("/"),
        help="local directory pip may search for dependencies (default: /)",
    )
    parser.add_argument(
        "--python",
        help="interpreter used to build the venv (default: sys.executable)",
    )
    parser.add_argument(
        "--receipt",
        type=Path,
        help="where to write the bounded stage-1 receipt (required unless --dry-run)",
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
        receipt = run_stage1_bootstrap(
            config_path=args.config,
            receipt_path=args.receipt if not args.dry_run else None,
            venv_path=args.venv,
            find_links_root=args.find_links_root,
            python_exe=args.python,
            overwrite=args.overwrite,
            execute=not args.dry_run,
        )
    except ContractError as exc:
        print(f"stage-1 bootstrap failed closed: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(receipt, indent=2, sort_keys=True))
    if not args.dry_run and args.receipt is not None:
        print(f"\nreceipt written: {args.receipt}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
