#!/usr/bin/env python3
"""Print candidate Mantis gripper endpoints and verify numeric round trips."""

from __future__ import annotations

import json
from pathlib import Path

from mantis_rocm_bridge.contracts import load_json
from mantis_rocm_bridge.gripper import physical_to_virtual, virtual_to_physical


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    port = load_json(ROOT / "configs/mantis-port-config.json")
    virtual_order = port["target"]["joint_order"]
    endpoints = []
    max_error = 0.0
    for fraction in (0.0, 0.5, 1.0):
        virtual = [0.0] * len(virtual_order)
        virtual[virtual_order.index("left_gripper_joint")] = fraction
        virtual[virtual_order.index("right_gripper_joint")] = fraction
        physical = virtual_to_physical(virtual, port, allow_unverified=True)
        recovered = physical_to_virtual(physical, port, allow_unverified=True)
        max_error = max(max_error, max(abs(a - b) for a, b in zip(virtual, recovered)))
        endpoints.append({"open_fraction": fraction, "physical_vector": physical})
    print(
        json.dumps(
            {
                "status": port["assets"]["virtual_gripper_mapping"]["status"],
                "offline_numeric_roundtrip_pass": max_error <= 1e-12,
                "max_roundtrip_error": max_error,
                "endpoints": endpoints,
                "genesis_visual_verified": (
                    port["assets"]["virtual_gripper_mapping"]["status"]
                    in {"sim_verified_hardware_unverified", "verified"}
                ),
                "hardware_verified": (
                    port["assets"]["virtual_gripper_mapping"]["status"] == "verified"
                ),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
