#!/usr/bin/env python3
"""Materialize the local-only primitive rim-support overlay on Mantis."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from mantis_rocm_bridge.contracts import load_json
from mantis_rocm_bridge.rim_support_overlay import materialize_rim_support_overlay


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_root", type=Path)
    parser.add_argument("output_root", type=Path)
    parser.add_argument(
        "--plan",
        type=Path,
        default=ROOT / "configs/mantis-rim-support-overlay-v1.json",
    )
    parser.add_argument("--acknowledge-unresolved-license-for-local-use", action="store_true")
    args = parser.parse_args()
    result = materialize_rim_support_overlay(
        args.input_root,
        args.output_root,
        load_json(args.plan),
        acknowledge_unresolved_license_for_local_use=(
            args.acknowledge_unresolved_license_for_local_use
        ),
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
