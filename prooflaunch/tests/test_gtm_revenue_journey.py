from __future__ import annotations

import copy
import unittest

from prooflaunch_remix.gtm_revenue_journey import (
    RevenueJourneyError,
    compile_revenue_journey_operations,
    verify_revenue_journey_operations,
)
from tests.test_gtm_production_pack import compile_pack


class RevenueJourneyTests(unittest.TestCase):
    def build(self):
        request, strategy, _ = compile_pack()
        return compile_revenue_journey_operations(
            request,
            strategy,
            compiled_at="2026-08-05T12:00:00Z",
        )

    def test_search_geo_email_sales_tracking_and_incrementality_contracts_are_complete(self) -> None:
        receipt = self.build()

        self.assertEqual(
            {row["intent"] for row in receipt["search_intent_graph"]},
            {"learn", "compare", "decide", "migrate", "troubleshoot", "validate_brand"},
        )
        self.assertTrue(receipt["information_gain_gate"]["mechanical_gate_passed"])
        self.assertFalse(receipt["information_gain_gate"]["search_publication_allowed"])
        self.assertEqual(len(receipt["geo_answer_graph"]), 6)
        self.assertEqual(receipt["citability_score"]["mechanical_score"], 1.0)
        self.assertFalse(receipt["citability_score"]["answer_published"])
        self.assertEqual(len(receipt["lifecycle_email_state_machine"]), 8)
        self.assertTrue(all(not row["automatic_send_enabled"] for row in receipt["lifecycle_email_state_machine"]))
        self.assertFalse(receipt["sales_enablement_pack"]["case_narrative"]["customer_outcome_claim_allowed"])
        self.assertFalse(receipt["incrementality_rules"]["current_causal_claim_allowed"])
        verify_revenue_journey_operations(receipt)

    def test_every_revenue_event_retains_content_creative_platform_and_claim_trace(self) -> None:
        receipt = self.build()
        events = receipt["event_tracking_contract"]["events"]
        required = {"content_id", "creative_version", "platform", "audience_id", "cta_id", "landing_page_id", "experiment_id", "claim_id", "occurred_at"}
        self.assertTrue(all(required.issubset(row["required_dimensions"]) for row in events))
        self.assertIn("currency", next(row for row in events if row["event"] == "revenue")["required_dimensions"])

    def test_tampering_fails_closed(self) -> None:
        receipt = self.build()
        tampered = copy.deepcopy(receipt)
        tampered["incrementality_rules"]["current_causal_claim_allowed"] = True
        with self.assertRaises(RevenueJourneyError):
            verify_revenue_journey_operations(tampered)


if __name__ == "__main__":
    unittest.main()
