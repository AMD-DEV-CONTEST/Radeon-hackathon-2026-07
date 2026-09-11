import math
import unittest

from parcel_sorter.mobile_dual_arm_projection import (
    project_dual_arm_residuals,
    transport_arm_authority,
)


class DualArmProjectionTests(unittest.TestCase):
    def test_cooperative_projection_preserves_tool_separation(self) -> None:
        projection = project_dual_arm_residuals(
            left_proposal_m=(0.05, 0.02, 0.01),
            right_proposal_m=(0.03, -0.01, 0.02),
            left_anchor_m=(0.00, 0.10, 0.50),
            right_anchor_m=(0.00, -0.10, 0.50),
            authority_scale=1.0,
            cooperative_carry=True,
        )
        self.assertEqual(projection.differential_residual_m, (0.0, 0.0, 0.0))
        self.assertAlmostEqual(projection.separation_change_m, 0.0, places=12)
        self.assertAlmostEqual(
            math.dist(projection.left_target_m, (0.00, 0.10, 0.50)),
            0.01,
            places=12,
        )
        self.assertIn("cooperative_rigid_span_lock", projection.reasons)

    def test_noncooperative_differential_motion_is_bounded(self) -> None:
        projection = project_dual_arm_residuals(
            left_proposal_m=(0.04, 0.10, 0.50),
            right_proposal_m=(-0.04, -0.10, 0.50),
            left_anchor_m=(0.00, 0.10, 0.50),
            right_anchor_m=(0.00, -0.10, 0.50),
            authority_scale=1.0,
            cooperative_carry=False,
        )
        self.assertLessEqual(math.dist(projection.differential_residual_m, (0, 0, 0)), 0.0015)
        self.assertLessEqual(projection.separation_change_m, 0.0030001)

    def test_authority_fades_before_placement_and_fails_closed(self) -> None:
        self.assertEqual(transport_arm_authority(stage="place", remaining_distance_m=0.30), 0.0)
        self.assertEqual(transport_arm_authority(stage="transport", remaining_distance_m=None), 0.0)
        self.assertEqual(transport_arm_authority(stage="transport", remaining_distance_m=0.025), 0.0)
        self.assertEqual(transport_arm_authority(stage="transport", remaining_distance_m=0.120), 1.0)
        self.assertGreater(
            transport_arm_authority(stage="transport", remaining_distance_m=0.080),
            0.0,
        )


if __name__ == "__main__":
    unittest.main()
