from __future__ import annotations

import copy
import math
import unittest
from pathlib import Path

from mantis_rocm_bridge.contracts import ContractError, load_json
from mantis_rocm_bridge.genesis_smoke import (
    compare_joint_limits,
    gripper_geometry,
    max_abs_error,
    physical_pose,
    resolve_backend,
)


ROOT = Path(__file__).resolve().parents[1]


class _GenesisStub:
    cpu = object()
    cuda = object()


class GenesisSmokeHelperTests(unittest.TestCase):
    def setUp(self) -> None:
        self.port = load_json(ROOT / "configs/mantis-port-config.json")

    def test_physical_open_pose_matches_frozen_limits(self) -> None:
        pose = physical_pose(self.port, 1.0)
        order = self.port["target"]["physical_joint_order"]
        by_name = dict(zip(order, pose))
        for name in self.port["assets"]["physical_gripper_joint_order"]:
            self.assertEqual(by_name[name], 0.0)

    def test_backend_selection_never_falls_back(self) -> None:
        self.assertIs(resolve_backend(_GenesisStub, "cpu"), _GenesisStub.cpu)
        with self.assertRaises(ContractError):
            resolve_backend(_GenesisStub, "amdgpu")
        with self.assertRaises(ContractError):
            resolve_backend(_GenesisStub, "gpu")

    def test_readback_error_rejects_bad_shapes_and_nonfinite_values(self) -> None:
        self.assertEqual(max_abs_error([0.0, 1.0], [0.0, 1.25]), 0.25)
        with self.assertRaises(ContractError):
            max_abs_error([0.0], [0.0, 1.0])
        with self.assertRaises(ContractError):
            max_abs_error([float("nan")], [0.0])

    def test_pose_rejects_bad_fraction(self) -> None:
        for value in (-0.1, 1.1, float("inf")):
            with self.subTest(value=value), self.assertRaises(ContractError):
                physical_pose(copy.deepcopy(self.port), value)

    def test_joint_limit_comparison(self) -> None:
        frozen = {
            "joint_a": {"lower": -1.0, "upper": 2.0},
            "joint_b": {"lower": 0.0, "upper": 0.04},
        }
        result = compare_joint_limits(
            ["joint_a", "joint_b"], [-1.0, 0.0], [2.0, 0.0400000001], frozen
        )
        self.assertTrue(result["pass"])
        self.assertLess(result["max_abs_error"], 1e-6)
        with self.assertRaises(ContractError):
            compare_joint_limits(["joint_a", "joint_b"], [-1.0], [2.0], frozen)

    def test_gripper_geometry_requires_separation_and_symmetric_travel(self) -> None:
        children = {
            "left_clamp_right_joint": "lr",
            "left_clamp_left_joint": "ll",
            "right_clamp_right_joint": "rr",
            "right_clamp_left_joint": "rl",
        }
        closed = {"lr": [0, 0, 0], "ll": [0, 0, 0], "rr": [0, 0, 0], "rl": [0, 0, 0]}
        opened = {
            "lr": [0, 0.0376, 0],
            "ll": [0, -0.0376, 0],
            "rr": [0, -0.0376, 0],
            "rl": [0, 0.0376, 0],
        }
        result = gripper_geometry(self.port, children, closed, opened)
        self.assertTrue(all(item["kinematic_gate_pass"] for item in result.values()))
        self.assertTrue(
            math.isclose(result["left_gripper_joint"]["separation_increase_m"], 0.0752)
        )


if __name__ == "__main__":
    unittest.main()
