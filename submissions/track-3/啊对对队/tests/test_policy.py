import unittest

from parcel_sorter.contracts import ControlDecision, PolicyContext, RobotState
from parcel_sorter.policy import _safe_cartesian_action


class LearnedPolicySafetyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.state = RobotState(
            joint_positions=(0.0,) * 9,
            end_effector_pose=(0.5, 0.0, 0.2, 1.0, 0.0, 0.0, 0.0),
            parcel_pose=(0.6, 0.0, 0.02, 1.0, 0.0, 0.0, 0.0),
            target_position=(0.48, -0.34, 0.025),
            gripper_contact_force_n=0.0,
        )

    def context(self, command: str) -> PolicyContext:
        return PolicyContext(
            decision=ControlDecision("test", command, "test", 0),
            state=self.state,
            task="sort parcel",
        )

    def test_bounds_motion_and_overrides_gripper_during_approach(self) -> None:
        action = _safe_cartesian_action(
            (1.0, 0.0, 0.2, 0.0, 2.0, 0.0, 0.0, -1.0),
            self.context("move_pregrasp"),
            0.04,
        )

        self.assertAlmostEqual(action.target_position[0], 0.54)
        self.assertEqual(action.target_quaternion, (0.0, 1.0, 0.0, 0.0))
        self.assertGreater(action.gripper, 0)

    def test_stop_holds_position_without_using_model_values(self) -> None:
        action = _safe_cartesian_action((), self.context("stop"), 0.04)

        self.assertEqual(action.target_position, self.state.end_effector_pose[:3])
        self.assertEqual(action.command, "stop")

    def test_rejects_non_finite_model_action(self) -> None:
        with self.assertRaises(ValueError):
            _safe_cartesian_action(
                (0.5, 0.0, float("nan"), 0.0, 1.0, 0.0, 0.0, 1.0),
                self.context("move_lift"),
                0.04,
            )


if __name__ == "__main__":
    unittest.main()
