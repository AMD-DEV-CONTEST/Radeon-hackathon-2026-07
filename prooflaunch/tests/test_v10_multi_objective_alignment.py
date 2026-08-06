from __future__ import annotations

import unittest

from prooflaunch_remix.v10_contracts import V10ContractError
from prooflaunch_remix.v10_multi_objective_alignment import (
    AlignmentBudget,
    AlignmentMethod,
    AlignmentMonitorObservation,
    AlignmentRunReceipt,
    CalibrationCurve,
    FeedbackKind,
    NormalizationBounds,
    RewardDimension,
    RewardVector,
    RichFeedback,
    VerifierKind,
    VerifierReceipt,
    alignment_monitor_failures,
    alignment_promotion_eligible,
    calibrate_probability,
    default_alignment_methods,
    default_safety_policy,
    normalize_reward_values,
    pareto_select,
    planned_alignment_card,
    tokenize_rich_feedback,
    verifier_quorum_passes,
)


SHA_A = "a" * 64


def vector(candidate_id: str, *, safety: float = 1.0, delta: float = 0.0) -> RewardVector:
    values = {item: min(1.0, 0.7 + delta) for item in RewardDimension}
    values.update(
        {
            RewardDimension.SAFETY: safety,
            RewardDimension.EVIDENCE: 1.0,
            RewardDimension.IDENTITY: 1.0,
            RewardDimension.STOP: 1.0,
        }
    )
    return RewardVector(candidate_id, values, {item: f"evidence/{item.value}" for item in RewardDimension}, True)


class RewardContractTests(unittest.TestCase):
    def test_reward_vector_has_all_thirteen_located_dimensions(self) -> None:
        item = vector("candidate-a")
        self.assertEqual(set(item.values), set(RewardDimension))
        self.assertEqual(len(item.values), 13)
        self.assertEqual(len(item.digest), 64)
        with self.assertRaisesRegex(V10ContractError, "every dimension"):
            RewardVector("bad", {RewardDimension.SAFETY: 1.0}, {RewardDimension.SAFETY: "x"}, True)

    def test_safety_is_lexicographic_then_pareto_without_scalar_flattening(self) -> None:
        unsafe = vector("unsafe-but-pretty", safety=0.98, delta=0.30)
        dominated = vector("dominated", delta=-0.10)
        frontier = vector("frontier", delta=0.10)
        selected = pareto_select((unsafe, dominated, frontier))
        self.assertEqual(tuple(item.candidate_id for item in selected), ("frontier",))
        self.assertFalse(default_safety_policy().scalar_flattening_allowed)

    def test_frozen_normalization_and_monotonic_calibration(self) -> None:
        bounds = NormalizationBounds(
            {item: 0.0 for item in RewardDimension},
            {item: 10.0 for item in RewardDimension},
        )
        normalized = normalize_reward_values({item: 5.0 for item in RewardDimension}, bounds)
        self.assertTrue(all(value == 0.5 for value in normalized.values()))
        curve = CalibrationCurve((0.0, 0.5, 1.0), (0.0, 0.4, 1.0), SHA_A)
        self.assertAlmostEqual(calibrate_probability(0.75, curve), 0.7)


class FeedbackAndMethodTests(unittest.TestCase):
    def test_audit_tool_and_human_feedback_are_tokenized_and_rights_gated(self) -> None:
        for kind in FeedbackKind:
            item = RichFeedback(kind, "visible issue", "rule-1", "artifact#locator", "repair locally", True)
            tokens = tokenize_rich_feedback(item)
            self.assertIn(kind.value, tokens[0])
            self.assertIn("artifact#locator", tokens[2])
        with self.assertRaisesRegex(V10ContractError, "approved"):
            tokenize_rich_feedback(RichFeedback(FeedbackKind.HUMAN_CRITIQUE, "x", "r", "l", "fix", False))

    def test_orpo_simpo_mdpo_and_micro_grpo_are_distinct_and_two_hour_bounded(self) -> None:
        methods = default_alignment_methods()
        self.assertEqual({item.method for item in methods}, set(AlignmentMethod))
        self.assertEqual(len({item.objective for item in methods}), 4)
        self.assertTrue(next(item for item in methods if item.method is AlignmentMethod.MDPO).multimodal_conditioned)
        self.assertEqual(next(item for item in methods if item.method is AlignmentMethod.MICRO_GRPO).group_size, 4)
        self.assertEqual(AlignmentBudget().wall_clock_seconds, 7_200)


class VerificationAndPromotionTests(unittest.TestCase):
    def test_five_hacking_monitors_trip_independently(self) -> None:
        failures = alignment_monitor_failures(AlignmentMonitorObservation(0.5, -0.8, 0.1, 0.5, 0.4))
        self.assertEqual(
            set(failures),
            {"reward_hacking", "length_hacking", "tool_call_hacking", "judge_gaming", "visual_metric_gaming"},
        )

    def test_adversarial_heldout_and_human_spotcheck_form_independent_quorum(self) -> None:
        receipts = tuple(
            VerifierReceipt(kind, f"{kind.value}@frozen", character * 64, 10, 10, True, True)
            for kind, character in zip(VerifierKind, ("a", "b", "c"))
        )
        self.assertTrue(verifier_quorum_passes(receipts, 100))
        self.assertFalse(verifier_quorum_passes(receipts, 1_000))

    def test_regression_or_unobserved_run_is_eliminated_and_card_stays_null(self) -> None:
        unobserved = AlignmentRunReceipt(AlignmentMethod.MICRO_GRPO, False, None, None, None, (), None)
        regressed = AlignmentRunReceipt(AlignmentMethod.MICRO_GRPO, True, SHA_A, SHA_A, SHA_A, (), True)
        passed = AlignmentRunReceipt(AlignmentMethod.MICRO_GRPO, True, SHA_A, SHA_A, SHA_A, (), False)
        self.assertFalse(alignment_promotion_eligible(unobserved))
        self.assertFalse(alignment_promotion_eligible(regressed))
        self.assertTrue(alignment_promotion_eligible(passed))
        card = planned_alignment_card()
        self.assertFalse(card["promotion_eligible"])
        for key in ("policy_gain", "trajectory_gain", "visual_gain", "calibration_gain", "inference_cost", "selected_adapter"):
            self.assertIsNone(card[key])


if __name__ == "__main__":
    unittest.main()

