from __future__ import annotations

import unittest
from dataclasses import replace

from prooflaunch_remix.v10_contracts import EvidenceClass, V10ContractError
from prooflaunch_remix.v10_world_model import (
    AssetState,
    AudienceState,
    BrandState,
    CampaignState,
    CampaignWorldSnapshot,
    ChannelState,
    CostState,
    CreativeState,
    EvidenceState,
    FutureValue,
    MarketState,
    MemoryState,
    PredictionActualReceipt,
    PredictionErrorSource,
    RiskState,
    UncertaintyState,
    WorldAction,
    WorldActionKind,
    WorldStateLedger,
    WorldStatus,
    action_rejection_reasons,
    compress_state,
    counterfactual_rollout,
    decompress_state,
    freeze_world_model_v1,
    future_state_accuracy,
    generate_three_future_trajectories,
    hard_sample_from_deviation,
    legal_actions,
    lifecycle_status,
    pareto_trajectories,
    predict_future,
    state_diff,
    state_mermaid,
    transition_state,
    uncertainty_calibration_error,
)


SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64


def snapshot(
    *,
    status: WorldStatus = WorldStatus.ACTIVE,
    hard_blocks: tuple[str, ...] = (),
    uncertainty: float = 0.1,
) -> CampaignWorldSnapshot:
    return CampaignWorldSnapshot(
        campaign=CampaignState("campaign-1", "launch with evidence", "research", status, "supervisor"),
        evidence=EvidenceState(("claim-1",), ("claim-1",), (SHA_A,)),
        audience=AudienceState(("founders",), ("analytics",), ("health", "race"), 0.8),
        market=MarketState("2026-07-31T00:00:00Z", ("signal-1",), ("competitor-1",), EvidenceClass.OBSERVED),
        brand=BrandState("brand@1", "calm", ("no hype",), ("claim-1",)),
        creative=CreativeState("concept-1", ("variant-1",), ("claim-1",), 0.70),
        assets=AssetState((SHA_B,), True, True),
        channels=ChannelState(("linkedin",), ("linkedin",)),
        risks=RiskState({"claim": 0.1}, hard_blocks),
        memory=MemoryState("memory@1", ("atom-1",), (), ()),
        uncertainty=UncertaintyState({"evidence": uncertainty, "market": uncertainty}),
        costs=CostState(10.0, 1.0, 2.0, 100, 60),
    )


def action(
    state: CampaignWorldSnapshot,
    kind: WorldActionKind = WorldActionKind.RESEARCH,
    *,
    action_id: str = "research-1",
    scopes: tuple[str, ...] = ("evidence", "costs"),
    cost: float = 0.5,
    risk: float = 0.1,
    payload: dict[str, object] | None = None,
) -> WorldAction:
    return WorldAction(
        action_id,
        kind,
        state.digest,
        scopes,
        payload or {"query": "market proof", "next_phase": "planning"},
        cost,
        risk,
    )


