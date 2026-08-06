from __future__ import annotations

import unittest
from dataclasses import replace

from prooflaunch_remix.gtm_channel_portfolio import (
    ChannelPortfolioError,
    compile_channel_portfolio,
    verify_channel_portfolio,
)
from prooflaunch_remix.gtm_strategy import (
    BudgetTier,
    BusinessModel,
    Channel,
    CompanyScale,
    ContentCapacity,
    DistributionStrength,
    LifecycleStage,
    SalesMotion,
    StrategyCompiler,
    score_channel_opportunities,
)
from tests.test_gtm_strategy_memory import NOW, strategy_input


_ORGANIC_EXPECTED = {
    (BusinessModel.B2B, LifecycleStage.PRE_PMF): (
        Channel.FOUNDER_CONVERSATIONS,
        Channel.COMMUNITY_LISTENING,
    ),
    (BusinessModel.B2B, LifecycleStage.LAUNCH): (
        Channel.LINKEDIN_ORGANIC,
        Channel.PARTNER_COMMUNITIES,
    ),
    (BusinessModel.B2B, LifecycleStage.GROWTH): (
        Channel.SEARCH_EDUCATION,
        Channel.CUSTOMER_EVIDENCE,
    ),
    (BusinessModel.B2B, LifecycleStage.MATURE): (
        Channel.CUSTOMER_EVIDENCE,
        Channel.CUSTOMER_EMAIL,
    ),
    (BusinessModel.B2C, LifecycleStage.PRE_PMF): (
        Channel.COMMUNITY_LISTENING,
        Channel.OWNED_SOCIAL,
    ),
    (BusinessModel.B2C, LifecycleStage.LAUNCH): (
        Channel.SHORT_VIDEO_ORGANIC,
        Channel.CREATOR_COMMUNITY,
    ),
    (BusinessModel.B2C, LifecycleStage.GROWTH): (
        Channel.SEARCH_EDUCATION,
        Channel.SHORT_VIDEO_ORGANIC,
    ),
    (BusinessModel.B2C, LifecycleStage.MATURE): (
        Channel.CUSTOMER_EVIDENCE,
        Channel.OWNED_SOCIAL,
    ),
}


