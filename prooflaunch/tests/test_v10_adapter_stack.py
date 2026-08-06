from __future__ import annotations

import json
import unittest
from pathlib import Path

from prooflaunch_remix.v10_adapter_stack import (
    AdapterCache,
    AdapterCapability,
    AdapterMetadata,
    AdapterRegistry,
    AdapterRouter,
    MergeEvaluation,
    MergeMethod,
    ModelArtifact,
    ModelRole,
    RegressionState,
    RoutingContext,
    SingleCardResidencyController,
    planned_adapter_stack_card,
    quantization_admitted,
    select_merge_strategy,
)
from prooflaunch_remix.v10_contracts import V10ContractError


ROOT = Path(__file__).resolve().parents[1]
SHA_A = "a" * 64
SHA_B = "b" * 64


def adapter(
    capability: AdapterCapability,
    revision: str,
    *,
    market: str = "global",
    size: int = 100,
    priority: int = 0,
    trained: bool = True,
) -> AdapterMetadata:
    return AdapterMetadata(
        adapter_id=f"{capability.value}-adapter",
        capability=capability,
        adapter_revision=revision,
        base_model_revision="gemma4-e4b@locked",
        task_tags=(capability.value,),
        market_tags=(market,),
        target_modules=("language_model.q_proj", "language_model.v_proj"),
        rank=16,
        dtype="bf16",
        size_bytes=size if trained else None,
        artifact_sha256=SHA_A if trained else None,
        training_observed=trained,
        regression_state=RegressionState.PASSED if trained else RegressionState.UNKNOWN,
        promotion_eligible=trained,
        priority=priority,
    )


class AdapterMetadataAndRouterTests(unittest.TestCase):
    def test_ten_capability_templates_exist_but_untrained_cannot_serve(self) -> None:
        card = planned_adapter_stack_card()
        templates = card["capability_templates"]
        self.assertEqual(len(templates), 10)
        self.assertEqual({item["capability"] for item in templates}, {item.value for item in AdapterCapability})
        self.assertTrue(all(item["training_observed"] is False for item in templates))
        registry = AdapterRegistry()
        item = adapter(AdapterCapability.EVIDENCE, "r0", trained=False)
        registry.register(item)
        with self.assertRaisesRegex(V10ContractError, "untrained"):
            registry.activate(item.key)

    def test_router_uses_task_and_market_metadata_deterministically(self) -> None:
        registry = AdapterRegistry()
        generic = adapter(AdapterCapability.COPY, "r1", priority=10)
        canada = adapter(AdapterCapability.COPY, "r2", market="ca", priority=1)
        for item in (generic, canada):
            registry.register(item)
        decision = AdapterRouter(registry).route(
            RoutingContext("task-1", {AdapterCapability.COPY: 0.9}, 0.1, "ca", 0.1)
        )
        self.assertEqual(decision.selected_adapter_key, canada.key)
        self.assertIn("task_capability", decision.reasons)
        self.assertIn("market=ca", decision.reasons)

    def test_uncertainty_and_risk_have_independent_overrides(self) -> None:
        registry = AdapterRegistry()
        for capability in (AdapterCapability.COPY, AdapterCapability.CRITIC, AdapterCapability.COMPLIANCE):
            registry.register(adapter(capability, "r1"))
        router = AdapterRouter(registry)
        uncertain = router.route(RoutingContext("u", {AdapterCapability.COPY: 1.0}, 0.8, "global", 0.1))
        risky = router.route(RoutingContext("r", {AdapterCapability.COPY: 1.0}, 0.9, "global", 0.9))
        self.assertEqual(uncertain.selected_capability, AdapterCapability.CRITIC)
        self.assertEqual(risky.selected_capability, AdapterCapability.COMPLIANCE)