class StateAndActionTests(unittest.TestCase):
    def test_all_twelve_world_state_components_are_typed_and_hash_bound(self) -> None:
        state = snapshot()
        self.assertEqual(len(state.digest), 64)
        self.assertEqual(state.evidence.support_rate, 1.0)
        self.assertEqual(state.costs.remaining_usd, 9.0)
        self.assertTrue(state.assets.rights_approved)
        self.assertEqual(state.memory.revision, "memory@1")
        self.assertEqual(state.market.evidence_class, EvidenceClass.OBSERVED)

    def test_exact_seven_action_kinds_have_scope_whitelists_and_publish_is_illegal(self) -> None:
        state = snapshot()
        self.assertEqual(len(WorldActionKind), 7)
        good = action(state)
        bad_scope = action(state, scopes=("brand",))
        publish = action(state, payload={"operation": "publish"})
        self.assertEqual(legal_actions(state, (good, bad_scope, publish)), (good,))
        self.assertIn("illegal_mutation_scope", action_rejection_reasons(state, bad_scope))
        self.assertIn("publication_not_a_world_model_action", action_rejection_reasons(state, publish))

    def test_terminal_blocked_and_human_approval_states_are_distinct(self) -> None:
        self.assertEqual(lifecycle_status(snapshot()), WorldStatus.ACTIVE)
        self.assertEqual(lifecycle_status(snapshot(status=WorldStatus.TERMINATED)), WorldStatus.TERMINATED)
        self.assertEqual(lifecycle_status(snapshot(hard_blocks=("unsupported claim",))), WorldStatus.BLOCKED)
        self.assertEqual(lifecycle_status(snapshot(uncertainty=0.8)), WorldStatus.AWAITING_HUMAN)
        high_risk = action(snapshot(), risk=0.8)
        self.assertIn("human_approval_required", action_rejection_reasons(snapshot(), high_risk))

    def test_state_transition_is_expected_state_bound_and_cost_accounted(self) -> None:
        state = snapshot()
        step = action(state)
        after, receipt = transition_state(state, step)
        self.assertEqual(after.sequence, 1)
        self.assertEqual(after.costs.spent_usd, 1.5)
        self.assertEqual(after.campaign.phase, "planning")
        self.assertEqual(receipt.before_sha256, state.digest)
        stale = replace(step, expected_state_sha256=SHA_C)
        with self.assertRaisesRegex(V10ContractError, "stale_state"):
            transition_state(state, stale)


class PredictionAndTrajectoryTests(unittest.TestCase):
    def test_next_risk_quality_cost_and_uncertainty_predictors_are_explicit(self) -> None:
        state = snapshot()
        prediction = predict_future(
            state,
            action(state),
            seed=7,
            quality_delta=0.1,
            diversity_delta=0.2,
            latency_ms=1000,
        )
        self.assertEqual(prediction.evidence_class, EvidenceClass.SIMULATED)
        self.assertEqual(prediction.initial_state_sha256, state.digest)
        self.assertGreater(prediction.values.four_a_value, state.creative.measured_quality)
        self.assertGreaterEqual(prediction.values.risk_value, 0.1)
        self.assertEqual(prediction.values.cost_usd, 0.5)
        self.assertGreaterEqual(prediction.values.uncertainty, state.uncertainty.maximum)
        self.assertEqual(len(prediction.predicted_state_sha256), 64)

    def test_exact_three_future_trajectories_expose_four_a_risk_latency_and_diversity(self) -> None:
        state = snapshot()
        routes = generate_three_future_trajectories(state, action(state), seed=11)
        self.assertEqual(tuple(route.profile for route in routes), ("conservative", "balanced", "exploratory"))
        self.assertEqual(len(routes), 3)
        self.assertTrue(all(route.values.latency_ms > 0 for route in routes))
        self.assertGreater(routes[2].values.diversity_value, routes[0].values.diversity_value)
        self.assertTrue(all(0 <= route.values.four_a_value <= 1 for route in routes))
        self.assertTrue(all(0 <= route.values.risk_value <= 1 for route in routes))

    def test_counterfactual_holds_initial_state_seed_and_assumptions_constant(self) -> None:
        state = snapshot()
        left = action(state, action_id="a", cost=0.3)
        right = action(state, action_id="b", cost=0.8)
        factual, counterfactual = counterfactual_rollout(state, left, right, seed=5)
        self.assertEqual(factual.initial_state_sha256, counterfactual.initial_state_sha256)
        self.assertEqual(factual.assumptions, counterfactual.assumptions)
        self.assertEqual(factual.values.four_a_value, counterfactual.values.four_a_value)
        self.assertNotEqual(factual.values.cost_usd, counterfactual.values.cost_usd)

    def test_pareto_selection_does_not_collapse_objectives_to_one_scalar(self) -> None:
        state = snapshot()
        routes = generate_three_future_trajectories(state, action(state), seed=11)
        frontier = pareto_trajectories(routes)
        self.assertGreaterEqual(len(frontier), 2)
        self.assertTrue({"conservative", "exploratory"}.issubset({item.profile for item in frontier}))


