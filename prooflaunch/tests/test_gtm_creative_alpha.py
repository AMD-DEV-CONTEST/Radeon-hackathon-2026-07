from __future__ import annotations

import copy
import unittest

from prooflaunch_remix.gtm_creative_alpha import (
    CreativeAlphaError,
    compile_creative_alpha_plan,
    compile_growth_case_radar,
    verify_creative_alpha_plan,
)
from prooflaunch_remix.gtm_strategy import (
    AudienceICP,
    BrandConstitution,
    BudgetTier,
    BusinessModel,
    CampaignStrategyInput,
    ClaimEvidence,
    CompanyScale,
    ContentCapacity,
    DistributionStrength,
    EvidenceRights,
    IndustryRisk,
    LifecycleStage,
    ProductSurface,
    SalesMotion,
    StrategyCompiler,
)


NOW = "2026-08-03T12:00:00Z"


def _request(
    *,
    business_model: BusinessModel = BusinessModel.B2B,
    lifecycle: LifecycleStage = LifecycleStage.GROWTH,
    risk: IndustryRisk = IndustryRisk.STANDARD,
    capacity: ContentCapacity = ContentCapacity.STANDARD,
    product_surface: ProductSurface = ProductSurface.WEB_AGENT,
    product_category: str = "AI GTM orchestration",
    distribution_platform: str = "LinkedIn",
    audience_role: str = "internal_champion",
) -> CampaignStrategyInput:
    return CampaignStrategyInput(
        org_id="org-alpha",
        project_id="project-alpha",
        campaign_id=f"campaign-{business_model.value}-{lifecycle.value}-{risk.value}-{capacity.value}",
        owner="gtm-owner",
        industry="developer tools",
        lifecycle=lifecycle,
        budget=BudgetTier.ZERO,
        industry_risk=risk,
        brand=BrandConstitution(
            brand_name="ProofLaunch",
            purpose="Make launch decisions inspectable.",
            customer_promise="One evidence-bound next step.",
            voice_principles=("specific", "calm", "unexpected"),
            prohibited_tactics=("fabricated proof",),
        ),
        audience=AudienceICP(
            audience_id="revenue-operators",
            name="revenue operators",
            business_model=business_model,
            core_problem="generic AI content has erased category distinction",
            desired_outcome="find one ownable evidence-led growth system",
            buying_context="cross-functional launch review",
        ),
        objective="request an evidence review",
        offer="a bounded creative diagnostic",
        landing_url="https://example.test/alpha",
        claims=(
            ClaimEvidence(
                claim_id="claim-alpha",
                text="The owner supplied one reproducible launch workflow.",
                evidence_uri="project://alpha/evidence.json#workflow",
                evidence_sha256="a" * 64,
                rights=EvidenceRights.OWNED,
                rights_reference="owner-record",
                valid_from="2026-01-01T00:00:00Z",
                valid_until="2027-01-01T00:00:00Z",
                approved_by="claim-owner",
                specialist_approved_by=(
                    "licensed-reviewer" if risk is IndustryRisk.HIGH_REGULATION else None
                ),
            ),
        ),
        company_scale=CompanyScale.STARTUP,
        brand_reach=DistributionStrength.EMERGING,
        owned_audience_strength=DistributionStrength.NONE,
        community_access=DistributionStrength.ESTABLISHED,
        partner_access=DistributionStrength.EMERGING,
        content_capacity=capacity,
        sales_motion=SalesMotion.SALES_LED,
        product_surface=product_surface,
        product_category=product_category,
        schedule_timezone="America/New_York",
        distribution_platform=distribution_platform,
        audience_role=audience_role,
    )


def _case(index: int) -> dict[str, object]:
    audience_growth = 0.02 + index * 0.01
    return {
        "case_id": f"public-case-{index:02d}",
        "category": "developer tools",
        "platform": "LinkedIn",
        "market": "US",
        "observed_at": "2026-08-02T12:00:00Z",
        "source_uri_sha256": f"{index + 1:064x}"[-64:],
        "rights": "public_measurement",
        "windows": {
            str(window): {
                "active_audience_growth_rate": audience_growth + (0.02 if window == 28 else 0),
                "qualified_engagement_rate": 0.01 + index * 0.002,
                "conversion_signal_rate": 0.005 + index * 0.001,
                "content_supply_growth_rate": 0.03 + index * 0.004,
                "sample_size": 2_000 + index * 100,
            }
            for window in (28, 90, 180)
        },
        "category_benchmarks": {
            str(window): {
                "active_audience_growth_rate": 0.03,
                "qualified_engagement_rate": 0.015,
                "conversion_signal_rate": 0.007,
                "content_supply_growth_rate": 0.04,
            }
            for window in (28, 90, 180)
        },
    }


