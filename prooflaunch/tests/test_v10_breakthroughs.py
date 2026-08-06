from __future__ import annotations

import unittest

from prooflaunch_remix.v10_agency import (
    AdapterExpert,
    DynamicAgencyDesigner,
    ExecutionStrategy,
    MemoryFact,
    OutcomeAwareTestTimeController,
    SparseAdapterRouter,
    TaskFocusedMemory,
)
from prooflaunch_remix.v10_contracts import (
    AgencyRoleKind,
    EvidenceClass,
    V10ContractError,
)
from prooflaunch_remix.v10_creative import (
    AgencyTasteGate,
    CampaignOperatingSpace,
    CampaignSnapshot,
    HumanTasteRating,
    MediaQualityTensor,
    RegionTimeIssue,
    RegionTimeRepairPlanner,
    TASTE_DIMENSIONS,
)
from prooflaunch_remix.v10_intelligence import (
    ActionConditionedPlanner,
    CampaignAction,
    CampaignGenome,
    CampaignWorldState,
    CausalExperimentAutopilot,
    CausalMarketTwin,
    ExperimentAssignment,
    TransitionCandidate,
    TwinObservation,
    TwinQuery,
)


class CausalTwinTests(unittest.TestCase):
    @staticmethod
    def observations() -> tuple[TwinObservation, ...]:
        rows = []
        for index in range(40):
            treated = index % 2 == 0
            rows.append(
                TwinObservation(
                    observation_id=f"o-{index}",
                    audience="founder",
                    offer="trial",
                    creative="proof",
                    channel="linkedin",
                    context="launch",
                    treated=treated,
                    outcome=0.20 + (0.10 if treated else 0.0),
                    propensity=0.5,
                    observed_at=f"2026-07-{(index % 28) + 1:02d}T12:00:00Z",
                    evidence_class=EvidenceClass.OBSERVED,
                    source_locator=f"dataset://row/{index}",
                )
            )
        return tuple(rows)

    def test_twin_prediction_is_never_presented_as_observed_revenue(self) -> None:
        twin = CausalMarketTwin(self.observations())
        query = TwinQuery(
            "founder",
            "trial",
            "proof",
            "linkedin",
            "launch",
            seed=7,
        )
        prediction = twin.predict(query)
        self.assertAlmostEqual(prediction.predicted_uplift, 0.10, places=6)
        self.assertEqual(prediction.evidence_class, EvidenceClass.SIMULATED)
        self.assertEqual(prediction.display_metric, "predicted uplift")
        self.assertLessEqual(
            prediction.interval_low,
            prediction.predicted_uplift,
        )
        self.assertGreaterEqual(
            prediction.interval_high,
            prediction.predicted_uplift,
        )
        self.assertEqual(
            prediction.method,
            "stabilized_ipw_with_empirical_conformal_radius",
        )
        self.assertEqual(prediction, twin.predict(query))
        self.assertIn(
            "observational estimate; run a randomized experiment",
            prediction.warnings,
        )

    def test_synthetic_only_twin_is_rejected(self) -> None:
        synthetic = tuple(
            TwinObservation(
                **{
                    **item.__dict__,
                    "evidence_class": EvidenceClass.SIMULATED,
                }
            )
            for item in self.observations()
        )
        with self.assertRaises(V10ContractError):
            CausalMarketTwin(synthetic).predict(
                TwinQuery("a", "o", "c", "ch", "ctx", seed=1)
            )


