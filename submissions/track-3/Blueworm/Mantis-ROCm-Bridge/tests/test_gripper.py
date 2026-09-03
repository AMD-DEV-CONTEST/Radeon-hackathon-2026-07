from __future__ import annotations

import unittest
from pathlib import Path

from mantis_rocm_bridge.contracts import ContractError, load_json
from mantis_rocm_bridge.gripper import (
    physical_to_virtual,
    project_physical_to_virtual,
    virtual_to_physical,
)


ROOT = Path(__file__).resolve().parents[1]


class GripperMappingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.port = load_json(ROOT / "configs/mantis-port-config.json")
        self.virtual_order = self.port["target"]["joint_order"]
        self.physical_order = self.port["target"]["physical_joint_order"]

    def _virtual(self, left: float, right: float) -> list[float]:
        values = [0.0] * len(self.virtual_order)
        values[self.virtual_order.index("left_gripper_joint")] = left
        values[self.virtual_order.index("right_gripper_joint")] = right
        return values

    def test_unverified_mapping_is_blocked_by_default(self) -> None:
        with self.assertRaises(ContractError):
            virtual_to_physical(self._virtual(0.0, 0.0), self.port)

    def test_candidate_open_endpoint_matches_urdf_limits(self) -> None:
        physical = virtual_to_physical(
            self._virtual(1.0, 1.0), self.port, allow_unverified=True
        )
        by_name = dict(zip(self.physical_order, physical))
        for name in self.port["assets"]["physical_gripper_joint_order"]:
            self.assertEqual(by_name[name], 0.0)

    def test_candidate_closed_endpoint_matches_urdf_limits(self) -> None:
        physical = virtual_to_physical(
            self._virtual(0.0, 0.0), self.port, allow_unverified=True
        )
        by_name = dict(zip(self.physical_order, physical))
        self.assertEqual(by_name["left_clamp_right_joint"], 0.0376)
        self.assertEqual(by_name["left_clamp_left_joint"], -0.0376)
        self.assertEqual(by_name["right_clamp_right_joint"], -0.0376)
        self.assertEqual(by_name["right_clamp_left_joint"], 0.0376)

    def test_candidate_roundtrip(self) -> None:
        virtual = self._virtual(0.25, 0.75)
        physical = virtual_to_physical(virtual, self.port, allow_unverified=True)
        recovered = physical_to_virtual(physical, self.port, allow_unverified=True)
        for expected, actual in zip(virtual, recovered):
            self.assertAlmostEqual(expected, actual, places=12)

    def test_asymmetric_physical_fingers_are_rejected(self) -> None:
        physical = virtual_to_physical(
            self._virtual(0.5, 0.5), self.port, allow_unverified=True
        )
        physical[self.physical_order.index("left_clamp_left_joint")] = -0.01
        with self.assertRaises(ContractError):
            physical_to_virtual(physical, self.port, allow_unverified=True)

    def test_virtual_range_is_not_silently_clipped(self) -> None:
        with self.assertRaises(ContractError):
            virtual_to_physical(self._virtual(-0.1, 0.5), self.port, allow_unverified=True)


class GripperProjectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.port = load_json(ROOT / "configs/mantis-port-config.json")
        self.virtual_order = self.port["target"]["joint_order"]
        self.physical_order = self.port["target"]["physical_joint_order"]
        self.coefficients = self.port["assets"]["virtual_gripper_mapping"]["coefficients"]
        self.offsets = self.port["assets"]["virtual_gripper_mapping"]["offsets"]

    def _physical_with_left_estimates(
        self, e_right_joint: float, e_left_joint: float, right_estimate: float = 0.5
    ) -> list[float]:
        """Build a full 18D physical vector whose left gripper resolves to the given estimates.

        Arm dofs are zero; the right gripper is kept symmetric at ``right_estimate`` so
        only the left gripper carries the asymmetry under test.
        """

        physical = [0.0] * len(self.physical_order)

        def set_physical(name: str, virtual: str, estimate: float) -> None:
            physical[self.physical_order.index(name)] = (
                float(self.offsets[virtual][name])
                + estimate * float(self.coefficients[virtual][name])
            )

        set_physical("left_clamp_right_joint", "left_gripper_joint", e_right_joint)
        set_physical("left_clamp_left_joint", "left_gripper_joint", e_left_joint)
        set_physical("right_clamp_right_joint", "right_gripper_joint", right_estimate)
        set_physical("right_clamp_left_joint", "right_gripper_joint", right_estimate)
        return physical

    def test_projection_returns_vector_and_diagnostic_structure(self) -> None:
        physical = self._physical_with_left_estimates(0.2, 0.8)
        result = project_physical_to_virtual(physical, self.port, allow_unverified=True)
        self.assertEqual(len(result.vector), len(self.virtual_order))
        self.assertEqual(
            [gripper.virtual_name for gripper in result.grippers],
            ["left_gripper_joint", "right_gripper_joint"],
        )
        left = result.grippers[0]
        self.assertEqual(left.physical_names, ["left_clamp_right_joint", "left_clamp_left_joint"])
        self.assertAlmostEqual(left.estimates[0], 0.2, places=12)
        self.assertAlmostEqual(left.estimates[1], 0.8, places=12)
        self.assertAlmostEqual(left.projected_mean, 0.5, places=12)
        self.assertAlmostEqual(left.spread, 0.6, places=12)
        # Arm channels pass through unchanged.
        for name in self.virtual_order:
            if name in self.coefficients:
                continue
            self.assertAlmostEqual(
                result.vector[self.virtual_order.index(name)],
                0.0,
                places=12,
            )
        self.assertAlmostEqual(
            result.vector[self.virtual_order.index("left_gripper_joint")],
            0.5,
            places=12,
        )

    def test_projection_accepts_large_in_range_asymmetry(self) -> None:
        physical = self._physical_with_left_estimates(0.2, 0.8)
        result = project_physical_to_virtual(physical, self.port, allow_unverified=True)
        left = result.grippers[0]
        # Both estimates are inside [0, 1], so the projection accepts the asymmetry and
        # reports it as a residual rather than rejecting it.
        self.assertAlmostEqual(left.spread, 0.6, places=12)
        self.assertAlmostEqual(left.projected_mean, 0.5, places=12)
        # The same input must be rejected by the strict runtime adapter's default.
        with self.assertRaises(ContractError):
            physical_to_virtual(physical, self.port, allow_unverified=True)

    def test_projection_rejects_per_finger_out_of_range_even_when_mean_in_range(
        self,
    ) -> None:
        # Estimates 1.2 and -0.2 average to 0.5 (in range) but each finger is out of range.
        physical = self._physical_with_left_estimates(1.2, -0.2)
        with self.assertRaises(ContractError):
            project_physical_to_virtual(physical, self.port, allow_unverified=True)
        # Raising range_tolerance does not rescue a finger that is far out of range.
        with self.assertRaises(ContractError):
            project_physical_to_virtual(
                physical, self.port, allow_unverified=True, range_tolerance=0.003
            )

    def test_projection_clamps_only_bounded_range_noise(self) -> None:
        # A small negative estimate (-0.001) is inside the [-0.003, 1.003] band, so it is
        # clamped to 0 and averaged with 0.2 rather than rejected.
        physical = self._physical_with_left_estimates(-0.001, 0.2)
        result = project_physical_to_virtual(
            physical, self.port, allow_unverified=True, range_tolerance=0.003
        )
        left = result.grippers[0]
        self.assertAlmostEqual(left.projected_mean, 0.1, places=12)

    def test_projection_symmetric_roundtrip(self) -> None:
        virtual = self._virtual(0.3, 0.7)
        physical = virtual_to_physical(virtual, self.port, allow_unverified=True)
        result = project_physical_to_virtual(physical, self.port, allow_unverified=True)
        for expected, actual in zip(virtual, result.vector):
            self.assertAlmostEqual(expected, actual, places=12)
        for gripper in result.grippers:
            self.assertAlmostEqual(gripper.spread, 0.0, places=12)

    def _virtual(self, left: float, right: float) -> list[float]:
        values = [0.0] * len(self.virtual_order)
        values[self.virtual_order.index("left_gripper_joint")] = left
        values[self.virtual_order.index("right_gripper_joint")] = right
        return values


if __name__ == "__main__":
    unittest.main()
