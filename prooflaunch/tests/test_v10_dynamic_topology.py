from __future__ import annotations

import unittest
from dataclasses import replace

from prooflaunch_remix.v10_contracts import EvidenceClass, V10ContractError
from prooflaunch_remix.v10_dynamic_topology import (
    BlackboardFact,
    Capability,
    CapabilityOutput,
    DynamicTopologyV1,
    Opinion,
    ScopedObservation,
    SearchMode,
    SharedFactBlackboard,
    SupervisorMetaPolicy,
    ToolContract,
    TopologyArm,
    TopologyHistory,
    TopologyOutcome,
    TopologyRequest,
    WorkPhase,
    append_topology_trace,
    default_capability_contracts,
    evaluate_matched_topology_arms,
    freeze_topology_v1,
    prune_duplicate_opinions,
    prune_observations,
    search_mode_for_phase,
    structural_entropy,
)


SHA_A = "a" * 64
SHA_B = "b" * 64


def request(
    *,
    phase: WorkPhase = WorkPhase.RESEARCH,
    entropy: float = 0.2,
    risk: float = 0.1,
    conflicts: int = 0,
    confidence: float = 0.8,
    values: dict[Capability, float] | None = None,
) -> TopologyRequest:
    return TopologyRequest(
        "task-1",
        (Capability.EVIDENCE, Capability.STRATEGY),
        phase,
        entropy,
        risk,
        conflicts,
        values or {},
        confidence,
    )


class CapabilityAndSupervisorTests(unittest.TestCase):
    def test_exact_twelve_capabilities_have_typed_io_tools_permissions_and_budget(self) -> None:
        contracts = default_capability_contracts()
        self.assertEqual(len(contracts), 12)
        self.assertEqual({item.capability for item in contracts}, set(Capability))
        self.assertTrue(all(item.input_fields and item.output_fields for item in contracts))
        self.assertTrue(all(item.permitted_tools for item in contracts))
        self.assertTrue(all("approve_release" not in item.permissions for item in contracts))

    def test_topology_uses_capability_nodes_not_fixed_persona_chat(self) -> None:
        topology = SupervisorMetaPolicy().build(request())
        self.assertFalse(any(node.node_id.startswith("persona-") for node in topology.nodes))
        self.assertEqual(sum(node.owns_state for node in topology.nodes), 1)
        self.assertTrue(any(node.node_id == "human-release" and node.human for node in topology.nodes))

    def test_entropy_risk_conflict_and_low_value_drive_activation_and_pruning(self) -> None:
        topology = SupervisorMetaPolicy().build(
            request(
                entropy=0.9,
                risk=0.7,
                conflicts=1,
                values={Capability.AUDIENCE: 0.0, Capability.COMPETITION: 0.8},
            )
        )
        node_ids = {node.node_id for node in topology.nodes}
        self.assertNotIn("capability-audience", node_ids)
        self.assertIn("capability-competition", node_ids)
        self.assertIn("capability-compliance", node_ids)
        self.assertIn("capability-critic", node_ids)
        self.assertIn("arbiter", node_ids)

    def test_width_depth_feedback_are_distinct_and_phase_selected(self) -> None:
        self.assertEqual(search_mode_for_phase(WorkPhase.RESEARCH), SearchMode.WIDTH)
        self.assertEqual(search_mode_for_phase(WorkPhase.PRODUCTION), SearchMode.DEPTH)
        self.assertEqual(search_mode_for_phase(WorkPhase.REPAIR), SearchMode.FEEDBACK)
        for phase in WorkPhase:
            self.assertEqual(SupervisorMetaPolicy().build(request(phase=phase)).search_mode, search_mode_for_phase(phase))


