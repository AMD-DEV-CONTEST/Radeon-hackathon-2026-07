from __future__ import annotations

import unittest

from prooflaunch_remix.v10_agentomnia import DatasetPartition
from prooflaunch_remix.v10_contracts import V10ContractError
from prooflaunch_remix.v10_trajectory_distillation import (
    OutcomeKind,
    TrainingLabel,
    TrajectoryRole,
    build_full_trajectory_corpus,
    decompose_role_trajectories,
)
from prooflaunch_remix.v10_trajectory_kd_runtime import (
    AblationArm,
    CreditIncident,
    HierarchicalCreditAssignment,
    LengthBucket,
    build_information_ablations,
    build_temporal_curriculum,
    build_trajectory_card,
    diagnose_trajectory,
    evaluate_mechanical_pipeline,
    assign_hierarchical_credit,
)


class HierarchicalCreditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.corpus = build_full_trajectory_corpus()

    def test_planner_worker_critic_and_supervisor_receive_local_evidence_credit(self) -> None:
        outcome = next(
            item
            for item in self.corpus
            if item.training_label == TrainingLabel.IMITATE
            and item.outcome_kind == OutcomeKind.SUCCESS
        )
        assignment = assign_hierarchical_credit(outcome)
        by_role = {item.role: item for item in assignment.role_credits}
        self.assertEqual(by_role[TrajectoryRole.PLANNER].planning, 1)
        self.assertEqual(by_role[TrajectoryRole.WORKER].execution, 1)
        self.assertEqual(by_role[TrajectoryRole.CRITIC].detection, 1)
        self.assertEqual(by_role[TrajectoryRole.SUPERVISOR].supervision, 1)
        self.assertTrue(all(item.evidence_codes for item in assignment.role_credits))

    def test_credit_assignment_blocks_final_only_credit(self) -> None:
        outcome = self.corpus[0]
        valid = assign_hierarchical_credit(outcome)
        self.assertTrue(valid.final_only_credit_blocked)
        self.assertGreaterEqual(len(valid.nonterminal_credited_steps), 1)
        with self.assertRaises(V10ContractError):
            HierarchicalCreditAssignment(
                trajectory_id="bad-final-only",
                step_reward_sha256="a" * 64,
                role_credits=valid.role_credits,
                nonterminal_credited_steps=(),
                terminal_credited_step=1,
                final_only_credit_blocked=True,
                upstream_propagation_guarded=True,
            )

    def test_explicit_worker_error_does_not_penalize_upstream_planner(self) -> None:
        failure = next(
            item for item in self.corpus if item.training_label == TrainingLabel.NEGATIVE
        )
        assignment = assign_hierarchical_credit(
            failure,
            CreditIncident(
                first_error_step=1,
                origin_role=TrajectoryRole.WORKER,
            ),
        )
        by_role = {item.role: item for item in assignment.role_credits}
        self.assertEqual(by_role[TrajectoryRole.WORKER].error_penalty, -1)
        self.assertEqual(by_role[TrajectoryRole.PLANNER].error_penalty, 0)
        self.assertEqual(by_role[TrajectoryRole.CRITIC].error_penalty, 0)
        self.assertTrue(assignment.upstream_propagation_guarded)

    def test_recovery_credit_keeps_error_and_repair_as_separate_signals(self) -> None:
        recovery = next(
            item for item in self.corpus if item.training_label == TrainingLabel.RECOVERY
        )
        worker = next(
            item
            for item in assign_hierarchical_credit(recovery).role_credits
            if item.role == TrajectoryRole.WORKER
        )
        self.assertEqual(worker.error_penalty, -1)
        self.assertEqual(worker.repair, 1)
        self.assertEqual(worker.execution, 1)


class TemporalCurriculumTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.corpus = build_full_trajectory_corpus()
        cls.curriculum = build_temporal_curriculum(cls.corpus)

    def test_curriculum_orders_short_then_medium_then_long(self) -> None:
        self.assertEqual(
            [stage.bucket for stage in self.curriculum.stages],
            [LengthBucket.SHORT, LengthBucket.MEDIUM, LengthBucket.LONG],
        )
        self.assertTrue(all(stage.trajectory_ids for stage in self.curriculum.stages))

    def test_each_stage_enforces_its_own_length_contract(self) -> None:
        by_id = {
            role.trajectory_id: len(role.steps)
            for outcome in self.corpus
            if outcome.partition in {DatasetPartition.SFT, DatasetPartition.RL}
            for role in decompose_role_trajectories(outcome)
        }
        for stage in self.curriculum.stages:
            lengths = {by_id[item] for item in stage.trajectory_ids}
            if stage.bucket == LengthBucket.SHORT:
                self.assertEqual(lengths, {1})
            elif stage.bucket == LengthBucket.MEDIUM:
                self.assertTrue(all(2 <= length <= 3 for length in lengths))
            else:
                self.assertTrue(all(length >= 4 for length in lengths))

    def test_validation_and_evaluation_are_held_out_of_curriculum(self) -> None:
        self.assertEqual(
            set(self.curriculum.held_out_partitions),
            {DatasetPartition.VALIDATION, DatasetPartition.EVALUATION},
        )
        self.assertTrue(
            all(
                set(stage.partition_counts)
                <= {DatasetPartition.SFT.value, DatasetPartition.RL.value}
                for stage in self.curriculum.stages
            )
        )

    def test_curriculum_is_content_addressed_and_deterministic(self) -> None:
        second = build_temporal_curriculum(self.corpus)
        self.assertEqual(self.curriculum.digest, second.digest)
        self.assertEqual(len(self.curriculum.digest), 64)