class RegistryCacheAndHotSwapTests(unittest.TestCase):
    def test_registry_is_versioned_content_addressed_and_rollback_restores_prior(self) -> None:
        registry = AdapterRegistry()
        first = adapter(AdapterCapability.EVIDENCE, "r1")
        second = adapter(AdapterCapability.EVIDENCE, "r2")
        registry.register(first)
        registry.register(second)
        registry.activate(first.key)
        before = registry.digest
        registry.activate(second.key)
        receipt = registry.rollback(AdapterCapability.EVIDENCE)
        self.assertEqual(receipt["restored"], first.key)
        self.assertEqual(before, registry.digest)
        self.assertEqual(len(receipt["receipt_sha256"]), 64)

    def test_cache_evicts_lru_but_never_active_adapter(self) -> None:
        cache = AdapterCache(max_adapters=2, max_bytes=250)
        first = adapter(AdapterCapability.EVIDENCE, "r1")
        second = adapter(AdapterCapability.COPY, "r1")
        third = adapter(AdapterCapability.ART, "r1")
        cache.put(first)
        cache.put(second)
        cache.protect(first.key)
        self.assertEqual(cache.put(third), (second.key,))
        self.assertEqual(cache.keys, (first.key, third.key))

    def test_cache_rejects_oversize_atomically(self) -> None:
        cache = AdapterCache(max_adapters=2, max_bytes=150)
        first = adapter(AdapterCapability.EVIDENCE, "r1", size=100)
        cache.put(first)
        with self.assertRaisesRegex(V10ContractError, "entire cache"):
            cache.put(adapter(AdapterCapability.COPY, "r1", size=200))
        self.assertEqual(cache.keys, (first.key,))

    def test_real_peft_hotswap_receipt_proves_in_place_output_change(self) -> None:
        receipt = json.loads((ROOT / "evidence/v10/peft-hotswap-local-probe.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt["status"], "passed")
        self.assertTrue(receipt["actual_peft_runtime"])
        self.assertTrue(receipt["in_place_storage_preserved"])
        self.assertTrue(receipt["output_changed"])
        self.assertGreater(receipt["maximum_output_delta"], 0)
        self.assertFalse(receipt["radeon_metric"])
        self.assertEqual(len(receipt["adapter_sha256"]), 64)


class MergeQuantizationAndResidencyTests(unittest.TestCase):
    def test_no_merge_control_wins_until_every_regression_is_observed_and_clear(self) -> None:
        unknown = MergeEvaluation(MergeMethod.TIES, False, None, None, None, None, None)
        regressed = MergeEvaluation(MergeMethod.DARE_TIES, True, False, False, True, False, 0.9)
        self.assertEqual(select_merge_strategy((unknown, regressed)), MergeMethod.NO_MERGE)
        passed = MergeEvaluation(MergeMethod.TIES, True, False, False, False, False, 0.8)
        self.assertEqual(select_merge_strategy((unknown, passed)), MergeMethod.TIES)

    def test_unverified_main_quantization_is_forbidden(self) -> None:
        self.assertFalse(quantization_admitted(role=ModelRole.MAIN, dtype="int8", parity_observed=False, safety_regression=None, quality_delta=None))
        self.assertFalse(quantization_admitted(role=ModelRole.MAIN, dtype="int8", parity_observed=True, safety_regression=True, quality_delta=0.0))
        self.assertTrue(quantization_admitted(role=ModelRole.MAIN, dtype="int8", parity_observed=True, safety_regression=False, quality_delta=-0.005))
        self.assertTrue(quantization_admitted(role=ModelRole.MAIN, dtype="bf16", parity_observed=False, safety_regression=None, quality_delta=None))

    def test_single_card_residency_plans_peak_and_unload_first_model_hotswap(self) -> None:
        controller = SingleCardResidencyController(observed_available_bytes=1_000)
        first = ModelArtifact("base-a", "r1", SHA_A, 600)
        second = ModelArtifact("base-b", "r2", SHA_B, 650)
        controller.load_base(first)
        controller.set_adapter_bytes(100)
        with self.assertRaisesRegex(V10ContractError, "only one heavy"):
            controller.load_base(second)
        plan = controller.plan_model_swap(second)
        self.assertTrue(plan.single_heavy_model)
        self.assertTrue(plan.unload_before_model_swap)
        self.assertLessEqual(plan.projected_peak_bytes, plan.budget_bytes)
        receipt = controller.swap_model(second)
        self.assertEqual(receipt["previous_model"], "base-a")
        self.assertEqual(receipt["next_model"], "base-b")

    def test_planned_card_keeps_all_neural_results_unknown(self) -> None:
        card = planned_adapter_stack_card()
        self.assertFalse(card["promotion_eligible"])
        self.assertTrue(all(value is None for value in card["metrics"].values()))
        self.assertTrue(all(value is None for value in card["artifacts"].values()))
        self.assertEqual(len(card["card_sha256"]), 64)


if __name__ == "__main__":
    unittest.main()