class ContractsGraphAndLifecycleTests(unittest.TestCase):
    def test_blackboard_shares_approved_facts_with_context_isolation_not_reasoning(self) -> None:
        board = SharedFactBlackboard()
        board.add(BlackboardFact("f1", "claim", "supported", SHA_A, EvidenceClass.OBSERVED, True, ("capability-evidence",)))
        board.add(BlackboardFact("f2", "draft", "private", SHA_B, EvidenceClass.OBSERVED, False, ("capability-evidence", "capability-strategy")))
        self.assertEqual(tuple(item.fact_id for item in board.read("capability-evidence")), ("f1",))
        self.assertEqual(board.read("capability-strategy"), ())
        with self.assertRaisesRegex(V10ContractError, "reasoning"):
            BlackboardFact("bad", "chain_of_thought", "secret", SHA_A, EvidenceClass.OBSERVED, True, ("supervisor",))

    def test_output_capability_and_tool_contracts_are_least_privilege_and_typed(self) -> None:
        output = CapabilityOutput("capability-evidence", Capability.EVIDENCE, {"claim_evidence": []}, (SHA_A,), 0.1)
        self.assertFalse(output.hidden_reasoning_persisted)
        tool = ToolContract("search", Capability.EVIDENCE, SHA_A, SHA_B, False, True, False)
        self.assertTrue(tool.networked)
        with self.assertRaisesRegex(V10ContractError, "destructive"):
            ToolContract("delete", Capability.PRODUCTION, SHA_A, SHA_B, True, False, False)

    def test_dependency_conflict_and_failure_graphs_are_explicit_and_dependency_is_acyclic(self) -> None:
        topology = SupervisorMetaPolicy().build(request(conflicts=1))
        self.assertTrue(topology.dependency_edges)
        self.assertTrue(topology.conflict_edges)
        self.assertTrue(topology.failure_edges)
        with self.assertRaisesRegex(V10ContractError, "acyclic"):
            DynamicTopologyV1(
                **{
                    **topology.__dict__,
                    "dependency_edges": topology.dependency_edges + ((topology.dependency_edges[0][1], "supervisor"),),
                }
            )

    def test_topology_mutation_and_rollback_are_revisioned_and_hash_bound(self) -> None:
        topology = SupervisorMetaPolicy().build(request())
        history = TopologyHistory(topology)
        worker = next(node.node_id for node in topology.nodes if node.capability is not None)
        mutated = history.remove_worker(worker, reason="measured value below threshold")
        self.assertEqual(mutated.revision, 2)
        self.assertNotIn(worker, {node.node_id for node in mutated.nodes})
        restored = history.rollback(1)
        self.assertEqual(restored.revision, 3)
        self.assertIn(worker, {node.node_id for node in restored.nodes})
        self.assertEqual(len(history.events), 2)

    def test_parallel_round_token_tool_and_low_confidence_limits_are_hard(self) -> None:
        topology = SupervisorMetaPolicy().build(request(confidence=0.2))
        self.assertLessEqual(topology.maximum_parallel, 3)
        self.assertLessEqual(topology.maximum_rounds, 8)
        self.assertLessEqual(topology.maximum_tokens, 16_000)
        self.assertLessEqual(topology.maximum_tool_calls, 20)
        self.assertTrue(topology.escalation_required)
        with self.assertRaisesRegex(V10ContractError, "parallel"):
            replace(request(), maximum_parallel=4)


class PruningEvaluationAndFreezeTests(unittest.TestCase):
    def test_duplicate_opinions_and_low_value_observations_are_pruned_deterministically(self) -> None:
        opinions = (
            Opinion("a", frozenset({"claim"}), 0.2),
            Opinion("b", frozenset({"claim"}), 0.9),
            Opinion("c", frozenset({"other"}), 0.5),
        )
        self.assertEqual(tuple(item.opinion_id for item in prune_duplicate_opinions(opinions)), ("b", "c"))
        observations = (
            ScopedObservation("high", 1.0, 1.0, True, 8),
            ScopedObservation("low", 0.1, 0.1, True, 8),
            ScopedObservation("denied", 1.0, 1.0, False, 1),
        )
        self.assertEqual(tuple(item.observation_id for item in prune_observations(observations, token_budget=8)), ("high",))

    def test_structural_entropy_is_normalized_and_detects_collapsed_or_balanced_topology(self) -> None:
        self.assertEqual(structural_entropy({"a": 10, "b": 0}), 0.0)
        self.assertAlmostEqual(structural_entropy({"a": 5, "b": 5}), 1.0)
        self.assertTrue(0 < structural_entropy({"a": 8, "b": 2}) < 1)

    def test_dynamic_fixed_six_and_single_agent_controls_share_exact_tasks(self) -> None:
        outcomes = tuple(
            TopologyOutcome(arm, task, arm is TopologyArm.DYNAMIC, 100, 2, 50, 3, EvidenceClass.SIMULATED)
            for arm in TopologyArm
            for task in ("t1", "t2")
        )
        report = evaluate_matched_topology_arms(outcomes)
        self.assertEqual(set(report["arms"]), {arm.value for arm in TopologyArm})
        self.assertEqual(report["evidence_class"], EvidenceClass.SIMULATED.value)
        self.assertEqual(report["arms"][TopologyArm.DYNAMIC.value]["success_rate"], 1.0)
        with self.assertRaisesRegex(V10ContractError, "same"):
            evaluate_matched_topology_arms(outcomes[:-1])

    def test_topology_trace_is_hash_chained_and_v1_freeze_claims_no_superiority(self) -> None:
        topology = SupervisorMetaPolicy().build(request())
        events = append_topology_trace((), topology, "built", {"task": "task-1"})
        events = append_topology_trace(events, topology, "routed", {"worker": "evidence"})
        self.assertEqual(events[0].prior_event_sha256, "0" * 64)
        self.assertEqual(events[1].prior_event_sha256, events[0].digest)
        frozen = freeze_topology_v1()
        self.assertEqual(len(frozen["capabilities"]), 12)
        self.assertEqual(len(frozen["controls"]), 3)
        self.assertEqual(frozen["fixed_persona_chat"], "prohibited")
        self.assertFalse(frozen["runtime_truth"]["live_agent_execution_observed"])
        self.assertIsNone(frozen["runtime_truth"]["selected_topology"])
        self.assertEqual(len(frozen["content_sha256"]), 64)


if __name__ == "__main__":
    unittest.main()
