from __future__ import annotations

import unittest
from pathlib import Path

from mantis_rocm_bridge.urdf_audit import audit_urdf


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/minimal.urdf"


class UrdfAuditTests(unittest.TestCase):
    def test_minimal_contract_passes(self) -> None:
        receipt = audit_urdf(FIXTURE, ["arm_joint"], ["finger_joint"], ROOT)
        self.assertTrue(receipt["genesis_import_gate_pass"])
        self.assertEqual(receipt["root_links"], ["base"])
        self.assertEqual(receipt["physical_gripper_joints"][0]["limit"]["upper"], 0.04)

    def test_uncontrolled_joint_is_rejected(self) -> None:
        receipt = audit_urdf(FIXTURE, [], ["finger_joint"], ROOT)
        self.assertFalse(receipt["genesis_import_gate_pass"])
        self.assertEqual(receipt["uncontrolled_actuated_joints"], ["arm_joint"])


if __name__ == "__main__":
    unittest.main()

