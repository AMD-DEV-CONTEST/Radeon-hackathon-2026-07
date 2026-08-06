#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src"
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))

from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.gtm_channel_portfolio import compile_channel_portfolio
from prooflaunch_remix.gtm_content_calendar import compile_content_calendar
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


COMPILED_AT = "2026-08-01T12:00:00Z"
CLAIM_SHA256 = hashlib.sha256(b"synthetic-owned-channel-matrix-claim-v1").hexdigest()
SCHEDULE_TIMEZONES = ("UTC", "America/New_York", "Asia/Tokyo", "Europe/London")


def _request(
    business_model: BusinessModel,
    lifecycle: LifecycleStage,
    budget: BudgetTier,
    risk: IndustryRisk,
) -> CampaignStrategyInput:
    scenario_id = "-".join(
        (business_model.value, lifecycle.value, budget.value, risk.value)
    )
    return CampaignStrategyInput(
        org_id="org-synthetic-matrix",
        project_id="project-channel-portfolio-v1",
        campaign_id=f"campaign-{scenario_id}",
        owner="synthetic-fixture-owner",
        industry="synthetic evaluation fixture",
        lifecycle=lifecycle,
        budget=budget,
        industry_risk=risk,
        brand=BrandConstitution(
            brand_name="ProofLaunch Fixture",
            purpose="Exercise channel portfolio contracts without external activation.",
            customer_promise="A deterministic and inspectable channel decision.",
            voice_principles=("specific", "calm", "evidence-first"),
            prohibited_tactics=("spam", "fabricated testimonials"),
        ),
        audience=AudienceICP(
            audience_id=f"audience-{business_model.value}",
            name="synthetic buying committee" if business_model is BusinessModel.B2B else "synthetic self-serve audience",
            business_model=business_model,
            core_problem="channel choices lack a shared evidence spine",
            desired_outcome="select a bounded route for a controlled experiment",
            buying_context="committee review" if business_model is BusinessModel.B2B else "self-serve evaluation",
        ),
        objective="review one source-bound next step",
        offer="a seven-day evidence review",
        landing_url=f"https://example.test/{scenario_id}",
        claims=(
            ClaimEvidence(
                claim_id="claim-synthetic-matrix-001",
                text="This synthetic fixture has no observed market-effect claim.",
                evidence_uri="fixture://channel-portfolio-v1/claim.json",
                evidence_sha256=CLAIM_SHA256,
                rights=EvidenceRights.OWNED,
                rights_reference="synthetic-fixture-only",
                valid_from="2026-01-01T00:00:00Z",
                valid_until="2027-01-01T00:00:00Z",
                approved_by="synthetic-fixture-owner",
                specialist_approved_by=(
                    "synthetic-specialist-fixture"
                    if risk is IndustryRisk.HIGH_REGULATION
                    else None
                ),
            ),
        ),
    )


