from __future__ import annotations

import unittest

from prooflaunch_remix.v10_contracts import V10ContractError
from prooflaunch_remix.v10_gtm_employee import (
    ABExperimentPlan,
    AudienceLearningPlan,
    Channel,
    ChannelAsset,
    CreativeFatiguePlan,
    PerformanceHypothesis,
    audit_cross_channel_campaign,
    planned_gtm_skill_card,
)


def asset(channel: Channel, suffix: str, *, strategy: str = "strategy-1") -> ChannelAsset:
    return ChannelAsset(
        f"asset-{suffix}",
        channel,
        strategy,
        "icp-1",
        ("claim-1",),
        f"proposition-{suffix}",
        f"angle-{suffix}",
        f"cta-{suffix}",
        "disclosure/footer",
    )


class CrossChannelTests(unittest.TestCase):
    def test_cross_channel_strategy_claim_and_audience_are_consistent(self) -> None:
        receipt = audit_cross_channel_campaign(
            (asset(Channel.META, "meta"), asset(Channel.TIKTOK, "tiktok")),
            substantiated_claims={"claim-1": "evidence/claims.json#claim-1"},
        )
        self.assertTrue(receipt.strategy_consistent)
        self.assertTrue(receipt.audience_consistent)
        self.assertTrue(receipt.claims_substantiated)

    def test_cross_channel_expression_is_nonduplicate(self) -> None:
        receipt = audit_cross_channel_campaign(
            (asset(Channel.META, "meta"), asset(Channel.EMAIL, "email")),
            substantiated_claims={"claim-1": "evidence/claims.json#claim-1"},
        )
        self.assertTrue(receipt.expressions_nonduplicate)
        duplicate = ChannelAsset(
            "asset-duplicate",
            Channel.LANDING_PAGE,
            "strategy-1",
            "icp-1",
            ("claim-1",),
            "proposition-meta",
            "angle-meta",
            "cta-meta",
            "disclosure/footer",
        )
        self.assertFalse(
            audit_cross_channel_campaign(
                (asset(Channel.META, "meta"), duplicate),
                substantiated_claims={"claim-1": "evidence/claims.json#claim-1"},
            ).expressions_nonduplicate
        )


class LearningPlanTests(unittest.TestCase):
    def test_performance_hypothesis_is_pre_registered_and_falsifiable(self) -> None:
        item = PerformanceHypothesis(
            "h1", "new proof module", "reduces uncertainty", "conversion_rate", 0.02, 0.003, "increase", "evidence/research.json#1", True
        )
        self.assertFalse(item.outcome_observed)
        with self.assertRaisesRegex(V10ContractError, "pre-registered"):
            PerformanceHypothesis("h2", "x", "y", "m", 0.1, 0.01, "increase", "e", False)

    def test_ab_plan_changes_one_variable_and_never_auto_publishes(self) -> None:
        plan = ABExperimentPlan("exp-1", "h1", "headline", "control", "treatment", "conversion_rate", "user", (0.5, 0.5), 500, 42, 7, 0.01)
        self.assertFalse(plan.automatic_publish)
        with self.assertRaisesRegex(V10ContractError, "human release"):
            ABExperimentPlan("exp-2", "h1", "headline", "a", "b", "metric", "user", (0.5, 0.5), 500, 28, 3, 0.01, True)

    def test_fatigue_plan_uses_leading_lagging_threshold_and_holdout(self) -> None:
        plan = CreativeFatiguePlan("fatigue-1", "thumb_stop_rate", "conversion_rate", 7, 0.15, 0.10, 1000, ("rotate_hook", "refresh_opening_frame"), 0.10)
        self.assertFalse(plan.refresh_required(impressions=500, leading_decline=0.5, lagging_decline=0.5))
        self.assertTrue(plan.refresh_required(impressions=1000, leading_decline=0.16, lagging_decline=0.01))

    def test_audience_learning_is_evidence_bounded_and_sensitive_safe(self) -> None:
        plan = AudienceLearningPlan("learn-1", "icp-1", "proof-led buyers respond", ("landing_conversion", "qualified_reply"), "bayesian_update_with_decay", 3, ("race", "health", "religion"), True)
        self.assertFalse(plan.update_admitted(2, True))
        self.assertFalse(plan.update_admitted(3, False))
        self.assertTrue(plan.update_admitted(3, True))
        with self.assertRaisesRegex(V10ContractError, "sensitive"):
            AudienceLearningPlan("bad", "icp", "x", ("health",), "rule", 3, ("health",), True)

    def test_skill_card_keeps_distillation_and_human_scores_null(self) -> None:
        card = planned_gtm_skill_card()
        self.assertFalse(card["promotion_eligible"])
        for key in ("distilled_skills", "trained_adapter", "five_rater_scores", "mean_rating", "publishable_rate", "frozen_employee_v1"):
            self.assertIsNone(card[key])


if __name__ == "__main__":
    unittest.main()