class CreativeAlphaTests(unittest.TestCase):
    def test_growth_cases_use_comparable_3_to_6_month_windows_and_remain_hypotheses(self) -> None:
        radar = compile_growth_case_radar([_case(index) for index in range(10)], as_of=NOW)
        self.assertEqual(radar["case_count"], 10)
        self.assertEqual(radar["eligible_case_count"], 10)
        self.assertEqual(radar["window_days"], [28, 90, 180])
        self.assertEqual(radar["cells"][0]["status"], "hypothesis_ranking_ready")
        self.assertEqual(len(radar["cells"][0]["ranked_candidates"]), 10)
        self.assertTrue(
            all(
                item["status"] == "hypothesis_candidate_not_growth_claim"
                for item in radar["cells"][0]["ranked_candidates"]
            )
        )
        self.assertFalse(radar["copied_creative_retained"])
        self.assertFalse(radar["automatic_strategy_mutation_executed"])

    def test_incomparable_small_cells_do_not_receive_a_rank(self) -> None:
        radar = compile_growth_case_radar([_case(index) for index in range(9)], as_of=NOW)
        self.assertEqual(radar["eligible_case_count"], 0)
        self.assertEqual(radar["cells"][0]["status"], "insufficient_comparable_cases")
        self.assertEqual(radar["cells"][0]["ranked_candidates"], [])

    def test_future_data_and_raw_source_copy_fail_closed(self) -> None:
        future = _case(0)
        future["observed_at"] = "2026-08-04T12:00:00Z"
        with self.assertRaisesRegex(CreativeAlphaError, "future information"):
            compile_growth_case_radar([future], as_of=NOW)
        copied = _case(0)
        copied["caption"] = "source expression must never enter the radar"
        with self.assertRaisesRegex(CreativeAlphaError, "raw creative"):
            compile_growth_case_radar([copied], as_of=NOW)
        stale = _case(0)
        stale["observed_at"] = "2026-07-20T12:00:00Z"
        with self.assertRaisesRegex(CreativeAlphaError, "too stale"):
            compile_growth_case_radar([stale], as_of=NOW)

    def test_plan_binds_eight_context_dimensions_platform_grammar_and_pinned_oss(self) -> None:
        request = _request()
        strategy = StrategyCompiler().compile(request, at=NOW)
        radar = compile_growth_case_radar([_case(index) for index in range(10)], as_of=NOW)
        plan = compile_creative_alpha_plan(
            request,
            strategy,
            signal_intelligence={
                "top_abstract_format_patterns": [{"feature": "proof_demo"}],
                "growth_case_radar": radar,
            },
        )
        verify_creative_alpha_plan(plan)
        self.assertEqual(plan["growth_case_radar_status"], "growth_case_hypotheses_ready")
        self.assertTrue(plan["growth_case_research_candidates"])
        self.assertEqual(plan["context"]["distribution_operating_floor"], "none")
        self.assertEqual(len(plan["style_portfolio"]), 3)
        generative = plan["generative_execution_kernel_contract"]
        self.assertEqual(generative["creative_genome_axis_count"], 8)
        self.assertGreater(generative["blueprint_design_space"], 1_000_000)
        self.assertEqual(generative["default_nonrepeating_blueprints_per_run"], 24)
        self.assertEqual(generative["capability_lane_count"], 13)
        self.assertFalse(generative["automatic_winner_selection"])
        self.assertEqual(
            {item["id"] for item in plan["oss_shadow_adapters"]},
            {
                "dspy",
                "river",
                "ruptures",
                "statsforecast",
                "posthog",
                "growthbook",
                "vowpal_wabbit",
                "causalml",
            },
        )
        self.assertEqual(plan["context"]["product_surface"], "web_agent")
        self.assertEqual(
            plan["surface_demonstration_contract"]["proof_object"],
            "one delegated job with plan, tool boundary, evidence and human checkpoint visible",
        )
        self.assertEqual(
            plan["audience_decision_unit_contract"]["mode"],
            "b2b_buying_system",
        )
        self.assertEqual(plan["context"]["audience_role"], "internal_champion")
        self.assertEqual(
            plan["market_language_contract"]["context"]["resolved_primary_role"],
            "internal_champion",
        )
        team = plan["gtm_team_capability_contract"]
        self.assertEqual(team["full_skill_registry"]["role_count"], 22)
        self.assertEqual(team["full_skill_registry"]["skills_per_role"], 10)
        self.assertEqual(team["full_skill_registry"]["atomic_skill_count"], 220)
        self.assertIn(
            "gtm_general_manager",
            {item["role_id"] for item in team["active_virtual_team"]["roles"]},
        )
        self.assertEqual(team["automatic_external_action_count"], 0)
        self.assertEqual(
            plan["publication_timing_contract"]["timezone"],
            "America/New_York",
        )
        self.assertEqual(
            plan["distribution_platform_overlay"]["language_shape"],
            "operator-specific, defensible and useful inside a real work decision",
        )
        self.assertFalse(
            plan["publication_timing_contract"]["universal_best_time_assumed"]
        )
        self.assertFalse(plan["self_evolution_contract"]["current_run_mutation_allowed"])
        self.assertEqual(
            {item["id"] for item in plan["skill_pattern_references"]},
            {"anthropic_skills", "openai_skills"},
        )
        self.assertEqual(plan["external_action_count"], 0)
        self.assertFalse(plan["automatic_install_or_adapter_promotion"])

    def test_style_depth_changes_with_capacity_and_regulated_work_excludes_humor(self) -> None:
        lean = _request(capacity=ContentCapacity.LEAN)
        studio = _request(
            business_model=BusinessModel.B2C,
            lifecycle=LifecycleStage.MATURE,
            capacity=ContentCapacity.STUDIO,
        )
        regulated = _request(
            business_model=BusinessModel.B2C,
            risk=IndustryRisk.HIGH_REGULATION,
            capacity=ContentCapacity.STUDIO,
        )
        lean_plan = compile_creative_alpha_plan(
            lean, StrategyCompiler().compile(lean, at=NOW)
        )
        studio_plan = compile_creative_alpha_plan(
            studio, StrategyCompiler().compile(studio, at=NOW)
        )
        regulated_plan = compile_creative_alpha_plan(
            regulated, StrategyCompiler().compile(regulated, at=NOW)
        )
        self.assertEqual(len(lean_plan["style_portfolio"]), 3)
        self.assertEqual(len(studio_plan["style_portfolio"]), 4)
        self.assertEqual(
            lean_plan["creative_candidate_contract"]["production_style_capacity"],
            2,
        )
        self.assertEqual(
            studio_plan["creative_candidate_contract"]["production_style_capacity"],
            4,
        )
        self.assertNotEqual(
            [item["style_id"] for item in lean_plan["style_portfolio"]],
            [item["style_id"] for item in studio_plan["style_portfolio"]],
        )
        self.assertNotIn(
            "humor", {item["mode"] for item in regulated_plan["style_portfolio"]}
        )

    def test_mobile_b2c_plan_uses_use_moment_and_store_category_contracts(self) -> None:
        request = _request(
            business_model=BusinessModel.B2C,
            lifecycle=LifecycleStage.LAUNCH,
            product_surface=ProductSurface.MOBILE_APP,
            product_category="Health and Fitness",
            distribution_platform="TikTok",
        )
        plan = compile_creative_alpha_plan(
            request, StrategyCompiler().compile(request, at=NOW)
        )
        self.assertEqual(
            plan["audience_decision_unit_contract"]["mode"],
            "b2c_use_moment_system",
        )
        self.assertIn(
            "health_fitness_medical",
            plan["market_operating_contract"]["reference_family_registry"],
        )
        self.assertEqual(
            len(plan["market_operating_contract"]["mobile_category_primary_sources"]),
            2,
        )
        self.assertIn(
            "first-session use moment",
            plan["surface_demonstration_contract"]["proof_object"],
        )
        self.assertEqual(
            plan["distribution_platform_overlay"]["content_bias"][0],
            "short_video",
        )

    def test_plan_tamper_fails_closed(self) -> None:
        request = _request()
        plan = compile_creative_alpha_plan(
            request, StrategyCompiler().compile(request, at=NOW)
        )
        tampered = copy.deepcopy(plan)
        tampered["external_action_count"] = 1
        with self.assertRaisesRegex(CreativeAlphaError, "digest"):
            verify_creative_alpha_plan(tampered)


if __name__ == "__main__":
    unittest.main()