class TrajectoryDiagnosticTests(unittest.TestCase):
    def test_healthy_fixture_has_no_kl_compounding_noise_or_loop_flag(self) -> None:
        report = diagnose_trajectory(
            "healthy",
            ({"inspect": 0.9, "repair": 0.1},) * 3,
            ({"inspect": 0.85, "repair": 0.15},) * 3,
            (True, True, True),
            (True, True, True),
            ("s0:inspect", "s1:repair", "s2:stop"),
        )
        self.assertEqual(report.flags, ())
        self.assertIsNone(report.first_action_mismatch_step)

    def test_controlled_fixture_detects_kl_compounding_tool_noise_and_loop(self) -> None:
        teacher = (
            {"inspect": 0.99, "repair": 0.01},
            {"inspect": 0.99, "repair": 0.01},
            {"inspect": 0.99, "repair": 0.01},
            {"inspect": 0.99, "repair": 0.01},
        )
        student = (
            {"inspect": 0.99, "repair": 0.01},
            {"inspect": 0.01, "repair": 0.99},
            {"inspect": 0.01, "repair": 0.99},
            {"inspect": 0.01, "repair": 0.99},
        )
        report = diagnose_trajectory(
            "all-faults",
            teacher,
            student,
            (True, True, True, True),
            (False, False, False, False),
            ("s0:inspect", "s1:repair", "s1:repair", "s1:repair"),
        )
        self.assertEqual(
            set(report.flags),
            {
                "trajectory_kl_explosion",
                "compounding_error",
                "tool_noise_regression",
                "invalid_loop",
            },
        )
        self.assertEqual(report.first_action_mismatch_step, 1)
        self.assertGreater(report.compounding_error_rate, 0.5)
        self.assertEqual(report.repeated_state_action_count, 2)


class AblationEvaluationAndCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.corpus = build_full_trajectory_corpus()

    def test_no_trajectory_and_final_answer_kd_are_distinct_executable_ablations(self) -> None:
        arms = {item.arm: item for item in build_information_ablations()}
        self.assertEqual(set(arms), set(AblationArm))
        self.assertFalse(arms[AblationArm.NO_TRAJECTORY].outcome_label_available)
        self.assertTrue(arms[AblationArm.FINAL_ANSWER_KD].outcome_label_available)
        self.assertFalse(arms[AblationArm.FINAL_ANSWER_KD].step_attribution_scorable)
        self.assertTrue(arms[AblationArm.FULL_TRAJECTORY].step_attribution_scorable)
        self.assertFalse(any(item.model_quality_measured for item in arms.values()))

    def test_held_out_mechanical_evaluation_reports_attribution_and_task_success_separately(self) -> None:
        evaluation = evaluate_mechanical_pipeline(self.corpus)
        self.assertEqual(evaluation.held_out_partition, DatasetPartition.EVALUATION)
        self.assertEqual(evaluation.held_out_task_count, 24)
        self.assertEqual(evaluation.outcome_count, 72)
        self.assertEqual(evaluation.attribution_eligible_count, 48)
        self.assertEqual(evaluation.mechanical_first_error_accuracy, 1.0)
        self.assertEqual(evaluation.clean_positive_success_rate, 1.0)
        self.assertEqual(evaluation.recovery_success_rate, 1.0)
        self.assertEqual(evaluation.negative_rejection_rate, 1.0)
        self.assertIsNone(evaluation.trained_model_attribution_accuracy)
        self.assertIsNone(evaluation.trained_model_task_success_rate)

    def test_trajectory_card_is_frozen_content_addressed_and_blocks_promotion(self) -> None:
        diagnostics = ("a" * 64, "b" * 64)
        first = build_trajectory_card(
            self.corpus,
            source_manifest_sha256="c" * 64,
            diagnostic_digests=diagnostics,
        )
        second = build_trajectory_card(
            self.corpus,
            source_manifest_sha256="c" * 64,
            diagnostic_digests=diagnostics,
        )
        self.assertTrue(first["frozen"])
        self.assertFalse(first["promotion_eligible"])
        self.assertIsNone(first["trained_model_metrics"])
        self.assertEqual(first["content_sha256"], second["content_sha256"])
        self.assertEqual(len(first["content_sha256"]), 64)


if __name__ == "__main__":
    unittest.main()
