#!/usr/bin/env python3
"""Materialize the pinned MIT-licensed RoboTwin bowl as a Genesis-ready URDF asset."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from mantis_rocm_bridge.bowl_asset import materialize_bowl_asset, validate_bowl_source
from mantis_rocm_bridge.contracts import load_json


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_root", type=Path)
    parser.add_argument("--plan", type=Path, default=ROOT / "configs/bowl-asset-plan.json")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    plan = load_json(args.plan)
    if args.output is None:
        result = {
            "valid": True,
            "materialized": False,
            "source_sha256": validate_bowl_source(args.source_root, plan),
        }
    else:
        result = materialize_bowl_asset(args.source_root, args.output, plan)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
