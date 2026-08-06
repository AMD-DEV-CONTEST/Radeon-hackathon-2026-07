from __future__ import annotations

import unittest

from prooflaunch_remix.v10_contracts import V10ContractError
from prooflaunch_remix.v10_on_policy_distillation import (
    CorrectionTokenKind,
    ExperimentBudget,
    FrozenRevisionPair,
    KDMethod,
    MethodRunReceipt,
    MonitoringObservation,
    PrivilegedKind,
    PrivilegedSignalSpec,
    RolloutContract,
    TemporalStageKind,
    clip_pointwise_kl,
    compute_divergence_diagnostics,
    default_deployment_contract,
    default_method_specs,
    default_protection_policy,
    default_temporal_curriculum,
    monitor_failures,
    planned_distillation_card,
    promotion_eligible,
)


SHA_A = "a" * 64
SHA_B = "b" * 64


class MethodAndInputContractTests(unittest.TestCase):
    def test_all_eight_kd_and_control_methods_are_distinct_and_frozen(self) -> None:
        specs = default_method_specs()
        self.assertEqual({item.method for item in specs}, set(KDMethod))
        self.assertEqual(len(specs), 8)
        by_method = {item.method: item for item in specs}
        self.assertTrue(by_method[KDMethod.TCOD].temporal_curriculum)
        self.assertTrue(by_method[KDMethod.OPSD].self_teacher)
        self.assertFalse(by_method[KDMethod.NO_KD].teacher_required)

    def test_privileged_evidence_critique_and_repair_are_deployment_isolated(self) -> None:
        contract = default_deployment_contract()
        self.assertEqual(set(contract.privileged_fields), {item.value for item in PrivilegedKind})
        self.assertFalse(set(contract.deployment_fields) & set(contract.privileged_fields))
        for kind in PrivilegedKind:
            signal = PrivilegedSignalSpec(kind, SHA_A, f"private/{kind.value}.json")
            self.assertTrue(signal.training_only)

    def test_student_rollout_is_teacher_evaluated_without_hidden_reasoning(self) -> None:
        rollout = RolloutContract(
            rollout_id="rollout-0001",
            student_revision="student@frozen",
            teacher_revision="teacher@frozen",
            deployment_input_sha256=SHA_A,
            teacher_evaluation_sha256=SHA_B,
            student_generated=True,
            teacher_evaluates_student_rollout=True,
            hidden_reasoning_persisted=False,
            output_rights_approved=True,
        )
        self.assertEqual(len(rollout.digest), 64)
        with self.assertRaisesRegex(V10ContractError, "rights"):
            RolloutContract(**{**rollout.__dict__, "output_rights_approved": False})


class DiagnosticsAndCurriculumTests(unittest.TestCase):
    def test_forward_reverse_jsd_overlap_advantage_and_entropy_are_computed(self) -> None:
        item = compute_divergence_diagnostics(
            (0.70, 0.20, 0.10),
            (0.40, 0.35, 0.25),
            target_index=0,
            top_k=2,
        )
        self.assertGreater(item.forward_kl, 0)
        self.assertGreater(item.reverse_kl, 0)
        self.assertGreater(item.jsd, 0)
        self.assertLessEqual(item.jsd, (item.forward_kl + item.reverse_kl) / 2)
        self.assertEqual(item.top_k_overlap, 1.0)
        self.assertAlmostEqual(item.token_advantage, 0.30)
        self.assertTrue(0 < item.fork_entropy < 1)

    def test_correction_tokens_style_tokens_and_pointwise_kl_are_protected(self) -> None:
        policy = default_protection_policy()
        self.assertEqual(set(policy.minimum_retention), set(CorrectionTokenKind))
        self.assertTrue(all(value == 0.98 for value in policy.minimum_retention.values()))
        self.assertEqual(
            clip_pointwise_kl((0.5, -0.5, 0.15), style_mask=(True, False, False)),
            (0.1, -0.2, 0.15),
        )

    def test_short_medium_long_curriculum_and_two_hour_budget_are_hard(self) -> None:
        stages = default_temporal_curriculum()
        self.assertEqual(tuple(item.kind for item in stages), tuple(TemporalStageKind))
        self.assertEqual(tuple(item.maximum_turns for item in stages), (4, 16, 64))
        for index, stage in enumerate(stages):
            self.assertEqual(stage.requires_prior, tuple(TemporalStageKind)[:index])
        self.assertEqual(ExperimentBudget().wall_clock_seconds, 7_200)

    def test_each_named_failure_monitor_trips_independently(self) -> None:
        observation = MonitoringObservation(
            trajectory_kl=0.90,
            top_k_overlap=0.01,
            teacher_information_gain=0.0,
            privileged_divergence=0.90,
            overconfidence_rate=0.40,
            verification_retention=0.50,
            backtracking_retention=0.40,
            distinct_n_ratio=0.10,
        )
        self.assertEqual(
            set(monitor_failures(observation)),
            {
                "trajectory_kl_explosion",
                "teacher_student_mismatch",
                "teacher_adds_no_new_knowledge",
                "student_overconfidence",
                "verification_behavior_reduced",
                "backtracking_behavior_reduced",
                "diversity_collapse",
            },
        )


class PromotionBoundaryTests(unittest.TestCase):
    def test_failed_or_unobserved_method_is_eliminated_and_card_stays_planned(self) -> None:
        revisions = FrozenRevisionPair("teacher@frozen", "student@frozen")
        unobserved = MethodRunReceipt(KDMethod.TCOD, revisions, False, None, None, ())
        failed = MethodRunReceipt(KDMethod.TCOD, revisions, True, SHA_A, SHA_B, ("kl",))
        passed = MethodRunReceipt(KDMethod.TCOD, revisions, True, SHA_A, SHA_B, ())
        self.assertFalse(promotion_eligible(unobserved))
        self.assertFalse(promotion_eligible(failed))
        self.assertTrue(promotion_eligible(passed))
        card = planned_distillation_card(default_method_specs(), revisions)
        self.assertFalse(card["training_observed"])
        self.assertFalse(card["promotion_eligible"])
        for key in (
            "token_efficiency",
            "capability_gain",
            "capability_retention",
            "calibration_error",
            "long_trajectory_success",
            "rollout_artifact",
            "kl_diagnostics_artifact",
            "negative_experiments",
            "selected_adapter",
        ):
            self.assertIsNone(card[key])


if __name__ == "__main__":
    unittest.main()