class DistributionAdvantageDecisionTests(unittest.TestCase):
    def test_default_context_preserves_the_frozen_business_lifecycle_prior(self) -> None:
        for business_model in BusinessModel:
            for lifecycle in LifecycleStage:
                for budget in BudgetTier:
                    with self.subTest(
                        business_model=business_model.value,
                        lifecycle=lifecycle.value,
                        budget=budget.value,
                    ):
                        request = strategy_input(
                            business_model=business_model,
                            lifecycle=lifecycle,
                            budget=budget,
                        )
                        strategy = StrategyCompiler().compile(request, at=NOW)
                        organic_primary, organic_secondary = _ORGANIC_EXPECTED[
                            (business_model, lifecycle)
                        ]
                        if budget is BudgetTier.SCALED:
                            expected_paid = (
                                Channel.PAID_SEARCH
                                if business_model is BusinessModel.B2B
                                else Channel.PAID_SOCIAL
                            )
                            self.assertEqual(
                                (strategy.primary_channel, strategy.secondary_channel),
                                (expected_paid, organic_primary),
                            )
                        else:
                            self.assertEqual(
                                (strategy.primary_channel, strategy.secondary_channel),
                                (organic_primary, organic_secondary),
                            )

    def test_zero_budget_mechanically_excludes_paid_channels(self) -> None:
        scores = score_channel_opportunities(strategy_input(budget=BudgetTier.ZERO))
        for channel in (Channel.PAID_SEARCH, Channel.PAID_SOCIAL):
            self.assertEqual(scores[channel][0], 0)
            self.assertEqual(
                scores[channel][1],
                ("zero_budget_paid_channel_hard_exclusion",),
            )

    def test_enterprise_owned_distribution_changes_the_focus(self) -> None:
        request = replace(
            strategy_input(
                business_model=BusinessModel.B2B,
                lifecycle=LifecycleStage.MATURE,
            ),
            company_scale=CompanyScale.ENTERPRISE,
            brand_reach=DistributionStrength.STRONG,
            owned_audience_strength=DistributionStrength.STRONG,
        )
        strategy = StrategyCompiler().compile(request, at=NOW)
        self.assertEqual(
            {strategy.primary_channel, strategy.secondary_channel},
            {Channel.CUSTOMER_EVIDENCE, Channel.CUSTOMER_EMAIL},
        )

    def test_partner_and_community_access_can_beat_the_static_launch_prior(self) -> None:
        request = replace(
            strategy_input(
                business_model=BusinessModel.B2B,
                lifecycle=LifecycleStage.LAUNCH,
            ),
            community_access=DistributionStrength.STRONG,
            partner_access=DistributionStrength.STRONG,
        )
        strategy = StrategyCompiler().compile(request, at=NOW)
        self.assertEqual(strategy.primary_channel, Channel.PARTNER_COMMUNITIES)
        self.assertEqual(strategy.secondary_channel, Channel.LINKEDIN_ORGANIC)

    def test_studio_capacity_and_self_serve_motion_shift_b2c_growth_to_video(self) -> None:
        request = replace(
            strategy_input(
                business_model=BusinessModel.B2C,
                lifecycle=LifecycleStage.GROWTH,
            ),
            content_capacity=ContentCapacity.STUDIO,
            sales_motion=SalesMotion.SELF_SERVE,
        )
        strategy = StrategyCompiler().compile(request, at=NOW)
        self.assertEqual(strategy.primary_channel, Channel.SHORT_VIDEO_ORGANIC)
        self.assertEqual(strategy.secondary_channel, Channel.SEARCH_EDUCATION)

    def test_authorized_platform_aggregates_change_focus_and_strategy_identity(self) -> None:
        request = strategy_input(
            business_model=BusinessModel.B2B,
            lifecycle=LifecycleStage.LAUNCH,
        )
        baseline = StrategyCompiler().compile(request, at=NOW)
        signaled = StrategyCompiler().compile(
            request,
            at=NOW,
            signal_platform_counts={"YouTube": 13, "Vimeo": 15},
        )
        self.assertEqual(signaled.primary_channel, Channel.LINKEDIN_ORGANIC)
        self.assertEqual(signaled.secondary_channel, Channel.SHORT_VIDEO_ORGANIC)
        self.assertNotEqual(signaled.strategy_id, baseline.strategy_id)
        self.assertNotEqual(
            signaled.attribution.experiment_id,
            baseline.attribution.experiment_id,
        )

    def test_portfolio_exposes_frontier_confidence_and_next_run_human_boundary(self) -> None:
        request = replace(
            strategy_input(
                business_model=BusinessModel.B2C,
                lifecycle=LifecycleStage.GROWTH,
            ),
            content_capacity=ContentCapacity.STUDIO,
            sales_motion=SalesMotion.SELF_SERVE,
        )
        signals = {"youtube": 24, "instagram": 8}
        strategy = StrategyCompiler().compile(
            request,
            at=NOW,
            signal_platform_counts=signals,
        )
        portfolio = compile_channel_portfolio(
            request,
            strategy,
            signal_platform_counts=signals,
        )
        verify_channel_portfolio(portfolio)
        self.assertEqual(
            portfolio["algorithm"]["name"],
            "distribution_advantage_frontier_v2",
        )
        self.assertEqual(len(portfolio["opportunity_frontier"]), 4)
        self.assertIn(portfolio["decision_confidence"], {"low", "medium", "high"})
        self.assertGreaterEqual(portfolio["focus_margin_points"], 0)
        self.assertTrue(portfolio["authorized_platform_signal_input_used"])
        self.assertFalse(
            portfolio["reallocation_policy"]["automatic_reallocation_allowed"]
        )
        self.assertFalse(
            portfolio["reallocation_policy"][
                "current_run_strategy_mutation_allowed"
            ]
        )

    def test_portfolio_rejects_signal_strategy_mismatch_and_digest_tampering(self) -> None:
        request = strategy_input(
            business_model=BusinessModel.B2B,
            lifecycle=LifecycleStage.LAUNCH,
        )
        strategy = StrategyCompiler().compile(request, at=NOW)
        with self.assertRaisesRegex(
            ChannelPortfolioError,
            "distribution opportunity frontier",
        ):
            compile_channel_portfolio(
                request,
                strategy,
                signal_platform_counts={"youtube": 100, "vimeo": 100},
            )
        portfolio = compile_channel_portfolio(request, strategy)
        tampered = dict(portfolio)
        tampered["decision_confidence"] = "invalid"
        with self.assertRaisesRegex(ChannelPortfolioError, "digest mismatch"):
            verify_channel_portfolio(tampered)


if __name__ == "__main__":
    unittest.main()
