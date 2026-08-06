from __future__ import annotations

import copy
import unittest

from prooflaunch_remix.gtm_operating_context_v2 import COMPETITION_DIMENSIONS, compile_operating_context_matrix, verify_operating_context_matrix


H = "a" * 64


def scenario(*, scale: str = "small", lifecycle: str = "pre_pmf", budget: str = "zero_paid") -> dict:
    scale_data = {
        "small": {"founder_time_hours_per_week": 10, "sales_capacity_opportunities_per_month": 20, "cash_cycle_days": 30, "delivery_capacity_units_per_month": 25, "top_channel_share_pct": 70},
        "mid_market": {"cross_function_owners": ["marketing", "sales"], "brand_consistency_review": "weekly", "regions": ["north_america"], "channel_conflicts": ["direct versus partner"], "existing_customer_expansion_motion": "account expansion"},
        "enterprise_or_mass_brand": {"procurement_lead_time_days": 90, "legal_review_required": True, "markets": ["north_america"], "brand_governance_owner": "brand lead", "channel_partner_model": "partners", "organizational_change_cost_band": "high"},
    }[scale]
    lifecycle_data = {
        "pre_pmf": {"problem_validation_method": "interviews", "activation_event": "completed workflow"},
        "launch": {"first_audience": "operators", "first_channel": "linkedin", "first_value_moment": "proof created", "feedback_loop": "weekly interviews"},
        "growth": {"marginal_cac_usd": 200, "retention_rate": .9, "delivery_capacity_utilization_pct": 70, "channel_saturation_score": 50},
        "mature": {"brand_compounding_asset": "benchmark", "portfolio_efficiency_metric": "margin", "customer_expansion_metric": "NRR", "internationalization_scope": "two markets", "innovation_risk": "stagnation"},
    }[lifecycle]
    return {
        "scenario_id": f"s:{scale}:{lifecycle}:{budget}", "company_scale": scale, "lifecycle_state": lifecycle, "budget_tier": budget,
        "scale_inputs": scale_data, "lifecycle_inputs": lifecycle_data,
        "requested_objectives": ["problem_validation"] if lifecycle == "pre_pmf" else [],
        "resource_costs": {name: {"amount_usd": 0 if name == "paid_media" else 100, "disclosure_status": "known_zero" if name == "paid_media" else "bounded_estimate"} for name in ("paid_media", "personnel", "tools", "creators", "channel_fees", "production")},
        "budget_allocation": {"brand_building": 25, "demand_capture": 35, "retargeting": 15, "channel_incentives": 25} if budget in {"mixed_budget", "mature_scale"} else None,
        "competition_inputs": {dimension: {"score": 50, "evidence_receipt_sha256s": [H], "evidence_status": "observed"} for dimension in COMPETITION_DIMENSIONS},
    }


class GTMOperatingContextV2Tests(unittest.TestCase):
    def test_scale_lifecycle_budget_matrix_changes_constraints(self) -> None:
        rows = [scenario(scale=scale, lifecycle=lifecycle, budget=budget) for scale in ("small", "mid_market", "enterprise_or_mass_brand") for lifecycle in ("pre_pmf", "launch", "growth", "mature") for budget in ("zero_paid", "low_budget", "capital_efficient", "mixed_budget", "mature_scale")]
        payload = compile_operating_context_matrix(rows)
        verify_operating_context_matrix(payload)
        self.assertEqual(payload["scenario_count"], 60)
        self.assertEqual(payload["coverage"]["scale_lifecycle_budget_combinations"], 60)
        self.assertEqual(len({tuple(row["scale_contract"]["binding_constraints"]) for row in payload["scenarios"]}), 3)
        self.assertEqual(len({tuple(row["lifecycle_contract"]["required_proof"]) for row in payload["scenarios"]}), 4)

    def test_pre_pmf_scale_claim_and_free_founder_labor_fail_closed(self) -> None:
        raw = scenario()
        raw["requested_objectives"] = ["scalable_acquisition"]
        raw["resource_costs"]["personnel"] = {"amount_usd": 0, "disclosure_status": "known_zero"}
        row = compile_operating_context_matrix([raw])["scenarios"][0]
        self.assertEqual(row["status"], "operating_context_gap")
        self.assertIn("scalable_acquisition", row["blockers"])
        self.assertIn("personnel_cannot_be_assumed_free", row["blockers"])

    def test_scaled_budget_needs_four_way_allocation_and_pressure_is_computed(self) -> None:
        raw = scenario(scale="enterprise_or_mass_brand", lifecycle="mature", budget="mature_scale")
        raw["budget_allocation"] = None
        row = compile_operating_context_matrix([raw])["scenarios"][0]
        self.assertIn("four_way_budget_allocation_missing", row["blockers"])
        raw["budget_allocation"] = {"brand_building": 1, "demand_capture": 1, "retargeting": 1, "channel_incentives": 1}
        for item in raw["competition_inputs"].values(): item["score"] = 90
        row = compile_operating_context_matrix([raw])["scenarios"][0]
        self.assertEqual(row["competition_pressure_index"]["pressure_band"], "extreme")

    def test_tampering_fails(self) -> None:
        payload = compile_operating_context_matrix([scenario()])
        broken = copy.deepcopy(payload); broken["scenarios"][0]["observed_effect_claim_allowed"] = True
        with self.assertRaises(Exception): verify_operating_context_matrix(broken)


if __name__ == "__main__":
    unittest.main()
