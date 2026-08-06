#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import replace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))

from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.gtm_channel_portfolio import compile_channel_portfolio
from prooflaunch_remix.gtm_strategy import (
    BudgetTier,
    BusinessModel,
    CompanyScale,
    ContentCapacity,
    DistributionStrength,
    IndustryRisk,
    LifecycleStage,
    SalesMotion,
    StrategyCompiler,
)
from scripts.compile_gtm_channel_portfolio_matrix import COMPILED_AT, _request


PROFILES = {
    "baseline_startup": {
        "company_scale": CompanyScale.STARTUP,
        "brand_reach": DistributionStrength.EMERGING,
        "owned_audience_strength": DistributionStrength.EMERGING,
        "community_access": DistributionStrength.EMERGING,
        "partner_access": DistributionStrength.EMERGING,
        "content_capacity": ContentCapacity.STANDARD,
        "sales_motion": SalesMotion.HYBRID,
    },
    "solo_cold_start": {
        "company_scale": CompanyScale.SOLO,
        "brand_reach": DistributionStrength.NONE,
        "owned_audience_strength": DistributionStrength.NONE,
        "community_access": DistributionStrength.NONE,
        "partner_access": DistributionStrength.NONE,
        "content_capacity": ContentCapacity.LEAN,
        "sales_motion": SalesMotion.SALES_LED,
    },
    "startup_community": {
        "company_scale": CompanyScale.STARTUP,
        "brand_reach": DistributionStrength.EMERGING,
        "owned_audience_strength": DistributionStrength.NONE,
        "community_access": DistributionStrength.STRONG,
        "partner_access": DistributionStrength.EMERGING,
        "content_capacity": ContentCapacity.STANDARD,
        "sales_motion": SalesMotion.HYBRID,
    },
    "scaleup_partner": {
        "company_scale": CompanyScale.SCALEUP,
        "brand_reach": DistributionStrength.ESTABLISHED,
        "owned_audience_strength": DistributionStrength.ESTABLISHED,
        "community_access": DistributionStrength.ESTABLISHED,
        "partner_access": DistributionStrength.STRONG,
        "content_capacity": ContentCapacity.STANDARD,
        "sales_motion": SalesMotion.SALES_LED,
    },
    "enterprise_owned": {
        "company_scale": CompanyScale.ENTERPRISE,
        "brand_reach": DistributionStrength.STRONG,
        "owned_audience_strength": DistributionStrength.STRONG,
        "community_access": DistributionStrength.ESTABLISHED,
        "partner_access": DistributionStrength.STRONG,
        "content_capacity": ContentCapacity.STANDARD,
        "sales_motion": SalesMotion.SALES_LED,
    },
    "creator_studio": {
        "company_scale": CompanyScale.STARTUP,
        "brand_reach": DistributionStrength.ESTABLISHED,
        "owned_audience_strength": DistributionStrength.ESTABLISHED,
        "community_access": DistributionStrength.STRONG,
        "partner_access": DistributionStrength.EMERGING,
        "content_capacity": ContentCapacity.STUDIO,
        "sales_motion": SalesMotion.SELF_SERVE,
    },
    "selfserve_lean": {
        "company_scale": CompanyScale.SCALEUP,
        "brand_reach": DistributionStrength.NONE,
        "owned_audience_strength": DistributionStrength.EMERGING,
        "community_access": DistributionStrength.NONE,
        "partner_access": DistributionStrength.NONE,
        "content_capacity": ContentCapacity.LEAN,
        "sales_motion": SalesMotion.SELF_SERVE,
    },
    "enterprise_hybrid_studio": {
        "company_scale": CompanyScale.ENTERPRISE,
        "brand_reach": DistributionStrength.STRONG,
        "owned_audience_strength": DistributionStrength.STRONG,
        "community_access": DistributionStrength.STRONG,
        "partner_access": DistributionStrength.STRONG,
        "content_capacity": ContentCapacity.STUDIO,
        "sales_motion": SalesMotion.HYBRID,
    },
}

SIGNAL_SCENARIOS: dict[str, dict[str, int]] = {
    "no_signal": {},
    "video_signal": {"youtube": 13, "vimeo": 15},
    "professional_search_signal": {"linkedin": 15, "google": 10},
    "community_signal": {"reddit": 12, "discord": 12},
    "owned_social_signal": {"instagram": 18, "threads": 8},
}