class WorldModelTests(unittest.TestCase):
    @staticmethod
    def transition(
        state: CampaignWorldState,
        action: CampaignAction,
        seed: int,
    ) -> TransitionCandidate:
        value = float(action.parameters["value"])
        next_state = CampaignWorldState(
            state_id=f"{state.state_id}-{action.action_id}-{seed}",
            observed={**state.observed, "last_action": action.action_id},
            latent=state.latent,
            predicted_outcomes={"value": value},
            evidence_class=EvidenceClass.SIMULATED,
        )
        return TransitionCandidate(
            next_state=next_state,
            expected_value=value,
            uncertainty=float(action.parameters.get("uncertainty", 0.1)),
            rationale=f"estimated value for {action.kind}",
        )

    def test_bounded_planner_prefers_value_and_exposes_rationale(self) -> None:
        planner = ActionConditionedPlanner(self.transition, depth_limit=2)
        initial = CampaignWorldState(
            "s0",
            {"channel": "linkedin"},
            {},
            {},
            EvidenceClass.OBSERVED,
        )
        route = planner.plan(
            initial,
            (
                CampaignAction("a", "hold", {"value": 0.2}, 0.0, 0.1),
                CampaignAction("b", "launch", {"value": 0.8}, 0.1, 0.1),
            ),
            seed=3,
        )
        self.assertEqual(len(route.steps), 2)
        self.assertEqual(route.steps[0].action.action_id, "b")
        self.assertEqual(route.stopped_reason, "bounded search completed")

    def test_high_uncertainty_forces_human_evidence_path(self) -> None:
        planner = ActionConditionedPlanner(self.transition)
        initial = CampaignWorldState(
            "s0", {}, {}, {}, EvidenceClass.OBSERVED
        )
        route = planner.plan(
            initial,
            (
                CampaignAction(
                    "risk",
                    "launch",
                    {"value": 1.0, "uncertainty": 0.9},
                    0,
                    0.1,
                ),
            ),
            seed=1,
        )
        self.assertTrue(route.requires_human)
        self.assertEqual(len(route.steps), 0)

    def test_planner_supports_exactly_eight_bounded_branches(self) -> None:
        planner = ActionConditionedPlanner(
            self.transition,
            branch_limit=8,
            beam_width=4,
            depth_limit=1,
        )
        initial = CampaignWorldState(
            "s0",
            {"channel": "linkedin"},
            {},
            {},
            EvidenceClass.OBSERVED,
        )
        actions = tuple(
            CampaignAction(
                f"a-{index}",
                "candidate",
                {"value": index / 10},
                0,
                0,
            )
            for index in range(8)
        )
        route = planner.plan(initial, actions, seed=9)
        self.assertEqual(route.steps[0].action.action_id, "a-7")
        with self.assertRaises(V10ContractError):
            ActionConditionedPlanner(self.transition, branch_limit=9)


class GenomeAndExperimentTests(unittest.TestCase):
    @staticmethod
    def genome() -> CampaignGenome:
        return CampaignGenome(
            genome_id="g0",
            big_idea="Proof before promise",
            single_minded_proposition="Every claim carries evidence",
            reasons_to_believe=("source-bound",),
            brand={"voice": "calm"},
            visual={"system": "evidence"},
            motion={"tempo": "measured"},
            sound={"tone": "assured"},
            channel={"primary": "linkedin"},
            constraints=("no unsupported claims",),
            locked_axes=frozenset({"brand"}),
        )

    def test_genome_mutation_preserves_lineage_and_locks(self) -> None:
        original = self.genome()
        child = original.mutate("g1", channel={"primary": "youtube"})
        self.assertEqual(child.parent_digest, original.digest)
        self.assertEqual(child.generation, 1)
        self.assertGreater(child.distance(original), 0)
        with self.assertRaises(V10ContractError):
            original.mutate("bad", brand={"voice": "hype"})

    def test_randomized_balanced_experiment_can_be_causal(self) -> None:
        assignments = tuple(
            ExperimentAssignment(
                unit_id=f"u-{index}",
                arm="B" if index % 2 else "A",
                outcome=(index % 5) / 100 + (0.1 if index % 2 else 0),
                preperiod_covariate=(index % 5) / 100,
                segment="all",
            )
            for index in range(100)
        )
        report = CausalExperimentAutopilot().analyze(
            assignments,
            control_arm="A",
            treatment_arm="B",
            randomized=True,
        )
        self.assertTrue(report.srm_passed)
        self.assertEqual(report.evidence_class, EvidenceClass.CAUSAL)
        self.assertAlmostEqual(report.cuped_effect, 0.1, places=6)

    def test_sample_ratio_mismatch_is_detected_and_blocks_causal_class(self) -> None:
        assignments = tuple(
            ExperimentAssignment(
                unit_id=f"u-{index}",
                arm="A" if index < 10 else "B",
                outcome=float(index % 7),
                preperiod_covariate=float(index % 5),
                segment="all",
            )
            for index in range(100)
        )
        report = CausalExperimentAutopilot().analyze(
            assignments,
            control_arm="A",
            treatment_arm="B",
            randomized=True,
        )
        self.assertFalse(report.srm_passed)
        self.assertGreaterEqual(report.srm_z, 3.29)
        self.assertIn("sample ratio mismatch", report.warnings)
        self.assertEqual(report.evidence_class, EvidenceClass.OBSERVED)

    def test_nonrandomized_result_stays_observed(self) -> None:
        assignments = tuple(
            ExperimentAssignment(
                f"u-{index}",
                "B" if index % 2 else "A",
                float(index % 3),
                float(index % 2),
                "all",
            )
            for index in range(20)
        )
        report = CausalExperimentAutopilot().analyze(
            assignments,
            control_arm="A",
            treatment_arm="B",
            randomized=False,
        )
        self.assertEqual(report.evidence_class, EvidenceClass.OBSERVED)


