from __future__ import annotations

import copy
import unittest

from prooflaunch_remix.gtm_breakout_loop import (
    BreakoutArchetype,
    BreakoutLoopError,
    compile_breakout_growth_loop,
    verify_breakout_growth_loop,
)
from prooflaunch_remix.gtm_strategy import (
    AudienceICP,
    BrandConstitution,
    BudgetTier,
    BusinessModel,
    CampaignStrategyInput,
    ClaimEvidence,
    EvidenceRights,
    IndustryRisk,
    LifecycleStage,
    StrategyCompiler,
    strategy_digest,
)


NOW = "2026-08-02T12:00:00Z"


def request_for(
    business_model: BusinessModel,
    lifecycle: LifecycleStage,
    budget: BudgetTier,
    risk: IndustryRisk,
) -> CampaignStrategyInput:
    return CampaignStrategyInput(
        org_id="org-001",
        project_id="project-001",
        campaign_id=(
            f"breakout-{business_model.value}-{lifecycle.value}-{budget.value}-{risk.value}"
        ),
        owner="gtm-owner-001",
        industry="enterprise software" if business_model is BusinessModel.B2B else "consumer care",
        lifecycle=lifecycle,
        budget=budget,
        industry_risk=risk,
        brand=BrandConstitution(
            brand_name="ProofLaunch",
            purpose="Help teams make evidence-bound launch decisions.",
            customer_promise="A traceable next step.",
            voice_principles=("specific", "calm", "evidence-first"),
            prohibited_tactics=("spam", "fabricated testimonials"),
        ),
        audience=AudienceICP(
            audience_id="audience-001",
            name="revenue operators" if business_model is BusinessModel.B2B else "busy new parents",
            business_model=business_model,
            core_problem="campaign evidence is fragmented",
            desired_outcome="make a defensible launch decision",
            buying_context="committee review" if business_model is BusinessModel.B2B else "self-serve research",
        ),
        objective="request a qualified pilot" if business_model is BusinessModel.B2B else "join the owned waitlist",
        offer="a seven-day evidence review",
        landing_url="https://example.test/proof",
        claims=(
            ClaimEvidence(
                claim_id="claim-001",
                text="In the frozen owner study, 82% completed the setup task.",
                evidence_uri="project://evidence/study.json#result",
                evidence_sha256="a" * 64,
                rights=EvidenceRights.OWNED,
                rights_reference="owner-record-001",
                valid_from="2026-01-01T00:00:00Z",
                valid_until="2027-01-01T00:00:00Z",
                approved_by="claim-owner-001",
                specialist_approved_by=(
                    "specialist-001" if risk is IndustryRisk.HIGH_REGULATION else None
                ),
            ),
        ),
    )


def compile_for(
    business_model: BusinessModel = BusinessModel.B2B,
    lifecycle: LifecycleStage = LifecycleStage.LAUNCH,
    budget: BudgetTier = BudgetTier.ZERO,
    risk: IndustryRisk = IndustryRisk.STANDARD,
):
    request = request_for(business_model, lifecycle, budget, risk)
    strategy = StrategyCompiler().compile(request, at=NOW)
    loop = compile_breakout_growth_loop(
        request,
        strategy,
        source_strategy_sha256=strategy_digest(strategy),
    )
    return request, strategy, loop


