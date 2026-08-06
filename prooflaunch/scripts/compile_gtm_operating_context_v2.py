#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.gtm_operating_context_v2 import BUDGETS, COMPETITION_DIMENSIONS, LIFECYCLES, SCALES, compile_operating_context_matrix, verify_operating_context_matrix


ROOT = Path(__file__).resolve().parents[1]
H = hashlib.sha256(b"synthetic-operating-context-regression-fixture").hexdigest()


def scale_inputs(scale: str) -> dict:
    if scale == "small":
        return {"founder_time_hours_per_week": 12, "sales_capacity_opportunities_per_month": 20, "cash_cycle_days": 45, "delivery_capacity_units_per_month": 30, "top_channel_share_pct": 55}
    if scale == "mid_market":
        return {"cross_function_owners": ["marketing", "sales"], "brand_consistency_review": "weekly", "regions": ["north_america"], "channel_conflicts": [], "existing_customer_expansion_motion": "quarterly account expansion"}
    return {"procurement_lead_time_days": 90, "legal_review_required": True, "markets": ["north_america", "uk_ireland"], "brand_governance_owner": "global brand", "channel_partner_model": "authorized partners", "organizational_change_cost_band": "high"}


def lifecycle_inputs(lifecycle: str) -> dict:
    return {
        "pre_pmf": {"problem_validation_method": "customer interviews", "activation_event": "completed first proof workflow"},
        "launch": {"first_audience": "named operator cohort", "first_channel": "linkedin", "first_value_moment": "inspectable proof created", "feedback_loop": "weekly interview and behavior review"},
        "growth": {"marginal_cac_usd": 300, "retention_rate": 0.88, "delivery_capacity_utilization_pct": 70, "channel_saturation_score": 45},
        "mature": {"brand_compounding_asset": "annual benchmark", "portfolio_efficiency_metric": "contribution margin", "customer_expansion_metric": "net revenue retention", "internationalization_scope": "two English markets", "innovation_risk": "category stagnation"},
    }[lifecycle]


def main() -> int:
    scenarios = []
    for scale in SCALES:
        for lifecycle in LIFECYCLES:
            for budget in BUDGETS:
                scenarios.append({
                    "scenario_id": f"synthetic:{scale}:{lifecycle}:{budget}",
                    "company_scale": scale, "lifecycle_state": lifecycle, "budget_tier": budget,
                    "scale_inputs": scale_inputs(scale), "lifecycle_inputs": lifecycle_inputs(lifecycle),
                    "requested_objectives": ["problem_validation"] if lifecycle == "pre_pmf" else [],
                    "resource_costs": {name: {"amount_usd": 0 if name == "paid_media" and budget == "zero_paid" else 100, "disclosure_status": "known_zero" if name == "paid_media" and budget == "zero_paid" else "bounded_estimate"} for name in ("paid_media", "personnel", "tools", "creators", "channel_fees", "production")},
                    "budget_allocation": {"brand_building": 25, "demand_capture": 35, "retargeting": 15, "channel_incentives": 25} if budget in {"mixed_budget", "mature_scale"} else None,
                    "competition_inputs": {dimension: {"score": 60, "evidence_receipt_sha256s": [H], "evidence_status": "synthetic_regression_fixture"} for dimension in COMPETITION_DIMENSIONS},
                })
    payload = compile_operating_context_matrix(scenarios)
    verify_operating_context_matrix(payload)
    output = ROOT / "evidence/v10/gtm-operating-context-matrix-v2.json"
    atomic_write_text(output, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": str(output), "scenario_count": payload["scenario_count"], "coverage": payload["coverage"], "content_sha256": payload["content_sha256"]}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
