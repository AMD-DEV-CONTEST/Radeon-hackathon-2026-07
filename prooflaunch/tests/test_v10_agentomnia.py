from __future__ import annotations

import unittest

from prooflaunch_remix.v10_agentomnia import (
    AgentCoordinate,
    AgentTask,
    ApplicationSplit,
    AtomicDifficulty,
    Capability,
    CurriculumCandidate,
    DatasetPartition,
    EvolutionBatch,
    EvolutionStatus,
    ExecutableEnvironment,
    FailureAttribution,
    FailureDrivenCurriculum,
    FullScenarioTrainingContract,
    RCRLRecovery,
    ReasoningRoute,
    RolloutResult,
    StepTransition,
    ToolContract,
)
from prooflaunch_remix.v10_contracts import V10ContractError


def coordinate() -> AgentCoordinate:
    return AgentCoordinate(
        application_split=ApplicationSplit.TO_EMPLOYEE,
        domain_l1="Go-to-market",
        scenario_l2="Evidence-grounded campaign launch",
        capabilities=frozenset(
            {
                Capability.TASK_UNDERSTANDING,
                Capability.PLANNING_DECISION,
                Capability.TOOL_USE,
                Capability.RELIABILITY_SAFETY,
            }
        ),
        difficulties=frozenset(
            {
                AtomicDifficulty.DYNAMIC_PLANNING,
                AtomicDifficulty.LONG_CONTEXT,
            }
        ),
        primary_difficulty=AtomicDifficulty.LONG_CONTEXT,
        route=ReasoningRoute.DAG,
    )


def step(index: int, *, terminal: bool = False) -> StepTransition:
    return StepTransition(
        step_index=index,
        observation_sha256="a" * 64,
        action_name="inspect_evidence" if index == 0 else "compose_asset",
        action_arguments_sha256="b" * 64,
        tool_response_sha256="c" * 64,
        next_observation_sha256="d" * 64,
        terminal=terminal,
        terminal_signal="verified_success" if terminal else None,
    )


def environment(identifier: str = "gtm-env", revision: str = "e") -> ExecutableEnvironment:
    return ExecutableEnvironment(
        environment_id=identifier,
        revision_sha256=revision * 64,
        license_id="owned-fixture-v1",
        tools=(
            ToolContract(
                name="inspect_evidence",
                schema_sha256="f" * 64,
                read_only=True,
            ),
            ToolContract(
                name="compose_asset",
                schema_sha256="1" * 64,
                read_only=False,
                requires_confirmation=True,
            ),
        ),
        resettable=True,
        golden_replay_verified=True,
        healthcheck_passed=True,
        deterministic_seed=17,
    )


def task(
    identifier: str = "gtm-task",
    partition: DatasetPartition = DatasetPartition.RL,
    env: ExecutableEnvironment | None = None,
) -> AgentTask:
    env = env or environment()
    return AgentTask(
        task_id=identifier,
        environment_id=env.environment_id,
        environment_revision_sha256=env.revision_sha256,
        partition=partition,
        coordinate=coordinate(),
        verifier_ids=("state_transition", "claim_grounding"),
        maximum_steps=8,
        task_seed=23,
        checkpoint_revision="checkpoint-001",
        golden_trajectory=(step(0), step(1), step(2, terminal=True)),
    )


