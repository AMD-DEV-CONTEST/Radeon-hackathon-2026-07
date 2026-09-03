#!/usr/bin/env python3
"""Plan or locally materialize the fixed-base Mantis asset."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from mantis_rocm_bridge.asset_builder import materialize_fixed_base_asset, plan_fixed_base_asset
from mantis_rocm_bridge.contracts import load_json


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_urdf", type=Path)
    parser.add_argument("--package-root", type=Path, required=True)
    parser.add_argument("--port", type=Path, default=ROOT / "configs/mantis-port-config.json")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--materialize", action="store_true")
    parser.add_argument("--acknowledge-unresolved-license-for-local-use", action="store_true")
    args = parser.parse_args()

    port = load_json(args.port)
    profile = port["assets"]["fixed_base_profile"]
    common = {
        "source_urdf": args.source_urdf,
        "package_root": args.package_root,
        "root_link": profile["root_link"],
        "selected_joint_order": profile["selected_joint_order"],
        "robot_name": profile["robot_name"],
    }
    if args.materialize:
        if args.output is None:
            parser.error("--output is required with --materialize")
        result = materialize_fixed_base_asset(
            output_root=args.output,
            physical_gripper_joints=port["assets"]["physical_gripper_joint_order"],
            acknowledge_unresolved_license_for_local_use=(
                args.acknowledge_unresolved_license_for_local_use
            ),
            **common,
        )
    else:
        result = plan_fixed_base_asset(**common)
        result["materialized"] = False
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

