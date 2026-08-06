#!/usr/bin/env python3
"""Convert a licensed bowl materialization to explicit multi-part STL collision."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from mantis_rocm_bridge.bowl_asset import materialize_bowl_collision_stl
from mantis_rocm_bridge.contracts import load_json


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_root", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--plan",
        type=Path,
        default=ROOT / "configs/bowl-asset-plan.json",
    )
    args = parser.parse_args()
    result = materialize_bowl_collision_stl(
        args.input_root,
        args.output,
        load_json(args.plan),
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