class TaxonomyAndTrajectoryTests(unittest.TestCase):
    def test_taxonomy_has_exactly_ten_capabilities_and_eight_difficulties(self) -> None:
        self.assertEqual(len(Capability), 10)
        self.assertEqual(len(AtomicDifficulty), 8)

    def test_primary_difficulty_must_be_active(self) -> None:
        with self.assertRaises(V10ContractError):
            AgentCoordinate(
                application_split=ApplicationSplit.TO_EMPLOYEE,
                domain_l1="GTM",
                scenario_l2="Launch",
                capabilities=frozenset({Capability.TOOL_USE}),
                difficulties=frozenset({AtomicDifficulty.DYNAMIC_PLANNING}),
                primary_difficulty=AtomicDifficulty.LONG_CONTEXT,
                route=ReasoningRoute.PROGRAM,
            )

    def test_step_level_mdp_requires_terminal_signal_consistency(self) -> None:
        with self.assertRaises(V10ContractError):
            StepTransition(
                step_index=0,
                observation_sha256="a" * 64,
                action_name="inspect",
                action_arguments_sha256="b" * 64,
                tool_response_sha256="c" * 64,
                next_observation_sha256="d" * 64,
                terminal=True,
            )

    def test_step_level_mdp_binds_observation_action_tool_response_next_and_terminal(self) -> None:
        transition = step(2, terminal=True)
        self.assertEqual(transition.observation_sha256, "a" * 64)
        self.assertEqual(transition.action_name, "compose_asset")
        self.assertEqual(transition.action_arguments_sha256, "b" * 64)
        self.assertEqual(transition.tool_response_sha256, "c" * 64)
        self.assertEqual(transition.next_observation_sha256, "d" * 64)
        self.assertEqual(transition.terminal_signal, "verified_success")

    def test_state_changing_tool_requires_confirmation(self) -> None:
        with self.assertRaises(V10ContractError):
            ToolContract(
                name="publish",
                schema_sha256="f" * 64,
                read_only=False,
            )

    def test_failure_attribution_marks_first_propagation_miss_repair_and_stop(self) -> None:
        attribution = FailureAttribution(
            trajectory_length=7,
            first_error_step=1,
            propagation_steps=(2, 3),
            missed_detection_step=3,
            repair_step=5,
            stop_step=6,
            failure_kind="unsupported_claim",
        )
        self.assertEqual(attribution.first_error_step, 1)
        self.assertEqual(attribution.repair_step, 5)


class RollbackCurriculumTests(unittest.TestCase):
    def test_all_fail_group_receives_verified_partial_prefix(self) -> None:
        env = environment()
        recovery = RCRLRecovery.from_all_fail_group(
            task(env=env),
            env,
            (
                RolloutResult("r1", 0.0, True),
                RolloutResult("r2", 0.0, True),
                RolloutResult("r3", 0.0, True),
            ),
        )
        self.assertEqual(len(recovery.prefix_steps), 1)
        self.assertEqual(recovery.unresolved_suffix_steps, 2)
        self.assertFalse(recovery.prefix_steps[-1].terminal)

    def test_nonzero_reward_group_cannot_receive_gold_prefix(self) -> None:
        env = environment()
        with self.assertRaises(V10ContractError):
            RCRLRecovery.from_all_fail_group(
                task(env=env),
                env,
                (
                    RolloutResult("r1", 0.0, True),
                    RolloutResult("r2", 1.0, False),
                ),
            )

    def test_environment_failure_cannot_masquerade_as_policy_failure(self) -> None:
        env = environment()
        with self.assertRaises(V10ContractError):
            RCRLRecovery.from_all_fail_group(
                task(env=env),
                env,
                (RolloutResult("r1", 0.0, True, environment_failure=True),),
            )

    def test_curriculum_is_frozen_deterministically_and_drops_low_value_repeats(self) -> None:
        env = environment()
        high_value = CurriculumCandidate(
            task("high", env=env),
            difficulty_score=0.9,
            novelty_score=0.8,
            coverage_gain=1.0,
            failure_value=1.0,
            verifier_reliability=0.99,
            counterfactual_variant=True,
        )
        repeated = CurriculumCandidate(
            task("repeat", env=env),
            difficulty_score=1.0,
            novelty_score=0.0,
            coverage_gain=0.0,
            failure_value=0.1,
            verifier_reliability=0.99,
            repeated_low_value_failure=True,
        )
        engine = FailureDrivenCurriculum()
        first = engine.freeze(
            "round-1",
            (repeated, high_value),
            checkpoint_revision="checkpoint-001",
            seed=42,
            maximum_tasks=2,
        )
        second = engine.freeze(
            "round-1",
            (repeated, high_value),
            checkpoint_revision="checkpoint-001",
            seed=42,
            maximum_tasks=2,
        )
        self.assertEqual(first.digest, second.digest)
        self.assertEqual(first.task_ids, ("high",))
        self.assertEqual(first.rejected_task_ids, ("repeat",))

    def test_curriculum_rejects_unreliable_verifier_and_binds_checkpoint_and_seed(self) -> None:
        env = environment()
        unreliable = CurriculumCandidate(
            task("unverifiable", env=env),
            difficulty_score=1.0,
            novelty_score=1.0,
            coverage_gain=1.0,
            failure_value=1.0,
            verifier_reliability=0.89,
        )
        engine = FailureDrivenCurriculum(minimum_verifier_reliability=0.90)
        first = engine.freeze(
            "round-2",
            (unreliable,),
            checkpoint_revision="checkpoint-old",
            seed=7,
            maximum_tasks=1,
        )
        second = engine.freeze(
            "round-2",
            (unreliable,),
            checkpoint_revision="checkpoint-old",
            seed=8,
            maximum_tasks=1,
        )
        self.assertEqual(first.task_ids, ())
        self.assertEqual(first.rejected_task_ids, ("unverifiable",))
        self.assertEqual(first.checkpoint_revision, "checkpoint-old")
        self.assertNotEqual(first.digest, second.digest)

    def test_counterfactual_variant_wins_an_otherwise_equal_curriculum_tie(self) -> None:
        env = environment()
        ordinary = CurriculumCandidate(
            task("ordinary", env=env),
            difficulty_score=0.5,
            novelty_score=0.5,
            coverage_gain=0.5,
            failure_value=0.5,
            verifier_reliability=0.99,
        )
        counterfactual = CurriculumCandidate(
            task("counterfactual", env=env),
            difficulty_score=0.5,
            novelty_score=0.5,
            coverage_gain=0.5,
            failure_value=0.5,
            verifier_reliability=0.99,
            counterfactual_variant=True,
        )
        frozen = FailureDrivenCurriculum().freeze(
            "round-3",
            (ordinary, counterfactual),
            checkpoint_revision="checkpoint-002",
            seed=13,
            maximum_tasks=1,
        )
        self.assertEqual(frozen.task_ids, ("counterfactual",))


