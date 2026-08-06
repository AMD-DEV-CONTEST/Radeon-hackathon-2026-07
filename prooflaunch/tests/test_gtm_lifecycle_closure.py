from __future__ import annotations

import hashlib
import unittest

from prooflaunch_remix.gtm_lifecycle_closure import (
    LifecycleClosureError,
    compile_lifecycle_closure_case,
    verify_lifecycle_closure_case,
)
from prooflaunch_remix.gtm_production_pack import ProductionPackCompiler
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
)


NOW = "2026-08-02T12:00:00Z"


def request(*, budget: BudgetTier, model: BusinessModel) -> CampaignStrategyInput:
    slug = f"{model.value}-{budget.value}"
    return CampaignStrategyInput(
        org_id="org-lifecycle-test",
        project_id="project-lifecycle-test",
        campaign_id=f"campaign-{slug}",
        owner="lifecycle-test-owner",
        industry=f"unclassified synthetic {model.value} category",
        lifecycle=LifecycleStage.GROWTH,
        budget=budget,
        industry_risk=IndustryRisk.STANDARD,
        brand=BrandConstitution(
            brand_name="Lifecycle Test",
            purpose="Test a full side-effect-free GTM lifecycle.",
            customer_promise="A traceable decision contract.",
            voice_principles=("specific", "evidence-first"),
            prohibited_tactics=("spam", "fabricated testimonials"),
        ),
        audience=AudienceICP(
            audience_id=f"audience-{slug}",
            name="decision participants",
            business_model=model,
            core_problem="the next decision lacks a shared evidence threshold",
            desired_outcome="make one governed next-cycle decision",
            buying_context="committee review" if model is BusinessModel.B2B else "self serve",
        ),
        objective="request one evidence review",
        offer="a decision packet",
        landing_url=f"https://example.test/{slug}",
        claims=(
            ClaimEvidence(
                claim_id="claim-lifecycle-test",
                text="The owner supplied this synthetic lifecycle fixture.",
                evidence_uri=f"fixture://{slug}/claim",
                evidence_sha256=hashlib.sha256(slug.encode()).hexdigest(),
                rights=EvidenceRights.OWNED,
                rights_reference="synthetic-owner-fixture",
                valid_from="2026-01-01T00:00:00Z",
                valid_until="2027-01-01T00:00:00Z",
                approved_by="fixture-owner",
            ),
        ),
    )


def compile_case(*, budget: BudgetTier, model: BusinessModel):
    raw = request(budget=budget, model=model)
    strategy = StrategyCompiler().compile(raw, at=NOW)
    pack = ProductionPackCompiler().compile(raw, strategy)
    return compile_lifecycle_closure_case(
        raw,
        strategy,
        pack,
        compiled_at=NOW,
        schedule_timezone="America/New_York",
    )


class GTMLifecycleClosureTests(unittest.TestCase):
    def test_zero_budget_case_connects_ten_capabilities_and_all_five_failure_modes(self) -> None:
        case = compile_case(budget=BudgetTier.ZERO, model=BusinessModel.B2B)
        self.assertEqual(len(case["capabilities"]), 10)
        self.assertTrue(all(case["capabilities"].values()))
        self.assertEqual(case["scenario_count"], 5)
        scenarios = {item["scenario"]: item for item in case["scenarios"]}
        self.assertEqual(
            scenarios["zero_budget_spend_breach"]["effect_decision"],
            "stop_and_review",
        )
        self.assertEqual(
            scenarios["zero_budget_spend_breach"]["revenue_decision"],
            "stop_and_review_zero_budget_breach",
        )
        self.assertEqual(
            scenarios["negative_contribution"]["revenue_decision"],
            "stop_and_review_negative_contribution",
        )
        self.assertTrue(case["zero_budget_paid_channels_excluded"])
        self.assertEqual(case["external_actions_executed"], 0)
        workspace = case["last_mile_workspace"]
        self.assertEqual(workspace["artifact_count"], 9)
        self.assertTrue(workspace["same_evidence_spine"])
        self.assertTrue(workspace["all_activation_disabled"])
        self.assertEqual(workspace["external_actions_executed"], 0)
        post_selection = case["post_selection_omnichannel_probe"]
        self.assertEqual(post_selection["lane_count"], 9)
        self.assertEqual(post_selection["campaign_id"], case["campaign_id"])
        self.assertEqual(post_selection["strategy_id"], case["strategy_id"])
        self.assertTrue(post_selection["same_creative_system_across_lanes"])
        self.assertTrue(post_selection["same_evidence_spine_across_lanes"])
        self.assertTrue(post_selection["all_external_actions_disabled"])
        self.assertFalse(post_selection["human_selection_observed"])

    def test_scaled_b2c_case_omits_inapplicable_zero_budget_probe_but_keeps_human_gate(self) -> None:
        case = compile_case(budget=BudgetTier.SCALED, model=BusinessModel.B2C)
        self.assertEqual(case["scenario_count"], 4)
        scenarios = {item["scenario"]: item for item in case["scenarios"]}
        self.assertNotIn("zero_budget_spend_breach", scenarios)
        positive = scenarios["qualified_positive_requires_human"]
        self.assertEqual(
            positive["effect_decision"], "continue_candidate_for_human_review"
        )
        self.assertEqual(
            positive["revenue_decision"],
            "continue_candidate_for_human_revenue_review",
        )
        self.assertTrue(positive["human_review_required"])
        self.assertFalse(case["four_a_effect_proven"])
        self.assertFalse(case["causal_revenue_proven"])

    def test_digest_and_truth_boundary_fail_closed_on_tamper(self) -> None:
        case = compile_case(budget=BudgetTier.ZERO, model=BusinessModel.B2C)
        verify_lifecycle_closure_case(case)
        tampered = dict(case)
        tampered["four_a_effect_proven"] = True
        with self.assertRaises(LifecycleClosureError):
            verify_lifecycle_closure_case(tampered)


if __name__ == "__main__":
    unittest.main()