def build_matrix() -> dict[str, object]:
    cases: list[dict[str, object]] = []
    for business_model in BusinessModel:
        for lifecycle in LifecycleStage:
            for budget in BudgetTier:
                for risk in IndustryRisk:
                    request = _request(business_model, lifecycle, budget, risk)
                    strategy = StrategyCompiler().compile(request, at=COMPILED_AT)
                    portfolio = compile_channel_portfolio(request, strategy)
                    pack = ProductionPackCompiler().compile(request, strategy)
                    breakout = pack.breakout_growth_loop
                    challenger = pack.text_creative_challenger_plan
                    schedule_timezone = SCHEDULE_TIMEZONES[len(cases) % len(SCHEDULE_TIMEZONES)]
                    calendar = compile_content_calendar(
                        request,
                        strategy,
                        portfolio,
                        source_draft_ids={
                            pack.primary_copy.channel: pack.primary_copy.draft_id,
                            pack.secondary_copy.channel: pack.secondary_copy.draft_id,
                        },
                        compiled_at=COMPILED_AT,
                        schedule_timezone=schedule_timezone,
                    )
                    excluded = [
                        item["channel"]
                        for item in portfolio["portfolio"]
                        if item["activation_state"] == "excluded"
                    ]
                    cases.append(
                        {
                            "scenario_id": request.campaign_id.removeprefix("campaign-"),
                            "business_model": business_model.value,
                            "lifecycle": lifecycle.value,
                            "budget": budget.value,
                            "industry_risk": risk.value,
                            "strategy_id": strategy.strategy_id,
                            "portfolio_sha256": portfolio["content_sha256"],
                            "focus_channels": portfolio["focus_channels"],
                            "test_channels": portfolio["test_channels"],
                            "excluded_channels": excluded,
                            "governed_route_count": len(portfolio["portfolio"]),
                            "schedule_timezone": schedule_timezone,
                            "content_calendar_sha256": calendar["content_sha256"],
                            "breakout_growth_loop_sha256": breakout["content_sha256"],
                            "breakout_archetype": breakout["archetype"],
                            "breakout_step_ids": [
                                step["step_id"] for step in breakout["steps"]
                            ],
                            "breakout_core_organic_channel": breakout[
                                "core_organic_channel"
                            ],
                            "breakout_paid_amplifier_channel": breakout[
                                "paid_amplifier_channel"
                            ],
                            "breakout_paid_independent_core": breakout[
                                "core_loop_functions_without_paid_media"
                            ],
                            "breakout_external_action_performed": breakout[
                                "external_action_performed"
                            ],
                            "text_challenger_plan_sha256": challenger["content_sha256"],
                            "text_challenger_territory_ids": [
                                item["territory_id"] for item in challenger["territories"]
                            ],
                            "text_challenger_official_first_required": challenger[
                                "official_first_required"
                            ],
                            "text_challenger_maximum_model_calls": challenger[
                                "maximum_model_calls"
                            ],
                            "text_challenger_execution_mode": challenger[
                                "execution_policy"
                            ]["mode"],
                            "text_challenger_maximum_concurrency": challenger[
                                "execution_policy"
                            ]["maximum_concurrency"],
                            "text_challenger_default_retry_rounds": challenger[
                                "execution_policy"
                            ]["default_retry_rounds"],
                            "text_challenger_winner_selected": challenger[
                                "winner_selected"
                            ],
                            "text_challenger_external_publish_executed": challenger[
                                "external_publish_executed"
                            ],
                            "calendar_slot_count": calendar["slot_count"],
                            "calendar_window_start_utc": calendar["window_start_utc"],
                            "calendar_window_end_utc": calendar["window_end_utc"],
                            "external_activation_executed": False,
                        }
                    )
    core: dict[str, object] = {
        "schema": "ProofLaunchChannelPortfolioMatrixEvidenceV1",
        "compiled_at": COMPILED_AT,
        "scenario_count": len(cases),
        "dimensions": {
            "business_models": [item.value for item in BusinessModel],
            "lifecycle_stages": [item.value for item in LifecycleStage],
            "budget_tiers": [item.value for item in BudgetTier],
            "industry_risk_tiers": [item.value for item in IndustryRisk],
        },
        "invariants": {
            "governed_route_count_per_case": 12,
            "focus_channel_count_per_case": 2,
            "maximum_test_channel_count_per_case": 2,
            "zero_budget_paid_channel_exclusion": True,
            "automatic_activation_enabled": False,
            "calendar_slot_count_per_case": 7,
            "calendar_minimum_review_window_hours": 24,
            "calendar_automatic_publish_enabled": False,
            "breakout_step_ids": ["sense", "make", "seed", "convert", "learn"],
            "breakout_archetype_count": 8,
            "breakout_paid_independent_core": True,
            "breakout_automatic_external_action_enabled": False,
            "text_challenger_territory_ids": [
                "decision_xray",
                "proof_before_promise",
                "voluntary_relay",
            ],
            "text_challenger_official_first_required": True,
            "text_challenger_maximum_model_calls_per_case": 3,
            "text_challenger_execution_mode": "sequential_fail_fast",
            "text_challenger_maximum_concurrency": 1,
            "text_challenger_default_retry_rounds": 0,
            "text_challenger_automatic_winner_selection_enabled": False,
            "text_challenger_automatic_external_publish_enabled": False,
        },
        "cases": cases,
        "truth_boundary": (
            "This evidence is a deterministic synthetic contract matrix. It does not "
            "prove publication, reach, preference, lift, virality, revenue or model quality."
        ),
    }
    encoded = json.dumps(core, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    core["content_sha256"] = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    return core


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        default=str(ROOT / "evidence/v10/channel-portfolio-matrix.json"),
    )
    args = parser.parse_args()
    output = Path(args.output).resolve()
    try:
        output.relative_to(ROOT.resolve())
    except ValueError as error:
        raise SystemExit("output must remain inside the project root") from error
    matrix = build_matrix()
    atomic_write_text(
        output,
        json.dumps(matrix, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    print(
        json.dumps(
            {
                "output": str(output),
                "scenario_count": matrix["scenario_count"],
                "content_sha256": matrix["content_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