class FullScenarioBoundaryTests(unittest.TestCase):
    def test_benchmark_specific_adapter_is_rejected(self) -> None:
        env = environment()
        contract = FullScenarioTrainingContract(
            base_model="Gemma-4-E4B-it",
            base_revision="immutable-model-revision",
            common_policy_head="gtm-generalist",
            benchmark_specific_adapters=("omnia-only",),
            environments=(env,),
            tasks=(task(env=env),),
        )
        self.assertIn("benchmark-specific adapters are forbidden", contract.audit())

    def test_train_eval_environment_revision_contamination_is_rejected(self) -> None:
        env = environment()
        contract = FullScenarioTrainingContract(
            base_model="Gemma-4-E4B-it",
            base_revision="immutable-model-revision",
            common_policy_head="gtm-generalist",
            benchmark_specific_adapters=(),
            environments=(env,),
            tasks=(
                task("train", DatasetPartition.SFT, env),
                task("eval", DatasetPartition.EVALUATION, env),
            ),
        )
        self.assertIn(
            "training/evaluation environment revision contamination",
            contract.audit(),
        )

    def test_prd_evolution_stays_on_hold_when_environment_is_unhealthy(self) -> None:
        env = ExecutableEnvironment(
            environment_id="bad-env",
            revision_sha256="2" * 64,
            license_id="owned-fixture-v1",
            tools=(
                ToolContract("inspect", "3" * 64, True),
            ),
            resettable=True,
            golden_replay_verified=True,
            healthcheck_passed=False,
            deterministic_seed=11,
        )
        batch = EvolutionBatch(
            batch_id="prd-round-1",
            source_failure_ids=("failure-001",),
            environments=(env,),
            tasks=(task("proposed", DatasetPartition.RL, env),),
            external_transfer_benchmarks=("tau2", "deepplanning", "vitabench"),
        )
        self.assertEqual(batch.status, EvolutionStatus.HOLD)
        self.assertTrue(batch.blockers)


if __name__ == "__main__":
    unittest.main()