class AgencyRuntimeTests(unittest.TestCase):
    def test_dynamic_topology_has_one_state_owner_and_bounded_roles(self) -> None:
        topology = DynamicAgencyDesigner().build(
            ("claims", "strategy", "video", "quality"),
            action_budget=20,
        )
        supervisors = [
            item
            for item in topology.roles
            if item.kind == AgencyRoleKind.SUPERVISOR
        ]
        self.assertEqual(len(supervisors), 1)
        self.assertTrue(supervisors[0].owns_state)
        self.assertLessEqual(topology.max_parallel_specialists, 3)

    def test_dynamic_topology_permissions_are_minimal_and_human_is_separate(
        self,
    ) -> None:
        topology = DynamicAgencyDesigner().build(
            ("claims", "strategy", "video", "quality"),
            action_budget=20,
        )
        specialists = [
            item
            for item in topology.roles
            if item.kind == AgencyRoleKind.SPECIALIST
        ]
        human = [
            item
            for item in topology.roles
            if item.kind == AgencyRoleKind.HUMAN
        ]
        self.assertEqual(len(human), 1)
        self.assertEqual(
            human[0].permissions,
            frozenset({"approve_release", "reject_release"}),
        )
        self.assertTrue(
            all("approve_release" not in role.permissions for role in specialists)
        )
        self.assertTrue(
            all("route" not in role.permissions for role in specialists)
        )

    def test_sparse_router_falls_back_on_low_margin(self) -> None:
        router = SparseAdapterRouter(
            (
                AdapterExpert(
                    "general",
                    frozenset({"copy", "video"}),
                    1,
                    1,
                    is_generalist=True,
                ),
                AdapterExpert("copy", frozenset({"copy"}), 1, 1),
            )
        )
        route = router.route(("copy",), {"general": 0.1, "copy": 0.1})
        self.assertTrue(route.fallback_used)
        self.assertEqual(route.selected_experts, ("general",))
        self.assertLess(route.confidence_margin, router.confidence_floor)
        self.assertEqual(
            route.reason,
            "confidence below floor; deterministic generalist fallback",
        )

    def test_memory_excludes_stale_and_unapproved_conflicts(self) -> None:
        memory = TaskFocusedMemory()
        memory.add(
            MemoryFact(
                "f1",
                "price",
                "10",
                "source://1",
                "2026-07-01T00:00:00Z",
                "2026-08-01T00:00:00Z",
                True,
                0.9,
            )
        )
        conflict = memory.add(
            MemoryFact(
                "f2",
                "price",
                "12",
                "source://2",
                "2026-07-02T00:00:00Z",
                "2026-08-02T00:00:00Z",
                False,
                0.9,
            )
        )
        self.assertIsNotNone(conflict)
        self.assertEqual(
            memory.retrieve(("price",), now="2026-07-29T00:00:00Z"),
            (),
        )

    def test_memory_ttl_confidence_and_provenance_are_enforced(self) -> None:
        memory = TaskFocusedMemory()
        memory.add(
            MemoryFact(
                "expired",
                "old_claim",
                "stale",
                "source://expired",
                "2026-01-01T00:00:00Z",
                "2026-02-01T00:00:00Z",
                True,
                1.0,
            )
        )
        memory.add(
            MemoryFact(
                "weak",
                "weak_claim",
                "uncertain",
                "source://weak",
                "2026-07-01T00:00:00Z",
                "2026-08-01T00:00:00Z",
                True,
                0.4,
            )
        )
        memory.add(
            MemoryFact(
                "active",
                "approved_claim",
                "verified",
                "source://approved",
                "2026-07-01T00:00:00Z",
                "2026-08-01T00:00:00Z",
                True,
                0.95,
            )
        )
        retrieved = memory.retrieve(
            ("old_claim", "weak_claim", "approved_claim"),
            now="2026-07-29T00:00:00Z",
            minimum_confidence=0.8,
        )
        self.assertEqual([item.fact_id for item in retrieved], ["active"])
        self.assertEqual(retrieved[0].source_locator, "source://approved")
        self.assertEqual(retrieved[0].confidence, 0.95)

    def test_test_time_controller_escalates_high_risk_to_human(self) -> None:
        decision = OutcomeAwareTestTimeController().decide(
            difficulty=0.2,
            action_risk=0.9,
            evidence_freshness=1.0,
            model_disagreement=0.0,
            expected_value=1.0,
            tool_budget=5,
        )
        self.assertEqual(decision.strategy, ExecutionStrategy.HUMAN)
        self.assertTrue(decision.requires_human)

    def test_test_time_controller_maps_all_six_execution_strategies(self) -> None:
        controller = OutcomeAwareTestTimeController()
        decisions = (
            controller.decide(
                difficulty=0.1,
                action_risk=0.1,
                evidence_freshness=1,
                model_disagreement=0,
                expected_value=0,
                tool_budget=0,
            ),
            controller.decide(
                difficulty=0.5,
                action_risk=0.1,
                evidence_freshness=1,
                model_disagreement=0,
                expected_value=0,
                tool_budget=1,
            ),
            controller.decide(
                difficulty=0.1,
                action_risk=0.1,
                evidence_freshness=0.1,
                model_disagreement=0,
                expected_value=0,
                tool_budget=3,
            ),
            controller.decide(
                difficulty=0.1,
                action_risk=0.1,
                evidence_freshness=1,
                model_disagreement=0.8,
                expected_value=0,
                tool_budget=3,
            ),
            controller.decide(
                difficulty=0.9,
                action_risk=0.1,
                evidence_freshness=1,
                model_disagreement=0,
                expected_value=1,
                tool_budget=3,
            ),
            controller.decide(
                difficulty=0.1,
                action_risk=0.9,
                evidence_freshness=1,
                model_disagreement=0,
                expected_value=1,
                tool_budget=3,
            ),
        )
        self.assertEqual(
            {item.strategy for item in decisions},
            set(ExecutionStrategy),
        )

    def test_test_time_controller_never_exceeds_tool_budget(self) -> None:
        controller = OutcomeAwareTestTimeController()
        cases = (
            (0.1, 0.1, 1.0, 0.0, 0.0, 0),
            (0.5, 0.1, 1.0, 0.0, 0.0, 1),
            (0.1, 0.1, 0.1, 0.0, 0.0, 2),
            (0.1, 0.1, 1.0, 0.8, 0.0, 3),
            (0.9, 0.1, 1.0, 0.0, 1.0, 3),
            (0.1, 0.9, 1.0, 0.0, 1.0, 5),
        )
        for (
            difficulty,
            risk,
            freshness,
            disagreement,
            value,
            tool_budget,
        ) in cases:
            with self.subTest(tool_budget=tool_budget, risk=risk):
                decision = controller.decide(
                    difficulty=difficulty,
                    action_risk=risk,
                    evidence_freshness=freshness,
                    model_disagreement=disagreement,
                    expected_value=value,
                    tool_budget=tool_budget,
                )
                self.assertLessEqual(decision.max_tool_calls, tool_budget)


