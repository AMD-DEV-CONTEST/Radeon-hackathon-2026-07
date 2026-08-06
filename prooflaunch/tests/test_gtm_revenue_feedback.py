from __future__ import annotations

import unittest
from datetime import datetime, timezone

from prooflaunch_remix.gtm_effect_feedback import compile_effect_observation
from prooflaunch_remix.gtm_revenue_feedback import (
    RevenueFeedbackError,
    compile_revenue_economics,
)


def _effect(*, spend: float = 0.0, baseline: bool = True, conversions: int = 5):
    return compile_effect_observation(
        {
            "observation_id": "obs-revenue-001",
            "experiment_id": "experiment-revenue-001",
            "strategy_plan_sha256": "a" * 64,
            "source_kind": "first_party_analytics",
            "source_reference_sha256": "b" * 64,
            "channel": "linkedin_organic",
            "window_start": "2026-07-01T00:00:00Z",
            "window_end": "2026-07-08T00:00:00Z",
            "assignment_method": "observational",
            "metrics": {
                "eligible_reach": 100,
                "qualified_actions": 12,
                "evidence_engagements": 18,
                "complaints": 0,
                "conversions": conversions,
                "revenue_usd": 250.0,
                "spend_usd": spend,
            },
            "baseline_metrics": (
                {
                    "eligible_reach": 80,
                    "qualified_actions": 8,
                    "evidence_engagements": 12,
                    "complaints": 0,
                    "conversions": 3,
                    "revenue_usd": 150.0,
                    "spend_usd": 0.0,
                }
                if baseline
                else None
            ),
            "deduplicated": True,
            "bot_filter_applied": True,
        },
        expected_experiment_id="experiment-revenue-001",
        expected_strategy_plan_sha256="a" * 64,
        registered_minimum_samples={"qualified_action_rate": 50},
        zero_budget=spend == 0,
        received_at=datetime(2026, 7, 9, tzinfo=timezone.utc),
    )


def _row(*, candidate: bool = True, spend: float = 0.0, conversions: int | None = None):
    return {
        "conversions": conversions if conversions is not None else (5 if candidate else 3),
        "gross_revenue_usd": 250.0 if candidate else 150.0,
        "discounts_usd": 5.0 if candidate else 3.0,
        "refunds_usd": 5.0,
        "chargebacks_usd": 0.0,
        "variable_cogs_usd": 35.0 if candidate else 25.0,
        "fulfillment_cost_usd": 15.0 if candidate else 12.0,
        "platform_fees_usd": 7.0 if candidate else 5.0,
        "media_spend_usd": spend,
        "model_cost_usd": 2.0 if candidate else 1.0,
        "operator_cost_usd": 20.0 if candidate else 18.0,
        "qualified_pipeline_usd": 50000.0 if candidate else 20000.0,
    }


def _payload(effect, *, candidate=None, baseline="default"):
    baseline_row = _row(candidate=False) if baseline == "default" else baseline
    return {
        "economics_id": "economics-001",
        "effect_observation_id": effect["observation_id"],
        "effect_observation_sha256": effect["observation_sha256"],
        "source_reference_sha256": "c" * 64,
        "currency": "USD",
        "measurement_basis": "cash_collected",
        "candidate": candidate or _row(),
        "baseline": baseline_row,
    }


