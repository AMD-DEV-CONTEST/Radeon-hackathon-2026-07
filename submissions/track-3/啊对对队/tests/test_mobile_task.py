import math
import unittest

from parcel_sorter.mobile_task import (
    MOBILE_BIMANUAL_ACTION_DIM,
    MobileBimanualTaskSupervisor,
    MobileTaskObservation,
    clamp_position_residual_to_anchor,
    decode_mobile_bimanual_action,
    limit_mobile_arm_step,
    placement_within_release_gate,
    update_release_gate_stability,
)


class MobileBimanualActionTests(unittest.TestCase):
    def test_placement_release_gate_uses_xy_and_z_tolerances(self) -> None:
        expected = (0.30, 0.75, 1.44)
        self.assertTrue(
            placement_within_release_gate((0.3187, 0.7375, 1.4399), expected)
        )
        self.assertFalse(
            placement_within_release_gate((0.35, 0.75, 1.44), expected)
        )
        self.assertFalse(
            placement_within_release_gate((0.30, 0.75, 1.47), expected)
        )

    def test_release_gate_stability_applies_to_every_grasp_mode(self) -> None:
        consecutive = 0
        completed = False
        for _ in range(24):
            consecutive, completed = update_release_gate_stability(
                attached=True,
                inside_release_gate=True,
                consecutive_steps=consecutive,
            )
        self.assertEqual(consecutive, 24)
        self.assertTrue(completed)

        consecutive, completed = update_release_gate_stability(
            attached=True,
            inside_release_gate=False,
            consecutive_steps=consecutive,
        )
        self.assertEqual(consecutive, 0)
        self.assertFalse(completed)

        with self.assertRaisesRegex(ValueError, "required_steps"):
            update_release_gate_stability(
                attached=True,
                inside_release_gate=True,
                consecutive_steps=0,
                required_steps=0,
            )

    def test_clamps_cumulative_arm_residual_about_frozen_anchor(self) -> None:
        anchor = (0.40, 0.10, 0.30)
        bounded = clamp_position_residual_to_anchor((0.43, 0.10, 0.30), anchor)
        self.assertAlmostEqual(math.dist(bounded, anchor), 0.01)
        self.assertEqual(
            clamp_position_residual_to_anchor((0.405, 0.10, 0.30), anchor),
            (0.405, 0.10, 0.30),
        )

    def test_decodes_normalizes_and_bounds_nineteen_dimensional_action(self) -> None:
        arm = (0.4, 0.1, 0.2, 2.0, 0.0, 0.0, 0.0, -0.2)
        action = decode_mobile_bimanual_action((1.0, 1.0, 4.0, *arm, *arm))
        self.assertEqual(MOBILE_BIMANUAL_ACTION_DIM, 19)
        self.assertAlmostEqual(math.hypot(*action.base_velocity_xy_yaw[:2]), 0.35)
        self.assertEqual(action.base_velocity_xy_yaw[2], 1.0)
        self.assertEqual(action.left.quaternion_wxyz, (1.0, 0.0, 0.0, 0.0))
        self.assertEqual(action.left.gripper, -1.0)

    def test_rejects_invalid_action_and_limits_cartesian_step(self) -> None:
        with self.assertRaisesRegex(ValueError, "19"):
            decode_mobile_bimanual_action((0.0,) * 18)
        arm = (0.2, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0)
        bounded = limit_mobile_arm_step(
            decode_mobile_bimanual_action((0.0, 0.0, 0.0, *arm, *arm)).left,
            (0.0, 0.0, 0.0),
        )
        self.assertAlmostEqual(bounded.position_m[0], 0.04)


class MobileTaskSupervisorTests(unittest.TestCase):
    def test_completes_navigation_bimanual_pick_transport_and_place(self) -> None:
        supervisor = MobileBimanualTaskSupervisor()
        observations = (
            MobileTaskObservation(base_at_pickup=True),
            MobileTaskObservation(arms_at_pregrasp=True),
            MobileTaskObservation(left_grasp_contact=True, right_grasp_contact=True),
            MobileTaskObservation(parcel_lifted=True),
            MobileTaskObservation(base_at_destination=True),
            MobileTaskObservation(parcel_placed=True),
            MobileTaskObservation(grippers_open=True),
            MobileTaskObservation(arms_retreated=True),
        )
        decision = None
        for observation in observations:
            decision = supervisor.step(observation)
        self.assertIsNotNone(decision)
        self.assertEqual(decision.stage, "complete")

    def test_force_gate_aborts_without_using_retry_budget(self) -> None:
        supervisor = MobileBimanualTaskSupervisor(max_retries=2)
        decision = supervisor.step(MobileTaskObservation(excessive_contact_force=True))
        self.assertEqual(decision.stage, "abort")
        self.assertEqual(decision.retry_count, 0)

    def test_drop_retries_then_aborts(self) -> None:
        supervisor = MobileBimanualTaskSupervisor(max_retries=1)
        self.assertEqual(
            supervisor.step(MobileTaskObservation(parcel_dropped=True)).stage,
            "navigate_pickup",
        )
        self.assertEqual(
            supervisor.step(MobileTaskObservation(parcel_dropped=True)).stage,
            "abort",
        )


if __name__ == "__main__":
    unittest.main()
