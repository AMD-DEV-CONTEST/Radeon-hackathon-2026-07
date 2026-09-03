from __future__ import annotations

import math
import unittest
from pathlib import Path

from mantis_rocm_bridge.camera_mounts import fixed_rpy_transform, genesis_wrist_mounts
from mantis_rocm_bridge.contracts import ContractError, load_json


ROOT = Path(__file__).resolve().parents[1]


class CameraMountTests(unittest.TestCase):
    def test_checked_in_sim_mounts_resolve_to_mantis_terminal_links(self) -> None:
        contract = load_json(ROOT / "configs/camera-extrinsics-v1.json")
        mounts = genesis_wrist_mounts(contract)
        self.assertEqual(mounts["left_wrist_cam"]["parent"], "left_wrist_yaw_link")
        self.assertEqual(mounts["right_wrist_cam"]["parent"], "right_wrist_yaw_link")
        self.assertEqual(mounts["left_wrist_cam"]["offset_T"][0][3], 0.0664)

    def test_rotation_is_orthonormal(self) -> None:
        transform = fixed_rpy_transform(
            [0.0664, -0.0012, -0.0979], [1.78179, 1.451946, -2.929144]
        )
        rotation = [row[:3] for row in transform[:3]]
        for left in range(3):
            for right in range(3):
                dot = sum(rotation[row][left] * rotation[row][right] for row in range(3))
                self.assertTrue(math.isclose(dot, 1.0 if left == right else 0.0, abs_tol=1e-12))

    def test_physical_calibration_boundary_cannot_be_removed(self) -> None:
        contract = load_json(ROOT / "configs/camera-extrinsics-v1.json")
        contract["hardware_boundary"]["status"] = "verified"
        with self.assertRaises(ContractError):
            genesis_wrist_mounts(contract)


if __name__ == "__main__":
    unittest.main()