class RevenueEconomicsFeedbackTests(unittest.TestCase):
    def test_positive_contribution_feedback_excludes_pipeline_and_requires_human_review(self) -> None:
        effect = _effect()
        result = compile_revenue_economics(
            _payload(effect), effect_observation=effect, zero_budget=True
        )
        self.assertTrue(result["candidate_derived"]["positive_contribution_observed"])
        self.assertTrue(result["contribution_improved_vs_baseline"])
        self.assertTrue(result["revenue_positive_feedback_ready"])
        self.assertEqual(
            result["next_cycle_decision"], "continue_candidate_for_human_revenue_review"
        )
        self.assertFalse(result["pipeline_counted_as_revenue"])
        self.assertEqual(result["candidate_derived"]["qualified_pipeline_usd"], 50000.0)
        self.assertFalse(result["causal_revenue_claim_allowed"])
        self.assertFalse(result["annualized_projection_allowed"])
        self.assertTrue(result["human_revenue_review_required"])

    def test_negative_contribution_stops_even_when_gross_revenue_is_positive(self) -> None:
        effect = _effect()
        candidate = _row()
        candidate["operator_cost_usd"] = 500.0
        result = compile_revenue_economics(
            _payload(effect, candidate=candidate),
            effect_observation=effect,
            zero_budget=True,
        )
        self.assertLess(result["candidate_derived"]["contribution_profit_usd"], 0)
        self.assertFalse(result["revenue_positive_feedback_ready"])
        self.assertEqual(
            result["next_cycle_decision"], "stop_and_review_negative_contribution"
        )

    def test_zero_media_budget_breach_stops_before_positive_economics(self) -> None:
        effect = _effect(spend=10.0)
        candidate = _row(spend=10.0)
        result = compile_revenue_economics(
            _payload(effect, candidate=candidate),
            effect_observation=effect,
            zero_budget=True,
        )
        self.assertTrue(result["zero_budget_contract_breach"])
        self.assertEqual(
            result["next_cycle_decision"], "stop_and_review_zero_budget_breach"
        )
        self.assertFalse(result["automatic_budget_activation_executed"])

    def test_pipeline_never_substitutes_for_closed_conversion_sample(self) -> None:
        effect = _effect(conversions=1)
        candidate = _row(conversions=1)
        candidate["qualified_pipeline_usd"] = 999999999.0
        result = compile_revenue_economics(
            _payload(effect, candidate=candidate),
            effect_observation=effect,
            zero_budget=True,
        )
        self.assertEqual(
            result["next_cycle_decision"], "collect_more_closed_conversion_data"
        )
        self.assertFalse(result["revenue_positive_feedback_ready"])

    def test_missing_baseline_remains_descriptive(self) -> None:
        effect = _effect(baseline=False)
        result = compile_revenue_economics(
            _payload(effect, baseline=None),
            effect_observation=effect,
            zero_budget=True,
        )
        self.assertEqual(
            result["next_cycle_decision"],
            "establish_comparable_unit_economics_baseline",
        )
        self.assertFalse(result["comparison_ready"])

    def test_refund_regression_blocks_otherwise_positive_candidate(self) -> None:
        effect = _effect()
        candidate = _row()
        candidate["refunds_usd"] = 30.0
        result = compile_revenue_economics(
            _payload(effect, candidate=candidate),
            effect_observation=effect,
            zero_budget=True,
        )
        self.assertTrue(result["refund_or_chargeback_regression"])
        self.assertEqual(
            result["next_cycle_decision"],
            "stop_and_review_refund_or_chargeback_regression",
        )

    def test_revenue_conversion_or_spend_mismatch_fails_source_binding(self) -> None:
        effect = _effect()
        for key, value, message in (
            ("gross_revenue_usd", 251.0, "gross revenue"),
            ("conversions", 4, "conversions"),
            ("media_spend_usd", 1.0, "media spend"),
        ):
            candidate = _row()
            candidate[key] = value
            with self.subTest(key=key):
                with self.assertRaisesRegex(RevenueFeedbackError, message):
                    compile_revenue_economics(
                        _payload(effect, candidate=candidate),
                        effect_observation=effect,
                        zero_budget=True,
                    )

    def test_unknown_fields_currency_or_measurement_basis_fail_closed(self) -> None:
        effect = _effect()
        unknown = _payload(effect)
        unknown["projected_arr_usd"] = 1000000
        with self.assertRaisesRegex(RevenueFeedbackError, "incomplete or unknown"):
            compile_revenue_economics(unknown, effect_observation=effect, zero_budget=True)
        currency = _payload(effect)
        currency["currency"] = "EUR"
        with self.assertRaisesRegex(RevenueFeedbackError, "normalized USD"):
            compile_revenue_economics(currency, effect_observation=effect, zero_budget=True)
        basis = _payload(effect)
        basis["measurement_basis"] = "forecast"
        with self.assertRaisesRegex(RevenueFeedbackError, "not admitted"):
            compile_revenue_economics(basis, effect_observation=effect, zero_budget=True)


if __name__ == "__main__":
    unittest.main()
