import math
import unittest

from parcel_sorter.mobile_pi05_contract import (
    MOBILE_PI05_ABSOLUTE_ACTION_NAMES,
    MOBILE_PI05_ABSOLUTE_STATE_NAMES,
    MOBILE_PI05_RESIDUAL_ACTION_NAMES,
    MOBILE_PI05_STATE_NAMES,
    PI05ResidualContext,
    build_primitive_progress_targets,
    build_pi05_observable_context_task,
    build_pi05_recovery_residual,
    decode_pi05_absolute_action,
    decode_pi05_context,
    encode_pi05_absolute_state,
    encode_pi05_state,
    project_pi05_residual_action,
    select_pi05_mode_consensus,
    smooth_lift_residual_fraction,
)


def _legacy_state() -> tuple[float, ...]:
    return (0.0,) * 43


def _expert_action() -> tuple[float, ...]:
    arm = (0.4, 0.1, 0.3, 1.0, 0.0, 0.0, 0.0, 1.0)
    return (0.03, 0.0, 0.0, *arm, *arm)


class MobilePI05ContractTests(unittest.TestCase):
    def test_observable_context_task_is_stable_and_mode_blind(self) -> None:
        context = PI05ResidualContext(
            sealed_cup_mask=(False, False, False),
            parcel_shape="cylinder",
            parcel_size_m=(0.043, 0.043, 0.07),
            parcel_mass_kg=0.17,
            grasp_mode="side_suction",
            retry_index=2,
            stage="pregrasp",
            left_force_history_n=(),
            right_force_history_n=(),
            left_contact_anchor_m=(0.0, 0.0, 0.0),
            right_contact_anchor_m=(0.0, 0.0, 0.0),
            grasp_mode_conditioned=False,
        )
        task = build_pi05_observable_context_task("Recover the parcel.", context)
        self.assertIn("shape cylinder", task)
        self.assertIn("0.0430 x 0.0430 x 0.0700", task)
        self.assertIn("current phase pregrasp", task)
        self.assertNotIn("side_suction", task)
        self.assertEqual(build_pi05_observable_context_task(task, context), task)

    def test_mode_consensus_uses_votes_before_mean_logits(self) -> None:
        consensus = select_pi05_mode_consensus(
            (
                (3.0, 0.0, -1.0),
                (-0.5, 2.0, -1.0),
                (0.1, 0.0, -1.0),
            )
        )
        self.assertEqual(consensus.selected_mode, "top_suction")
        self.assertEqual(consensus.vote_counts, (2, 1, 0))
        self.assertAlmostEqual(consensus.consensus_fraction, 2 / 3)

    def test_mode_consensus_breaks_three_way_vote_tie_with_mean_logits(self) -> None:
        consensus = select_pi05_mode_consensus(
            (
                (1.0, 0.0, 0.0),
                (0.0, 3.0, 0.0),
                (0.0, 0.0, 2.0),
            )
        )
        self.assertEqual(consensus.selected_mode, "side_suction")
        self.assertEqual(consensus.vote_counts, (1, 1, 1))

    def test_mode_consensus_rejects_empty_samples(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least one"):
            select_pi05_mode_consensus(())

    def test_builds_monotonic_progress_per_contiguous_primitive(self) -> None:
        progress = build_primitive_progress_targets(
            ("pregrasp", "pregrasp", "pregrasp", "lift", "lift", "release")
        )
        self.assertEqual(progress, (0.0, 0.5, 1.0, 0.0, 1.0, 1.0))

    def test_lift_residual_schedule_matches_480_of_720_step_smoothstep(self) -> None:
        self.assertEqual(smooth_lift_residual_fraction(0.0), 0.0)
        self.assertAlmostEqual(smooth_lift_residual_fraction(1.0 / 3.0), 0.5)
        self.assertEqual(smooth_lift_residual_fraction(2.0 / 3.0), 1.0)
        self.assertEqual(smooth_lift_residual_fraction(1.0), 1.0)
        self.assertAlmostEqual(smooth_lift_residual_fraction(0.5, 0.8), 0.648)

    def test_builds_nonzero_verified_recovery_label(self) -> None:
        recovery = build_pi05_recovery_residual(
            contact_offset_m=(0.004, -0.003),
            contact_penetration_delta_m=0.001,
            approach_axis_world=(0.0, 0.0, 2.0),
            stage="grasp_approach",
            grasp_mode="top_suction",
        )
        self.assertEqual(
            recovery.left_contact_residual_m,
            (0.004, -0.003, 0.001),
        )
        self.assertEqual(recovery.right_contact_residual_m, (0.0, 0.0, 0.0))

    def test_cradle_recovery_is_common_mode_and_lift_bounded(self) -> None:
        recovery = build_pi05_recovery_residual(
            contact_offset_m=(0.008, 0.008),
            contact_penetration_delta_m=0.0,
            approach_axis_world=(0.0, 0.0, 1.0),
            stage="lift",
            grasp_mode="cooperative_cradle",
        )
        self.assertEqual(
            recovery.left_contact_residual_m,
            recovery.right_contact_residual_m,
        )
        self.assertAlmostEqual(
            math.dist(recovery.left_contact_residual_m, (0.0, 0.0, 0.0)),
            0.005000001,
        )

    def test_cradle_lift_allows_bounded_right_contact_recovery(self) -> None:
        recovery = build_pi05_recovery_residual(
            contact_offset_m=(0.0, 0.0),
            contact_penetration_delta_m=0.0,
            approach_axis_world=(0.0, 1.0, 0.0),
            right_contact_offset_m=(0.0, 0.008, 0.0),
            stage="lift",
            grasp_mode="cooperative_cradle",
        )
        self.assertAlmostEqual(
            math.dist(
                recovery.left_contact_residual_m,
                recovery.right_contact_residual_m,
            ),
            0.005000001,
        )
        self.assertLessEqual(
            math.dist(recovery.right_contact_residual_m, (0.0, 0.0, 0.0)),
            0.005000001,
        )

    def test_cradle_lift_supports_bounded_left_and_right_recovery(self) -> None:
        recovery = build_pi05_recovery_residual(
            contact_offset_m=(0.0, 0.0),
            contact_penetration_delta_m=0.0,
            approach_axis_world=(0.0, 1.0, 0.0),
            left_contact_offset_m=(0.0, 0.0, 0.002),
            right_contact_offset_m=(0.0, 0.002, -0.002),
            stage="lift",
            grasp_mode="cooperative_cradle",
        )
        self.assertGreater(recovery.left_contact_residual_m[2], 0.0)
        self.assertGreater(recovery.right_contact_residual_m[1], 0.0)
        self.assertLess(recovery.right_contact_residual_m[2], 0.0)
        self.assertLessEqual(
            math.dist(
                recovery.left_contact_residual_m,
                recovery.right_contact_residual_m,
            ),
            0.005000001,
        )

    def test_release_has_no_recovery_motion_label(self) -> None:
        recovery = build_pi05_recovery_residual(
            contact_offset_m=(0.004, -0.003),
            contact_penetration_delta_m=0.001,
            approach_axis_world=(0.0, 0.0, 1.0),
            stage="release",
            grasp_mode="cooperative_cradle",
        )
        self.assertEqual(recovery.left_contact_residual_m, (0.0, 0.0, 0.0))
        self.assertEqual(recovery.right_contact_residual_m, (0.0, 0.0, 0.0))

    def test_encodes_eighty_dimensional_observable_state(self) -> None:
        context = PI05ResidualContext(
            sealed_cup_mask=(True, False, True),
            parcel_shape="box",
            parcel_size_m=(0.1, 0.08, 0.04),
            parcel_mass_kg=0.5,
            grasp_mode="top_suction",
            retry_index=1,
            stage="grasp_approach",
            left_force_history_n=(2.0, 3.0),
            right_force_history_n=(1.0,),
            left_contact_anchor_m=(0.4, 0.1, 0.3),
            right_contact_anchor_m=(0.4, -0.1, 0.3),
        )
        encoded = encode_pi05_state(_legacy_state(), context)
        self.assertEqual(len(MOBILE_PI05_STATE_NAMES), 80)
        self.assertEqual(len(encoded), 80)
        self.assertEqual(encoded[43:46], (1.0, 0.0, 1.0))
        self.assertEqual(encoded[-18:-12], (0.0, 0.0, 0.0, 0.0, 2.0, 3.0))
        decoded = decode_pi05_context(encoded)
        self.assertEqual(decoded.grasp_mode, context.grasp_mode)
        self.assertEqual(decoded.stage, context.stage)
        self.assertEqual(decoded.sealed_cup_mask, context.sealed_cup_mask)

    def test_unconditioned_pregrasp_hides_mode_input_for_vla_selection(self) -> None:
        context = PI05ResidualContext(
            sealed_cup_mask=(False, False, False),
            parcel_shape="cylinder",
            parcel_size_m=(0.09, 0.09, 0.35),
            parcel_mass_kg=1.2,
            grasp_mode="cooperative_cradle",
            retry_index=0,
            stage="pregrasp",
            left_force_history_n=(),
            right_force_history_n=(),
            left_contact_anchor_m=(0.0, 0.0, 0.0),
            right_contact_anchor_m=(0.0, 0.0, 0.0),
            grasp_mode_conditioned=False,
        )
        encoded = encode_pi05_state(_legacy_state(), context)
        self.assertEqual(encoded[52:55], (0.0, 0.0, 0.0))
        self.assertFalse(decode_pi05_context(encoded).grasp_mode_conditioned)

    def test_absolute_state_uses_current_tools_not_action_anchors(self) -> None:
        legacy = list(_legacy_state())
        legacy[24:27] = (0.31, 0.12, 0.44)
        legacy[31:34] = (0.29, -0.11, 0.42)
        context = PI05ResidualContext(
            sealed_cup_mask=(False, False, False),
            parcel_shape="box",
            parcel_size_m=(0.1, 0.08, 0.04),
            parcel_mass_kg=0.5,
            grasp_mode="top_suction",
            retry_index=0,
            stage="pregrasp",
            left_force_history_n=(),
            right_force_history_n=(),
            left_contact_anchor_m=(9.0, 9.0, 9.0),
            right_contact_anchor_m=(-9.0, -9.0, -9.0),
            grasp_mode_conditioned=False,
        )

        encoded = encode_pi05_absolute_state(legacy, context)

        self.assertEqual(len(encoded), len(MOBILE_PI05_ABSOLUTE_STATE_NAMES))
        self.assertEqual(encoded[-6:-3], (0.31, 0.12, 0.44))
        self.assertEqual(encoded[-3:], (0.29, -0.11, 0.42))
        self.assertEqual(encoded[52:55], (0.0, 0.0, 0.0))

    def test_absolute_action_decode_never_reads_an_expert_reference(self) -> None:
        action = list(_expert_action())
        action.extend((-1.0, 3.0, -2.0, 1.2))

        projection = decode_pi05_absolute_action(action)

        self.assertEqual(len(action), len(MOBILE_PI05_ABSOLUTE_ACTION_NAMES))
        self.assertEqual(projection.absolute_action, _expert_action())
        self.assertEqual(projection.predicted_mode, "side_suction")
        self.assertEqual(projection.progress, 1.0)

    def test_pregrasp_residual_is_bounded_and_orientation_is_locked(self) -> None:
        raw = [0.0] * len(MOBILE_PI05_RESIDUAL_ACTION_NAMES)
        raw[0] = 0.20
        raw[3:6] = (0.03, 0.04, 0.0)
        raw[9:12] = (0.0, 2.0, 1.0)
        raw[12] = -1.0
        raw[13] = 1.4
        projection = project_pi05_residual_action(
            raw,
            _expert_action(),
            stage="pregrasp",
            grasp_mode="top_suction",
        )
        self.assertAlmostEqual(math.dist(projection.absolute_action[3:6], (0.4, 0.1, 0.3)), 0.02)
        self.assertEqual(projection.absolute_action[6:11], _expert_action()[6:11])
        self.assertEqual(projection.absolute_action[11:14], _expert_action()[11:14])
        self.assertEqual(projection.predicted_mode, "side_suction")
        self.assertEqual(projection.mode_logits, (0.0, 2.0, 1.0))
        self.assertFalse(projection.requested_suction)
        self.assertEqual(projection.progress, 1.0)

    def test_grasp_lift_bounds_cradle_common_and_differential_motion(self) -> None:
        raw = [0.0] * len(MOBILE_PI05_RESIDUAL_ACTION_NAMES)
        raw[3:6] = (0.010, 0.0, 0.0)
        raw[6:9] = (0.0, 0.010, 0.0)
        projection = project_pi05_residual_action(
            raw,
            _expert_action(),
            stage="lift",
            grasp_mode="cooperative_cradle",
        )
        self.assertLessEqual(
            math.dist(projection.left_contact_residual_m, (0.0, 0.0, 0.0)),
            0.005000001,
        )
        self.assertLessEqual(
            math.dist(projection.right_contact_residual_m, (0.0, 0.0, 0.0)),
            0.005000001,
        )
        self.assertLessEqual(
            math.dist(
                projection.left_contact_residual_m,
                projection.right_contact_residual_m,
            ),
            0.005000001,
        )

    def test_release_ignores_learned_motion_and_tool_intent(self) -> None:
        raw = [1.0] * len(MOBILE_PI05_RESIDUAL_ACTION_NAMES)
        projection = project_pi05_residual_action(
            raw,
            _expert_action(),
            stage="release",
            grasp_mode="cooperative_cradle",
        )
        self.assertEqual(projection.absolute_action, _expert_action())


if __name__ == "__main__":
    unittest.main()
