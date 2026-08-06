from __future__ import annotations

import unittest
from collections import Counter

from prooflaunch_remix.v10_agentomnia import DatasetPartition
from prooflaunch_remix.v10_contracts import V10ContractError
from prooflaunch_remix.v10_frontier_landscape import ProductLane
from prooflaunch_remix.v10_gtm_environment import IssueKind
from prooflaunch_remix.v10_gtm_environment import Operation
from prooflaunch_remix.v10_trajectory_distillation import (
    ExecutionSkillKind,
    OutcomeKind,
    PolicyDistillationExample,
    PolicyKind,
    TrainingLabel,
    TrajectoryRole,
    build_full_trajectory_corpus,
    build_matched_trajectory_family,
    decompose_role_trajectories,
    distill_policy_example,
    distill_execution_skills,
    reward_outcome,
)


class MatchedOutcomeTrajectoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.corpus = build_full_trajectory_corpus()

    def test_corpus_collects_exact_success_failure_fallback_stop_escalation_and_retry_counts(self) -> None:
        counts = Counter(item.outcome_kind for item in self.corpus)
        self.assertEqual(len(self.corpus), 456)
        self.assertEqual(counts[OutcomeKind.SUCCESS], 112)
        self.assertEqual(counts[OutcomeKind.FAILURE], 152)
        self.assertEqual(counts[OutcomeKind.RETRY], 152)
        self.assertEqual(counts[OutcomeKind.FALLBACK], 16)
        self.assertEqual(counts[OutcomeKind.STOP], 16)
        self.assertEqual(counts[OutcomeKind.HUMAN_ESCALATION], 8)

    def test_every_task_has_matched_positive_negative_and_recovery_trajectories(self) -> None:
        families = {}
        for trajectory in self.corpus:
            families.setdefault(trajectory.task_id, set()).add(trajectory.training_label)
        self.assertEqual(len(families), 152)
        self.assertTrue(
            all(
                labels
                == {
                    TrainingLabel.IMITATE,
                    TrainingLabel.NEGATIVE,
                    TrainingLabel.RECOVERY,
                }
                for labels in families.values()
            )
        )

    def test_failure_trajectory_is_explicitly_terminal_unresolved_negative_data(self) -> None:
        family = build_matched_trajectory_family(
            ProductLane.TEXT,
            IssueKind.IMPLIED_CLAIM,
            9,
        )
        failure = next(item for item in family if item.outcome_kind == OutcomeKind.FAILURE)
        self.assertEqual(failure.training_label, TrainingLabel.NEGATIVE)
        self.assertFalse(failure.verification.issue_resolved)
        self.assertEqual(
            failure.verification.terminal_signal,
            "budget_exhausted_failure",
        )
        self.assertGreaterEqual(failure.verification.rejected_action_count, 1)

    def test_retry_trajectory_contains_failed_attempt_then_verified_recovery(self) -> None:
        family = build_matched_trajectory_family(
            ProductLane.VIDEO,
            IssueKind.VIDEO_FLICKER,
            11,
        )
        retry = next(item for item in family if item.outcome_kind == OutcomeKind.RETRY)
        self.assertEqual(retry.training_label, TrainingLabel.RECOVERY)
        self.assertTrue(retry.verification.issue_resolved)
        self.assertEqual(retry.verification.terminal_signal, "verified_success")
        self.assertEqual(retry.verification.rejected_action_count, 1)

    def test_fallback_stop_and_human_escalation_use_distinct_verified_operations(self) -> None:
        cases = (
            (IssueKind.TOOL_TIMEOUT, 13, OutcomeKind.FALLBACK, Operation.FALLBACK),
            (IssueKind.INVALID_LOOP, 17, OutcomeKind.STOP, Operation.STOP),
            (
                IssueKind.AGENT_CONFLICT,
                16,
                OutcomeKind.HUMAN_ESCALATION,
                Operation.ESCALATE,
            ),
        )
        for issue_kind, index, outcome_kind, operation in cases:
            with self.subTest(outcome=outcome_kind.value):
                family = build_matched_trajectory_family(
                    ProductLane.EMPLOYEE_AGENT,
                    issue_kind,
                    index,
                )
                positive = next(
                    item for item in family if item.outcome_kind == outcome_kind
                )
                self.assertIn(operation, {event.action.operation for event in positive.events})
                self.assertEqual(positive.training_label, TrainingLabel.IMITATE)
                self.assertEqual(
                    positive.verification.terminal_signal,
                    "verified_success",
                )

    def test_corpus_preserves_all_partitions_rights_and_zero_hidden_reasoning(self) -> None:
        self.assertEqual({item.partition for item in self.corpus}, set(DatasetPartition))
        self.assertTrue(
            all(item.rights_id == "project-owned-synthetic-v1" for item in self.corpus)
        )
        self.assertFalse(any(item.hidden_chain_of_thought_present for item in self.corpus))

    def test_matched_family_replay_is_byte_deterministic(self) -> None:
        first = build_matched_trajectory_family(
            ProductLane.EMPLOYEE_AGENT,
            IssueKind.AGENT_CONFLICT,
            16,
        )
        second = build_matched_trajectory_family(
            ProductLane.EMPLOYEE_AGENT,
            IssueKind.AGENT_CONFLICT,
            16,
        )
        self.assertEqual(
            [item.trace_sha256 for item in first],
            [item.trace_sha256 for item in second],
        )


