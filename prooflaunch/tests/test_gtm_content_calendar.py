from __future__ import annotations

import unittest
from datetime import datetime

from prooflaunch_remix.gtm_channel_portfolio import compile_channel_portfolio
from prooflaunch_remix.gtm_content_calendar import (
    ContentCalendarError,
    compile_content_calendar,
    verify_content_calendar,
)
from prooflaunch_remix.gtm_production_pack import ProductionPackCompiler
from prooflaunch_remix.gtm_strategy import (
    AudienceICP,
    BrandConstitution,
    BudgetTier,
    BusinessModel,
    CampaignStrategyInput,
    Channel,
    ClaimEvidence,
    EvidenceRights,
    IndustryRisk,
    LifecycleStage,
    StrategyCompiler,
)


COMPILED_AT = "2026-08-06T12:00:00Z"


def request_for(
    *,
    business_model: BusinessModel = BusinessModel.B2B,
    lifecycle: LifecycleStage = LifecycleStage.LAUNCH,
    budget: BudgetTier = BudgetTier.ZERO,
    risk: IndustryRisk = IndustryRisk.STANDARD,
) -> CampaignStrategyInput:
    return CampaignStrategyInput(
        org_id="org-calendar",
        project_id="project-calendar",
        campaign_id=f"campaign-{business_model.value}-{lifecycle.value}-{budget.value}-{risk.value}",
        owner="calendar-owner",
        industry="calendar fixture",
        lifecycle=lifecycle,
        budget=budget,
        industry_risk=risk,
        brand=BrandConstitution(
            "ProofLaunch",
            "Test governed scheduling.",
            "An inspectable calendar.",
            ("specific", "calm"),
            ("spam",),
        ),
        audience=AudienceICP(
            "audience-calendar",
            "buying committee" if business_model is BusinessModel.B2B else "self-serve audience",
            business_model,
            "content operations are fragmented",
            "coordinate one bounded experiment",
            "committee review" if business_model is BusinessModel.B2B else "self-serve review",
        ),
        objective="review the evidence",
        offer="a seven-slot evidence sequence",
        landing_url="https://example.test/calendar",
        claims=(
            ClaimEvidence(
                "claim-calendar",
                "The owned fixture contains seven reviewable content themes.",
                "fixture://calendar/claim.json",
                "a" * 64,
                EvidenceRights.OWNED,
                "owned-fixture",
                "2026-01-01T00:00:00Z",
                "2027-01-01T00:00:00Z",
                "calendar-owner",
                "calendar-specialist" if risk is IndustryRisk.HIGH_REGULATION else None,
            ),
        ),
    )


def compile_for(request: CampaignStrategyInput, *, timezone_name: str = "UTC", at: str = COMPILED_AT):
    strategy = StrategyCompiler().compile(request, at=at)
    pack = ProductionPackCompiler().compile(request, strategy)
    calendar = compile_content_calendar(
        request,
        strategy,
        compile_channel_portfolio(request, strategy),
        source_draft_ids={
            pack.primary_copy.channel: pack.primary_copy.draft_id,
            pack.secondary_copy.channel: pack.secondary_copy.draft_id,
        },
        compiled_at=at,
        schedule_timezone=timezone_name,
    )
    return strategy, calendar


class ContentCalendarContractTests(unittest.TestCase):
    def test_all_48_strategy_scenarios_compile_across_four_timezones(self) -> None:
        zones = ("UTC", "America/New_York", "Asia/Tokyo", "Europe/London")
        count = 0
        for business_model in BusinessModel:
            for lifecycle in LifecycleStage:
                for budget in BudgetTier:
                    for risk in IndustryRisk:
                        request = request_for(
                            business_model=business_model,
                            lifecycle=lifecycle,
                            budget=budget,
                            risk=risk,
                        )
                        _, calendar = compile_for(request, timezone_name=zones[count % len(zones)])
                        self.assertEqual(calendar["slot_count"], 7)
                        self.assertEqual(len(calendar["approval_queue"]), 7)
                        self.assertFalse(calendar["automatic_publish_enabled"])
                        count += 1
        self.assertEqual(count, 48)

    def test_b2b_professional_routes_skip_local_weekends(self) -> None:
        _, calendar = compile_for(request_for(business_model=BusinessModel.B2B))
        self.assertTrue(
            all(
                datetime.fromisoformat(slot["scheduled_local"]).weekday() < 5
                for slot in calendar["slots"]
            )
        )

    def test_b2c_short_video_can_use_the_local_weekend(self) -> None:
        _, calendar = compile_for(request_for(business_model=BusinessModel.B2C))
        first = datetime.fromisoformat(calendar["slots"][0]["scheduled_local"])
        self.assertEqual(first.weekday(), 5)
        self.assertEqual(calendar["slots"][0]["channel"], Channel.SHORT_VIDEO_ORGANIC.value)

    def test_dst_transition_preserves_the_named_local_window_and_unique_utc_instants(self) -> None:
        _, calendar = compile_for(
            request_for(business_model=BusinessModel.B2C),
            timezone_name="America/New_York",
            at="2026-10-30T12:00:00Z",
        )
        first = datetime.fromisoformat(calendar["slots"][0]["scheduled_local"])
        self.assertEqual((first.hour, first.minute), (18, 30))
        self.assertEqual(first.utcoffset().total_seconds(), -5 * 3600)
        utc_values = [slot["scheduled_at_utc"] for slot in calendar["slots"]]
        self.assertEqual(len(utc_values), len(set(utc_values)))

    def test_zero_budget_calendar_contains_no_paid_slot(self) -> None:
        _, calendar = compile_for(request_for(budget=BudgetTier.ZERO))
        self.assertFalse(
            {Channel.PAID_SEARCH.value, Channel.PAID_SOCIAL.value}
            & {slot["channel"] for slot in calendar["slots"]}
        )

    def test_invalid_timezone_fails_before_any_calendar_is_returned(self) -> None:
        with self.assertRaisesRegex(ContentCalendarError, "installed IANA timezone"):
            compile_for(request_for(), timezone_name="Mars/Olympus_Mons")

    def test_digest_tampering_and_automatic_publish_fail_closed(self) -> None:
        _, calendar = compile_for(request_for())
        tampered = dict(calendar)
        tampered["automatic_publish_enabled"] = True
        with self.assertRaisesRegex(ContentCalendarError, "digest mismatch"):
            verify_content_calendar(tampered)


if __name__ == "__main__":
    unittest.main()
