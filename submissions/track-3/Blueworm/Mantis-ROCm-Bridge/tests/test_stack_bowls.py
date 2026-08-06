from __future__ import annotations

import unittest

from mantis_rocm_bridge.stack_bowls import (
    StackStabilityTracker,
    evaluate_legacy_source,
    evaluate_strict_target_frame,
)
from mantis_rocm_bridge.stack_bowls_env import (
    arm_for_bowl_x,
    sample_source_reset_poses,
    validate_source_reset_poses,
)


ZERO_VELOCITIES = [[0.0, 0.0, 0.0]] * 3


class StackBowlEvaluatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.canonical = [
            [0.0, -0.1, 0.74],
            [0.0, -0.1, 0.77],
            [0.0, -0.1, 0.81],
        ]

    def strict_frame(self, positions=None, **kwargs):
        return evaluate_strict_target_frame(
            positions or self.canonical,
            ZERO_VELOCITIES,
            ZERO_VELOCITIES,
            left_gripper_open_fraction=kwargs.pop("left_gripper_open_fraction", 1.0),
            right_gripper_open_fraction=kwargs.pop("right_gripper_open_fraction", 1.0),
            **kwargs,
        )

    def test_canonical_stack_passes_both_frame_protocols(self) -> None:
        legacy = evaluate_legacy_source(
            self.canonical,
            left_gripper_open=True,
            right_gripper_open=True,
        )
        strict = self.strict_frame()
        self.assertTrue(legacy["success"])
        self.assertEqual(legacy["graded_score"], 1.0)
        self.assertTrue(strict["frame_success"])

    def test_one_sided_legacy_height_bug_is_preserved_but_strict_rejects_it(self) -> None:
        implausibly_low = [
            [0.0, -0.1, 0.10],
            [0.0, -0.1, 0.13],
            [0.0, -0.1, 0.17],
        ]
        legacy = evaluate_legacy_source(
            implausibly_low,
            left_gripper_open=True,
            right_gripper_open=True,
        )
        strict = self.strict_frame(implausibly_low)
        self.assertTrue(legacy["success"])
        self.assertFalse(strict["frame_success"])
        self.assertFalse(strict["checks"]["absolute_heights"])

    def test_xy_misalignment_and_closed_gripper_are_rejected(self) -> None:
        misaligned = [row[:] for row in self.canonical]
        misaligned[2][0] = 0.04
        self.assertFalse(self.strict_frame(misaligned)["frame_success"])
        self.assertFalse(
            self.strict_frame(left_gripper_open_fraction=0.89)["frame_success"]
        )

    def test_motion_must_be_below_strict_threshold(self) -> None:
        moving = [[0.02, 0.0, 0.0], [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]]
        result = evaluate_strict_target_frame(
            self.canonical,
            moving,
            ZERO_VELOCITIES,
            left_gripper_open_fraction=1.0,
            right_gripper_open_fraction=1.0,
        )
        self.assertFalse(result["frame_success"])

    def test_stability_tracker_requires_consecutive_frames_and_resets(self) -> None:
        tracker = StackStabilityTracker(required_frames=12)
        for _ in range(11):
            self.assertFalse(tracker.update(True))
        self.assertTrue(tracker.update(True))
        self.assertFalse(tracker.update(False))
        self.assertEqual(tracker.consecutive_frames, 0)

    def test_non_finite_state_is_rejected(self) -> None:
        invalid = [row[:] for row in self.canonical]
        invalid[0][0] = float("nan")
        with self.assertRaises(ValueError):
            self.strict_frame(invalid)


class StackBowlResetTests(unittest.TestCase):
    def test_numpy_randomstate_seed_zero_matches_frozen_source_sequence(self) -> None:
        try:
            poses = sample_source_reset_poses(seed=0)
        except RuntimeError as exc:
            if "requires NumPy" in str(exc):
                self.skipTest("NumPy is not installed in this minimal test interpreter")
            raise
        self.assertEqual([pose.source_sample_index for pose in poses], [1, 0, 2])
        self.assertEqual([pose.accepted_attempt for pose in poses], [2, 3, 1])
        expected = [
            (-0.24772242017907556, -0.14393448076790227, 0.741),
            (0.27819765630061755, -0.034967544352266684, 0.741),
            (0.16689405056991027, 0.11100364447404575, 0.741),
        ]
        for pose, target in zip(poses, expected):
            for actual, wanted in zip(pose.position_xyz_m, target):
                self.assertAlmostEqual(actual, wanted, places=15)

    def test_reference_seeds_obey_every_reset_invariant(self) -> None:
        try:
            for seed in (0, 1, 42, 20260722):
                validate_source_reset_poses(sample_source_reset_poses(seed=seed))
        except RuntimeError as exc:
            if "requires NumPy" in str(exc):
                self.skipTest("NumPy is not installed in this minimal test interpreter")
            raise

    def test_seed_and_injected_rng_are_mutually_exclusive(self) -> None:
        with self.assertRaises(ValueError):
            sample_source_reset_poses()
        with self.assertRaises(ValueError):
            sample_source_reset_poses(seed=0, rng=object())  # type: ignore[arg-type]

    def test_source_arm_boundary_is_preserved(self) -> None:
        self.assertEqual(arm_for_bowl_x(-1e-9), "left")
        self.assertEqual(arm_for_bowl_x(0.0), "right")
        self.assertEqual(arm_for_bowl_x(0.2), "right")


if __name__ == "__main__":
    unittest.main()