class RoleTrajectoryTests(unittest.TestCase):
    def test_planner_worker_critic_and_supervisor_have_independent_visible_trajectories(self) -> None:
        outcome = build_matched_trajectory_family(
            ProductLane.DATA,
            IssueKind.LONG_DOCUMENT,
            2,
        )[0]
        roles = decompose_role_trajectories(outcome)
        self.assertEqual({item.role for item in roles}, set(TrajectoryRole))
        self.assertEqual(len({item.trace_sha256 for item in roles}), 4)
        self.assertTrue(all(item.steps[-1].terminal for item in roles))
        self.assertFalse(any(item.hidden_chain_of_thought_present for item in roles))
        by_role = {item.role: item for item in roles}
        self.assertEqual(by_role[TrajectoryRole.PLANNER].steps[0].action_name, "emit_bounded_plan")
        self.assertEqual(by_role[TrajectoryRole.WORKER].steps[0].action_name, "inspect")
        self.assertEqual(by_role[TrajectoryRole.CRITIC].steps[0].action_name, "verify_outcome_kind")
        self.assertEqual(
            by_role[TrajectoryRole.SUPERVISOR].steps[0].action_name,
            "supervise_training_admission",
        )

    def test_worker_trajectory_retains_every_visible_environment_transition(self) -> None:
        outcome = build_matched_trajectory_family(
            ProductLane.AD_ACTIVATION,
            IssueKind.OCR,
            7,
        )[2]
        worker = next(
            item
            for item in decompose_role_trajectories(outcome)
            if item.role == TrajectoryRole.WORKER
        )
        self.assertEqual(len(worker.steps), len(outcome.events))
        for step, event in zip(worker.steps, outcome.events, strict=True):
            self.assertEqual(step.observation_sha256, event.observation_sha256)
            self.assertEqual(step.tool_response_sha256, event.tool_response_sha256)
            self.assertEqual(step.next_observation_sha256, event.next_observation_sha256)


class RewardAndPolicyDistillationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.corpus = build_full_trajectory_corpus()

    def test_step_rewards_penalize_first_error_and_reward_repair(self) -> None:
        retry = next(
            item
            for item in self.corpus
            if item.outcome_kind == OutcomeKind.RETRY
            and item.issue_kind == IssueKind.TOOL_TIMEOUT
        )
        steps, trajectory = reward_outcome(retry)
        self.assertTrue(any(item.correctness == -1 for item in steps))
        self.assertTrue(any(item.recovery == 1 for item in steps))
        self.assertEqual(trajectory.first_error_repaired, 1)
        self.assertEqual(trajectory.training_label, TrainingLabel.RECOVERY)

    def test_trajectory_rewards_keep_negative_and_recovery_semantics_separate(self) -> None:
        family = build_matched_trajectory_family(
            ProductLane.AUDIO,
            IssueKind.AV_ALIGNMENT,
            12,
        )
        rewards = {
            item.training_label: reward_outcome(item)[1]
            for item in family
        }
        self.assertEqual(rewards[TrainingLabel.NEGATIVE].terminal_success, 0)
        self.assertEqual(rewards[TrainingLabel.NEGATIVE].first_error_repaired, 0)
        self.assertEqual(rewards[TrainingLabel.RECOVERY].terminal_success, 1)
        self.assertEqual(rewards[TrainingLabel.RECOVERY].first_error_repaired, 1)
        self.assertEqual(rewards[TrainingLabel.IMITATE].terminal_success, 1)

    def test_policy_examples_cover_stop_retry_fallback_and_human_escalation(self) -> None:
        examples = [
            example
            for item in self.corpus
            if (example := distill_policy_example(item)) is not None
        ]
        counts = Counter(item.policy_kind for item in examples)
        self.assertEqual(len(examples), 192)
        self.assertEqual(counts[PolicyKind.RETRY], 152)
        self.assertEqual(counts[PolicyKind.FALLBACK], 16)
        self.assertEqual(counts[PolicyKind.STOP], 16)
        self.assertEqual(counts[PolicyKind.HUMAN_ESCALATION], 8)
        self.assertFalse(any(item.privileged_context_present for item in examples))
        self.assertFalse(any(item.hidden_chain_of_thought_present for item in examples))

    def test_policy_example_rejects_privileged_or_hidden_reasoning(self) -> None:
        with self.assertRaises(V10ContractError):
            PolicyDistillationExample(
                example_id="bad",
                source_trajectory_id="source",
                partition=DatasetPartition.SFT,
                policy_kind=PolicyKind.STOP,
                deployment_observation={"visible": True},
                teacher_action="stop",
                action_arguments={},
                source_trace_sha256="a" * 64,
                privileged_context_present=True,
            )


class ExecutionSkillDistillationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.outcome = build_matched_trajectory_family(
            ProductLane.EMPLOYEE_AGENT,
            IssueKind.TOOL_TIMEOUT,
            13,
        )[0]
        cls.examples = {
            item.kind: item for item in distill_execution_skills(cls.outcome)
        }

    def test_task_decomposition_is_an_ordered_visible_dependency_dag(self) -> None:
        example = self.examples[ExecutionSkillKind.TASK_DECOMPOSITION]
        steps = example.target["steps"]
        self.assertEqual(len(steps), len(self.outcome.events))
        self.assertEqual(steps[0]["depends_on"], ())
        self.assertEqual(steps[-1]["depends_on"], (f"step-{len(steps) - 2}",))
        self.assertFalse(example.hidden_chain_of_thought_present)
        with self.assertRaisesRegex(V10ContractError, "backward"):
            type(example)(
                **{
                    **example.__dict__,
                    "target": {
                        "steps": (
                            {"step_id": "a", "depends_on": ("b",)},
                            {"step_id": "b", "depends_on": ()},
                        )
                    },
                }
            )

    def test_tool_selection_chooses_only_from_explicit_allowed_candidates(self) -> None:
        example = self.examples[ExecutionSkillKind.TOOL_SELECTION]
        self.assertIn(example.target["selected_tool"], example.target["candidate_tools"])
        with self.assertRaisesRegex(V10ContractError, "explicit candidates"):
            type(example)(**{**example.__dict__, "target": {"candidate_tools": ("inspect", "stop"), "selected_tool": "shell"}})

    def test_argument_filling_exactly_satisfies_the_frozen_tool_schema(self) -> None:
        example = self.examples[ExecutionSkillKind.ARGUMENT_FILLING]
        self.assertEqual(set(example.target["arguments"]), set(example.target["required_fields"]))
        with self.assertRaisesRegex(V10ContractError, "exactly"):
            type(example)(**{**example.__dict__, "target": {**example.target, "arguments": {**example.target["arguments"], "extra": "leak"}}})

    def test_observation_compression_preserves_every_required_visible_fact(self) -> None:
        example = self.examples[ExecutionSkillKind.OBSERVATION_COMPRESSION]
        self.assertTrue(set(example.required_fact_sha256s).issubset(example.target["retained_fact_sha256s"]))
        self.assertLessEqual(example.target["estimated_tokens"], example.output_token_budget)
        with self.assertRaisesRegex(V10ContractError, "dropped"):
            type(example)(**{**example.__dict__, "target": {**example.target, "retained_fact_sha256s": ()}})


if __name__ == "__main__":
    unittest.main()
