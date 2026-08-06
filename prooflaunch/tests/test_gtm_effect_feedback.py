from __future__ import annotations

import unittest
from datetime import datetime, timezone

from prooflaunch_remix.gtm_effect_feedback import (
    EffectFeedbackError,
    compile_effect_observation,
)


NOW = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)
STRATEGY_SHA = "a" * 64
SOURCE_SHA = "b" * 64


def metrics(
    reach: int = 100,
    qualified: int = 12,
    engagement: int = 30,
    complaints: int = 1,
    conversions: int = 5,
    revenue: float = 250.0,
    spend: float = 0.0,
) -> dict[str, int | float]:
    return {
        "eligible_reach": reach,
        "qualified_actions": qualified,
        "evidence_engagements": engagement,
        "complaints": complaints,
        "conversions": conversions,
        "revenue_usd": revenue,
        "spend_usd": spend,
    }


def payload() -> dict[str, object]:
    return {
        "observation_id": "obs-launch-001",
        "experiment_id": "exp-launch-001",
        "strategy_plan_sha256": STRATEGY_SHA,
        "source_kind": "first_party_analytics",
        "source_reference_sha256": SOURCE_SHA,
        "channel": "short_video_organic",
        "window_start": "2026-08-01T00:00:00Z",
        "window_end": "2026-08-02T00:00:00Z",
        "assignment_method": "observational",
        "metrics": metrics(),
        "baseline_metrics": metrics(100, 8, 20, 1, 3, 150),
        "deduplicated": True,
        "bot_filter_applied": True,
    }


class EffectFeedbackTests(unittest.TestCase):
    def compile(self, candidate: dict[str, object]) -> dict[str, object]:
        return compile_effect_observation(
            candidate,
            expected_experiment_id="exp-launch-001",
            expected_strategy_plan_sha256=STRATEGY_SHA,
            registered_minimum_samples={
                "qualified_action_rate": 25,
                "evidence_engagement_rate": 25,
                "unsubscribe_or_complaint_rate": 1,
            },
            zero_budget=True,
            received_at=NOW,
        )

    def test_sufficient_observation_produces_human_review_candidate_not_causal_claim(self) -> None:
        result = self.compile(payload())
        self.assertEqual(
            result["next_cycle_decision"], "continue_candidate_for_human_review"
        )
        self.assertEqual(result["evidence_class"], "observational_attribution")
        self.assertFalse(result["causal_outcome_claim_allowed"])
        self.assertFalse(result["automatic_strategy_mutation_executed"])
        self.assertRegex(result["observation_sha256"], r"^[0-9a-f]{64}$")

    def test_low_sample_requires_more_data(self) -> None:
        candidate = payload()
        candidate["metrics"] = metrics(10, 1, 3, 0, 0, 0)
        candidate["baseline_metrics"] = None
        result = self.compile(candidate)
        self.assertEqual(result["next_cycle_decision"], "collect_more_data")
        self.assertFalse(result["observed_sample_gate_passed"])

    def test_zero_budget_spend_and_guardrail_regression_stop(self) -> None:
        spend = payload()
        spend["metrics"] = metrics(spend=1.0)
        self.assertEqual(self.compile(spend)["next_cycle_decision"], "stop_and_review")
        self.assertTrue(self.compile(spend)["zero_budget_contract_breach"])

        complaint = payload()
        complaint["metrics"] = metrics(complaints=5)
        self.assertEqual(
            self.compile(complaint)["next_cycle_decision"], "stop_and_review"
        )

    def test_identity_future_time_unknown_fields_and_pii_fail_closed(self) -> None:
        wrong = payload()
        wrong["experiment_id"] = "exp-other"
        with self.assertRaisesRegex(EffectFeedbackError, "preregistered"):
            self.compile(wrong)

        future = payload()
        future["window_end"] = "2026-08-03T00:00:00Z"
        with self.assertRaisesRegex(EffectFeedbackError, "future"):
            self.compile(future)

        pii = payload()
        pii["user_email"] = "person@example.test"
        with self.assertRaisesRegex(EffectFeedbackError, "unknown"):
            self.compile(pii)


if __name__ == "__main__":
    unittest.main()