class LedgerCalibrationAndFreezeTests(unittest.TestCase):
    def test_hash_chain_diff_replay_compression_and_visualization_are_verifiable(self) -> None:
        state = snapshot()
        step = action(state)
        after, _ = transition_state(state, step)
        ledger = WorldStateLedger(state)
        record = ledger.append(step, after)
        self.assertTrue(ledger.verify())
        self.assertEqual(ledger.replay(1), after)
        self.assertEqual(record.parent_record_sha256, "0" * 64)
        self.assertEqual(set(state_diff(state, after)), {"campaign", "costs", "sequence"})
        compressed = compress_state(after)
        self.assertLess(len(compressed), len(str(after).encode("utf-8")))
        self.assertEqual(decompress_state(compressed)["sequence"], 1)
        diagram = state_mermaid(after)
        self.assertIn("flowchart LR", diagram)
        self.assertIn("Evidence 100%", diagram)

    @staticmethod
    def receipt(
        *,
        input_fresh: bool = True,
        action_matched: bool = True,
        execution_success: bool = True,
        actual_observed: bool = True,
    ) -> PredictionActualReceipt:
        state = snapshot()
        prediction = predict_future(
            state,
            action(state),
            seed=3,
            quality_delta=0.1,
            diversity_delta=0.1,
            latency_ms=1000,
        )
        actual = FutureValue(0.40, 0.60, 2000, 0.10, 2.0, 0.50) if actual_observed else None
        return PredictionActualReceipt(
            prediction,
            actual,
            SHA_C if actual_observed else None,
            actual_observed,
            input_fresh,
            action_matched,
            execution_success,
        )

    def test_prediction_actual_deviation_becomes_content_addressed_hard_sample(self) -> None:
        receipt = self.receipt()
        self.assertIsNotNone(receipt.deviations)
        sample = hard_sample_from_deviation(receipt)
        assert sample is not None
        self.assertEqual(sample["error_source"], PredictionErrorSource.WORLD_MODEL.value)
        self.assertEqual(len(sample["sample_sha256"]), 64)

    def test_world_model_executor_and_data_errors_are_mutually_attributed(self) -> None:
        self.assertEqual(self.receipt().error_source, PredictionErrorSource.WORLD_MODEL)
        self.assertEqual(self.receipt(execution_success=False).error_source, PredictionErrorSource.EXECUTOR)
        self.assertEqual(self.receipt(action_matched=False).error_source, PredictionErrorSource.EXECUTOR)
        self.assertEqual(self.receipt(input_fresh=False).error_source, PredictionErrorSource.DATA)
        self.assertEqual(self.receipt(actual_observed=False).error_source, PredictionErrorSource.DATA)

    def test_future_accuracy_and_uncertainty_calibration_use_observed_pairs_only(self) -> None:
        rows = (self.receipt(), self.receipt(), self.receipt(actual_observed=False))
        report = future_state_accuracy(rows)
        self.assertEqual(report["observed_count"], 2)
        self.assertTrue(0 <= report["all_core_dimensions_within_tolerance_rate"] <= 1)
        calibration = uncertainty_calibration_error(rows)
        self.assertTrue(0 <= calibration <= 1)

    def test_world_model_v1_is_frozen_without_learned_or_radeon_claims(self) -> None:
        model = freeze_world_model_v1()
        self.assertEqual(len(model["state_components"]), 12)
        self.assertEqual(len(model["action_kinds"]), 7)
        self.assertEqual(len(model["future_profiles"]), 3)
        self.assertEqual(set(model["error_sources"]), {item.value for item in PredictionErrorSource})
        self.assertFalse(model["runtime_truth"]["trained_predictor_observed"])
        self.assertFalse(model["runtime_truth"]["radeon_execution_observed"])
        self.assertIsNone(model["runtime_truth"]["future_state_accuracy"])
        self.assertEqual(len(model["content_sha256"]), 64)


if __name__ == "__main__":
    unittest.main()
