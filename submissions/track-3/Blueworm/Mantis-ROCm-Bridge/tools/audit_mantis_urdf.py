#!/usr/bin/env python3
"""Audit a Mantis URDF against the frozen policy contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from mantis_rocm_bridge.contracts import load_json
from mantis_rocm_bridge.urdf_audit import audit_urdf


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("urdf", type=Path)
    parser.add_argument("--package-root", type=Path)
    parser.add_argument("--port", type=Path, default=ROOT / "configs/mantis-port-config.json")
    parser.add_argument("--require-clean", action="store_true")
    args = parser.parse_args()
    port = load_json(args.port)
    virtual_grippers = {"left_gripper_joint", "right_gripper_joint"}
    expected_arm = [
        name for name in port["target"]["joint_order"] if name not in virtual_grippers
    ]
    receipt = audit_urdf(
        args.urdf,
        expected_arm,
        port["assets"]["physical_gripper_joint_order"],
        args.package_root,
    )
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 2 if args.require_clean and not receipt["genesis_import_gate_pass"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

