from __future__ import annotations

import unittest

from prooflaunch_remix.v10_contracts import V10ContractError
from prooflaunch_remix.v10_distillation import OutputRightsStatus
from prooflaunch_remix.v10_distillation_stack import (
    DistillationControl,
    DistillationLane,
    HiddenFeaturePair,
    LayoutTarget,
    MatchedControlMatrix,
    SourceAssetPolicy,
    TeacherCandidate,
    TemporalTarget,
    VisibleAgentTarget,
    VisualCropTarget,
    capability_retention,
    default_control_arms,
    default_lane_specs,
    expected_calibration_error,
    freeze_distillation_stack_v1,
    logits_kl_loss,
    planned_distillation_stack_card,
    teacher_elimination_reasons,
    token_efficiency,
    wall_clock_benefit,
)


SHA_A = "a" * 64
SHA_B = "b" * 64


def matrix() -> MatchedControlMatrix:
    return MatchedControlMatrix(
        arms=default_control_arms(),
        base_revision="student@frozen",
        dataset_sha256=SHA_A,
        evaluation_sha256=SHA_B,
        hardware_fingerprint="radeon@frozen",
        seed=42,
        maximum_train_tokens=1000,
    )


class LaneContractTests(unittest.TestCase):
    def test_exact_twelve_distillation_lanes_are_unique_bounded_and_objective(self) -> None:
        specs = default_lane_specs()
        self.assertEqual(len(specs), 12)
        self.assertEqual({item.lane for item in specs}, set(DistillationLane))
        self.assertTrue(all(item.maximum_gpu_seconds == 7_200 for item in specs))
        self.assertTrue(all(len(item.objective_metrics) >= 2 for item in specs))
        self.assertTrue(all(not item.hidden_reasoning_allowed for item in specs))

    def test_logits_kl_and_projected_hidden_feature_loss_are_computed(self) -> None:
        self.assertGreater(logits_kl_loss((0.7, 0.3), (0.4, 0.6)), 0)
        self.assertAlmostEqual(logits_kl_loss((0.7, 0.3), (0.7, 0.3)), 0)
        features = HiddenFeaturePair(
            teacher=(1.0, 2.0, 100.0),
            student_projected=(0.0, 4.0, -100.0),
            projection_revision="projection@sha",
            attention_mask=(True, True, False),
        )
        self.assertEqual(features.masked_mse(), 2.5)
        with self.assertRaisesRegex(V10ContractError, "align"):
            HiddenFeaturePair((1.0,), (1.0, 2.0), "p", (True,))

    def test_visual_layout_and_temporal_targets_are_source_bound(self) -> None:
        crop = VisualCropTarget(
            SHA_A, (0.1, 0.2, 0.8, 0.9), "product", OutputRightsStatus.APPROVED
        )
        self.assertEqual(crop.label, "product")
        layout = LayoutTarget(SHA_A, ("h", "cta"), (("h", "cta"),), ("h", "cta"))
        self.assertEqual(layout.reading_order[-1], "cta")
        temporal = TemporalTarget(SHA_B, (0, 500, 900), ("a", "b", "c"), 1000)
        self.assertEqual(temporal.event_ids[1], "b")
        with self.assertRaisesRegex(V10ContractError, "increasing"):
            TemporalTarget(SHA_B, (0, 0), ("a", "b"), 1000)

    def test_agent_craft_audit_and_workflow_targets_are_visible_and_rights_gated(self) -> None:
        derived = {
            item.lane
            for item in default_lane_specs()
            if item.source_asset_policy is SourceAssetPolicy.DERIVED_ABSTRACTION
        }
        self.assertEqual(
            derived,
            {
                DistillationLane.AGENT_PLAN,
                DistillationLane.AGENT_TOOL,
                DistillationLane.AGENT_STOP,
                DistillationLane.FAILURE_ATTRIBUTION,
                DistillationLane.FOUR_A_CRITIQUE,
                DistillationLane.AUDIT_REPAIR,
                DistillationLane.MATURE_WORKFLOW,
            },
        )
        target = VisibleAgentTarget(
            DistillationLane.FOUR_A_CRITIQUE,
            "task-1",
            SHA_A,
            {"rubric_scores": {"strategy": 4}, "finding": "unsupported claim"},
            False,
            OutputRightsStatus.APPROVED,
        )
        self.assertIn("finding", target.target_event)
        with self.assertRaisesRegex(V10ContractError, "forbidden"):
            VisibleAgentTarget(
                DistillationLane.AGENT_PLAN,
                "task-2",
                SHA_A,
                {"chain_of_thought": "private"},
                False,
                OutputRightsStatus.APPROVED,
            )


class ControlAndMetricTests(unittest.TestCase):
    def test_exact_five_matched_controls_include_caopd_self_and_no_kd(self) -> None:
        controls = matrix()
        self.assertEqual({item.control for item in controls.arms}, set(DistillationControl))
        by_control = {item.control: item for item in controls.arms}
        self.assertTrue(by_control[DistillationControl.CAOPD].teacher_required)
        self.assertTrue(by_control[DistillationControl.SELF_KD].student_generated_rollouts)
        self.assertFalse(by_control[DistillationControl.NO_KD].teacher_required)

    def test_capability_retention_does_not_allow_gains_to_hide_regressions(self) -> None:
        value = capability_retention(
            {"vision": 0.8, "agent": 0.8},
            {"vision": 1.0, "agent": 0.4},
        )
        self.assertAlmostEqual(value, 0.75)

    def test_calibration_token_and_wall_clock_metrics_are_mechanical(self) -> None:
        self.assertAlmostEqual(
            expected_calibration_error((0.8, 0.6), (1, 0), (1, 1), bins=5),
            0.4,
        )
        self.assertEqual(token_efficiency(5, 100), 50.0)
        self.assertEqual(wall_clock_benefit(120, 60), 2.0)

    def test_unverified_unlicensed_or_no_information_teacher_is_eliminated(self) -> None:
        candidate = TeacherCandidate(
            "minimax-unresolved-h3-claim",
            "UNRESOLVED",
            False,
            OutputRightsStatus.REVIEW_REQUIRED,
            0.0,
            2,
        )
        self.assertEqual(
            set(teacher_elimination_reasons(candidate)),
            {
                "unverified_teacher_revision",
                "output_rights_not_approved",
                "teacher_adds_no_new_information",
                "insufficient_observed_examples",
            },
        )

    def test_planned_card_and_frozen_stack_never_claim_runtime_results(self) -> None:
        card = planned_distillation_stack_card(default_lane_specs(), matrix())
        self.assertFalse(card["training_observed"])
        self.assertFalse(card["radeon_execution_observed"])
        self.assertFalse(card["promotion_eligible"])
        for field in (
            "capability_retention",
            "expected_calibration_error",
            "token_efficiency_per_1k",
            "wall_clock_benefit",
            "selected_teacher",
            "selected_control",
            "selected_adapter",
        ):
            self.assertIsNone(card[field])
        stack = freeze_distillation_stack_v1()
        self.assertEqual(len(stack["lanes"]), 12)
        self.assertEqual(len(stack["controls"]["arms"]), 5)
        self.assertEqual(len(stack["content_sha256"]), 64)
        self.assertFalse(stack["runtime_truth"]["training_observed"])


if __name__ == "__main__":
    unittest.main()