class BreakoutGrowthLoopTests(unittest.TestCase):
    def test_full_48_scenario_matrix_compiles(self) -> None:
        observed = 0
        archetypes: set[str] = set()
        for business_model in BusinessModel:
            for lifecycle in LifecycleStage:
                for budget in BudgetTier:
                    for risk in IndustryRisk:
                        with self.subTest(
                            business_model=business_model.value,
                            lifecycle=lifecycle.value,
                            budget=budget.value,
                            risk=risk.value,
                        ):
                            _, strategy, loop = compile_for(
                                business_model, lifecycle, budget, risk
                            )
                            verify_breakout_growth_loop(loop)
                            self.assertEqual(loop["strategy_id"], strategy.strategy_id)
                            self.assertEqual(
                                [step["step_id"] for step in loop["steps"]],
                                ["sense", "make", "seed", "convert", "learn"],
                            )
                            self.assertFalse(loop["external_action_performed"])
                            self.assertFalse(loop["automatic_learning_promotion_enabled"])
                            archetypes.add(loop["archetype"])
                            observed += 1
        self.assertEqual(observed, 48)
        self.assertEqual(archetypes, {item.value for item in BreakoutArchetype})

    def test_zero_budget_has_no_paid_dependency(self) -> None:
        _, _, loop = compile_for(budget=BudgetTier.ZERO)
        self.assertIsNone(loop["paid_amplifier_channel"])
        self.assertTrue(loop["core_loop_functions_without_paid_media"])
        self.assertTrue(all(not step["channel"].startswith("paid_") for step in loop["steps"]))

    def test_scaled_budget_keeps_paid_as_optional_amplifier(self) -> None:
        _, strategy, loop = compile_for(budget=BudgetTier.SCALED)
        self.assertEqual(loop["paid_amplifier_channel"], strategy.primary_channel.value)
        self.assertNotEqual(loop["core_organic_channel"], strategy.primary_channel.value)
        self.assertTrue(loop["core_loop_functions_without_paid_media"])

    def test_b2b_and_b2c_launch_use_distinct_mechanisms(self) -> None:
        _, _, b2b = compile_for(BusinessModel.B2B, LifecycleStage.LAUNCH)
        _, _, b2c = compile_for(BusinessModel.B2C, LifecycleStage.LAUNCH)
        self.assertEqual(b2b["archetype"], BreakoutArchetype.PEER_PROOF_TRANSFER.value)
        self.assertEqual(b2c["archetype"], BreakoutArchetype.UTILITY_DEMO_REMIX.value)
        self.assertNotEqual(b2b["seed_cohorts"], b2c["seed_cohorts"])
        self.assertNotEqual(b2b["value_before_ask"], b2c["value_before_ask"])

    def test_experiment_changes_only_message_order(self) -> None:
        _, strategy, loop = compile_for()
        experiment = loop["primary_experiment"]
        self.assertEqual(experiment["experiment_id"], strategy.attribution.experiment_id)
        self.assertEqual(
            experiment["single_changed_variable"],
            "proof_first_versus_promise_first_message_order",
        )
        self.assertFalse(experiment["causal_claim_allowed"])
        self.assertEqual(experiment["activation_status"], "awaiting_human_release")

    def test_growth_accounting_refuses_projection_and_causal_inflation(self) -> None:
        _, _, loop = compile_for()
        accounting = loop["growth_accounting"]
        self.assertFalse(accounting["projection_supplied"])
        self.assertIn("observed_loop_amplification_ratio", accounting["derived_metrics_after_observation"])
        self.assertIn("not causal effects", accounting["interpretation"])

    def test_operator_capacity_must_be_filled_before_release(self) -> None:
        _, _, loop = compile_for()
        capacity = loop["operator_capacity"]
        self.assertFalse(capacity["numeric_capacity_invented"])
        self.assertIn("maximum consented seed count", capacity["required_before_release"])

    def test_high_regulation_preserves_specialist_gate(self) -> None:
        _, _, standard = compile_for(risk=IndustryRisk.STANDARD)
        _, _, regulated = compile_for(risk=IndustryRisk.HIGH_REGULATION)
        self.assertFalse(standard["specialist_gate_required"])
        self.assertTrue(regulated["specialist_gate_required"])

    def test_content_is_bound_to_strategy_digest(self) -> None:
        _, strategy, loop = compile_for()
        self.assertEqual(loop["source_strategy_sha256"], strategy_digest(strategy))
        self.assertEqual(len(loop["content_sha256"]), 64)

    def test_tampering_fails_verification(self) -> None:
        _, _, loop = compile_for()
        tampered = copy.deepcopy(loop)
        tampered["automatic_publish_enabled"] = True
        with self.assertRaisesRegex(BreakoutLoopError, "digest"):
            verify_breakout_growth_loop(tampered)

    def test_resealed_unsafe_tampering_still_fails(self) -> None:
        _, _, loop = compile_for()
        tampered = copy.deepcopy(loop)
        tampered["automatic_budget_activation_enabled"] = True
        unsigned = dict(tampered)
        unsigned.pop("content_sha256")
        import hashlib
        import json

        tampered["content_sha256"] = hashlib.sha256(
            json.dumps(
                unsigned,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        with self.assertRaisesRegex(BreakoutLoopError, "must remain false"):
            verify_breakout_growth_loop(tampered)


if __name__ == "__main__":
    unittest.main()