def build_matrix() -> dict[str, object]:
    cases: list[dict[str, object]] = []
    for business_model in BusinessModel:
        for lifecycle in LifecycleStage:
            for budget in BudgetTier:
                for risk in IndustryRisk:
                    base_request = _request(business_model, lifecycle, budget, risk)
                    for profile_id, profile in PROFILES.items():
                        request = replace(
                            base_request,
                            campaign_id=(
                                f"{base_request.campaign_id}-{profile_id}"
                            ),
                            **profile,
                        )
                        for signal_id, signal_counts in SIGNAL_SCENARIOS.items():
                            strategy = StrategyCompiler().compile(
                                request,
                                at=COMPILED_AT,
                                signal_platform_counts=signal_counts,
                            )
                            portfolio = compile_channel_portfolio(
                                request,
                                strategy,
                                signal_platform_counts=signal_counts,
                            )
                            paid_rows = [
                                row for row in portfolio["portfolio"]
                                if row["paid_channel"]
                            ]
                            cases.append(
                                {
                                    "case_id": (
                                        f"{business_model.value}-{lifecycle.value}-"
                                        f"{budget.value}-{risk.value}-{profile_id}-{signal_id}"
                                    ),
                                    "business_model": business_model.value,
                                    "lifecycle": lifecycle.value,
                                    "budget": budget.value,
                                    "industry_risk": risk.value,
                                    "profile_id": profile_id,
                                    "signal_id": signal_id,
                                    "decision_context": portfolio["decision_context"],
                                    "authorized_platform_signal_counts": portfolio[
                                        "authorized_platform_signal_counts"
                                    ],
                                    "strategy_id": strategy.strategy_id,
                                    "focus_channels": portfolio["focus_channels"],
                                    "test_channels": portfolio["test_channels"],
                                    "focus_margin_points": portfolio[
                                        "focus_margin_points"
                                    ],
                                    "decision_confidence": portfolio[
                                        "decision_confidence"
                                    ],
                                    "frontier_channels": [
                                        row["channel"]
                                        for row in portfolio["opportunity_frontier"]
                                    ],
                                    "zero_budget_paid_exclusion_passed": (
                                        budget is not BudgetTier.ZERO
                                        or all(
                                            row["activation_state"] == "excluded"
                                            and row["score"] == 0
                                            for row in paid_rows
                                        )
                                    ),
                                    "automatic_activation_executed": portfolio[
                                        "external_activation_executed"
                                    ],
                                    "automatic_reallocation_executed": portfolio[
                                        "automatic_reallocation_executed"
                                    ],
                                    "portfolio_sha256": portfolio["content_sha256"],
                                }
                            )
    core: dict[str, object] = {
        "schema": "ProofLaunchDistributionAdvantageMatrixV2",
        "compiled_at": COMPILED_AT,
        "scenario_count": len(cases),
        "matrix_design": "48_core_contracts_x_8_distribution_profiles_x_5_authorized_signal_scenarios",
        "dimensions": {
            "business_models": [item.value for item in BusinessModel],
            "lifecycle_stages": [item.value for item in LifecycleStage],
            "budget_tiers": [item.value for item in BudgetTier],
            "industry_risk_tiers": [item.value for item in IndustryRisk],
            "distribution_profile_ids": list(PROFILES),
            "authorized_signal_scenario_ids": list(SIGNAL_SCENARIOS),
            "company_scales_covered": [item.value for item in CompanyScale],
            "distribution_strengths_covered": [
                item.value for item in DistributionStrength
            ],
            "content_capacities_covered": [item.value for item in ContentCapacity],
            "sales_motions_covered": [item.value for item in SalesMotion],
        },
        "invariants": {
            "exact_focus_channels_per_case": 2,
            "maximum_test_channels_per_case": 2,
            "opportunity_frontier_channels_per_case": 4,
            "zero_budget_paid_channel_exclusion": True,
            "automatic_activation_enabled": False,
            "automatic_reallocation_enabled": False,
            "reallocation_scope": "named_human_review_next_run_only",
        },
        "cases": cases,
        "truth_boundary": (
            "This is a synthetic deterministic decision matrix. Scores are relative "
            "prioritization, not forecasts, and do not prove access, publication, reach, "
            "lift, preference, virality, revenue, 4A effect or Top-1 standing."
        ),
    }
    encoded = json.dumps(
        core,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    core["content_sha256"] = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    return core


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        default=str(
            ROOT / "evidence/v10/gtm-distribution-advantage-matrix-v2.json"
        ),
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