class CreativeBreakthroughTests(unittest.TestCase):
    def test_simulated_taste_rating_cannot_certify_4a(self) -> None:
        with self.assertRaises(V10ContractError):
            HumanTasteRating(
                "model",
                {name: 5.0 for name in TASTE_DIMENSIONS},
                True,
                "model://self-score",
                evidence_class=EvidenceClass.SIMULATED,
            )

    def test_five_human_ratings_still_fail_if_publishable_rate_is_low(self) -> None:
        ratings = tuple(
            HumanTasteRating(
                f"r-{index}",
                {name: 4.9 for name in TASTE_DIMENSIONS},
                index < 4,
                f"review://{index}",
            )
            for index in range(5)
        )
        report = AgencyTasteGate().evaluate(ratings)
        self.assertFalse(report.passed)
        self.assertIn("directly publishable rate below 97%", report.failures)

    def test_v10_media_tensor_enforces_new_hard_bars(self) -> None:
        tensor = MediaQualityTensor(
            ocr_accuracy=0.9995,
            brand_delta_e=1.0,
            product_identity_rate=0.995,
            temporal_gain=0.30,
            audio_video_alignment=0.96,
            claim_locator_coverage=1.0,
            rights_locator_coverage=1.0,
            approval_coverage=1.0,
        )
        self.assertTrue(tensor.passed)

    def test_region_time_repair_is_local_and_bounded_to_two(self) -> None:
        issues = tuple(
            RegionTimeIssue(
                f"i-{index}",
                "asset",
                (0.1, 0.1, 0.2, 0.2),
                index,
                index,
                "ocr",
                1 - index * 0.1,
                "replace_text_layer",
            )
            for index in range(3)
        )
        program = RegionTimeRepairPlanner().plan(issues)
        self.assertEqual(len(program.repairs), 2)
        self.assertEqual(program.blocked_issues, ("i-2",))
        self.assertTrue(
            all("product" in repair.locks for repair in program.repairs)
        )

    def test_operating_space_merge_conflict_requires_resolution(self) -> None:
        space = CampaignOperatingSpace(
            CampaignSnapshot("root", (), {"headline": "A"}, "user", "start", 0)
        )
        space.fork(
            "root",
            snapshot_id="left",
            changes={"headline": "B"},
            author="a",
            reason="test left",
        )
        space.fork(
            "root",
            snapshot_id="right",
            changes={"headline": "C"},
            author="b",
            reason="test right",
        )
        result = space.merge(
            "left",
            "right",
            snapshot_id="merge",
            author="supervisor",
            reason="combine",
        )
        self.assertIsNone(result.snapshot)
        self.assertIn("headline", result.conflicts)
        self.assertEqual(
            space.compare("left", "right"),
            {"headline": ("B", "C")},
        )


if __name__ == "__main__":
    unittest.main()
