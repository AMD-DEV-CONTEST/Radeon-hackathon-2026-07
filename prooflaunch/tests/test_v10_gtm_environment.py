from __future__ import annotations

import unittest

from prooflaunch_remix.v10_agentomnia import (
    AtomicDifficulty,
    DatasetPartition,
    FullScenarioTrainingContract,
)
from prooflaunch_remix.v10_contracts import V10ContractError
from prooflaunch_remix.v10_frontier_landscape import ProductLane
from prooflaunch_remix.v10_gtm_environment import (
    EXPECTED_OPERATION,
    ROLE_CONTRACTS,
    AgentRole,
    Challenger,
    Critic,
    DeterministicGTMEnvironment,
    GTMAction,
    IssueKind,
    Operation,
    Planner,
    Producer,
    Verifier,
    build_seed_episode,
    environment_contract,
)


class SeedRoleAndTaskTests(unittest.TestCase):
    def test_five_bounded_roles_are_present(self) -> None:
        self.assertEqual(set(ROLE_CONTRACTS), set(AgentRole))
        self.assertEqual(len(ROLE_CONTRACTS), 5)
        self.assertTrue(all(item.maximum_actions <= 4 for item in ROLE_CONTRACTS.values()))

    def test_challenger_generates_all_nineteen_failure_task_kinds(self) -> None:
        fixtures = [
            Challenger.create_issue(ProductLane.VIDEO, kind)
            for kind in IssueKind
        ]
        self.assertEqual(len(fixtures), 19)
        self.assertEqual({item.kind for item in fixtures}, set(IssueKind))
        self.assertTrue(
            all(item.expected_operation == EXPECTED_OPERATION[item.kind] for item in fixtures)
        )
        self.assertTrue(all(item.artifacts for item in fixtures))

    def test_planner_producer_critic_verifier_complete_a_golden_episode(self) -> None:
        contract, task, _, _ = build_seed_episode(
            ProductLane.EMPLOYEE_AGENT,
            IssueKind.AGENT_CONFLICT,
            16,
        )
        runtime = DeterministicGTMEnvironment(
            contract.environment_id,
            contract.revision_sha256,
            (task.issue,),
        )
        plan = Planner.plan(task)
        self.assertEqual(Critic.critique_plan(task, plan), ())
        events = Producer.execute(runtime, plan)
        self.assertEqual(Critic.critique(task, events), ())
        self.assertTrue(Verifier.verify(task, runtime, events).passed)

    def test_wrong_resolution_fails_mechanical_verification(self) -> None:
        contract, task, _, _ = build_seed_episode(
            ProductLane.TEXT,
            IssueKind.EVIDENCE_MISSING,
            1,
        )
        runtime = DeterministicGTMEnvironment(
            contract.environment_id,
            contract.revision_sha256,
            (task.issue,),
        )
        events = Producer.execute(
            runtime,
            (
                GTMAction(Operation.INSPECT, task.issue.issue_id, "inspect"),
                GTMAction(Operation.REPAIR, task.issue.issue_id, "wrong_operation"),
                GTMAction(Operation.STOP, task.issue.issue_id, "premature_stop"),
            ),
        )
        verification = Verifier.verify(task, runtime, events)
        self.assertFalse(verification.passed)
        self.assertIn("missing_required_resolution_operation", verification.failures)

    def test_replay_after_reset_is_byte_deterministic(self) -> None:
        contract, task, _, _ = build_seed_episode(
            ProductLane.AUDIO,
            IssueKind.AV_ALIGNMENT,
            12,
        )
        runtime = DeterministicGTMEnvironment(
            contract.environment_id,
            contract.revision_sha256,
            (task.issue,),
        )
        first = Producer.execute(runtime, Planner.plan(task))
        first_receipt = Verifier.verify(task, runtime, first)
        runtime.reset()
        second = Producer.execute(runtime, Planner.plan(task))
        second_receipt = Verifier.verify(task, runtime, second)
        self.assertEqual(first_receipt.trace_sha256, second_receipt.trace_sha256)
        self.assertEqual(first_receipt.final_state_sha256, second_receipt.final_state_sha256)


class FullSeedCorpusTests(unittest.TestCase):
    def test_eight_lanes_times_nineteen_tasks_are_executable_and_partition_isolated(self) -> None:
        environments = {}
        tasks = []
        for lane in ProductLane:
            for index, kind in enumerate(IssueKind):
                contract, _, agent_task, events = build_seed_episode(lane, kind, index)
                environments[(contract.environment_id, contract.revision_sha256)] = contract
                tasks.append(agent_task)
                self.assertTrue(events[-1].terminal)
        self.assertEqual(len(tasks), 8 * 19)
        self.assertEqual(len(environments), 8 * 4)
        self.assertEqual(
            {task.partition for task in tasks},
            set(DatasetPartition),
        )
        contract = FullScenarioTrainingContract(
            base_model="Gemma-4-E4B-it",
            base_revision="immutable-seed-only-no-weights-trained",
            common_policy_head="shared-gtm-policy",
            benchmark_specific_adapters=(),
            environments=tuple(environments.values()),
            tasks=tuple(tasks),
        )
        self.assertEqual(contract.audit(), ())
        self.assertEqual(len(contract.digest), 64)

    def test_seed_corpus_covers_all_eight_atomic_difficulties(self) -> None:
        active = set()
        for index, kind in enumerate(IssueKind):
            _, _, task, _ = build_seed_episode(ProductLane.DATA, kind, index)
            active.update(task.coordinate.difficulties)
        self.assertEqual(active, set(AtomicDifficulty))

    def test_partition_specific_environment_revisions_are_distinct(self) -> None:
        revisions = {
            environment_contract(ProductLane.GEO, partition).revision_sha256
            for partition in DatasetPartition
        }
        self.assertEqual(len(revisions), 4)

    def test_seed_fixtures_cannot_silently_claim_external_rights(self) -> None:
        issue = Challenger.create_issue(ProductLane.AD_ACTIVATION, IssueKind.IMPLIED_CLAIM)
        self.assertTrue(all(item.synthetic for item in issue.artifacts))
        self.assertTrue(
            all(item.license_id == "project-owned-synthetic-v1" for item in issue.artifacts)
        )


if __name__ == "__main__":
    unittest.main()
