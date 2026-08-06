from __future__ import annotations

import copy
import unittest

from prooflaunch_remix.gtm_seed_candidate_normalization import (
    GTMSeedCandidateNormalizationError,
    compile_seed_candidate_normalization,
    verify_seed_candidate_normalization,
)


class GTMSeedCandidateNormalizationTests(unittest.TestCase):
    def _seed(self, budget: str = "cold_start_low_budget") -> dict:
        return {
            "content_sha256": "a" * 64,
            "teams": [{
                "team_id": "one", "team_name": "One", "business_model": "b2b", "cold_start_budget_tier": budget,
                "observable_mechanism": "A source-bounded mechanism with a real proof object and distribution path.",
                "reported_outcomes": ["A bounded outcome"], "cold_start_budget_window": "A disclosed resource window",
            }],
        }

    def _capture(self) -> dict:
        return {
            "content_sha256": "b" * 64,
            "records": [{
                "capture_status": "captured_metadata_only", "source_context_ids": ["team:one"], "source_url": "https://example.com/one",
                "captured_at": "2026-08-04T12:00:00+00:00", "content_sha256": "c" * 64,
            }],
        }

    def _decision(self) -> dict:
        return {
            "team_id": "one", "subvertical_id": "b2b.b2b_saas.horizontal_saas", "business_model": "b2b", "product": "Product",
            "campaign_or_motion": "Proof loop", "campaign_or_motion_id": "proof-loop", "primary_audience": "Named business buyers",
            "observed_start": "2026-01-01", "observed_end": "2026-07-01", "company_scale": "small", "lifecycle_state": "growth",
            "recency_bucket": "three_to_six_months", "outcome_type": "recent_breakout", "quota_market": "north_america",
            "platforms": ["linkedin"], "classification_basis": "A bounded analyst classification from captured public evidence.",
        }

    def test_preserves_seed_as_zero_credit_budget_evidence_gap(self) -> None:
        payload = compile_seed_candidate_normalization(self._seed(), self._capture(), [self._decision()])
        verify_seed_candidate_normalization(payload)
        self.assertEqual(payload["candidate_count"], 1)
        self.assertEqual(payload["quota_eligible_candidate_count"], 0)
        self.assertEqual(payload["candidates"][0]["budget_tier"], "low_budget")
        self.assertEqual(set(payload["candidates"][0]["resource_costs"]), {"paid_media", "personnel", "tools", "creators", "channel_fees", "production"})
        self.assertTrue(all(row["disclosure_status"] == "unknown" for row in payload["candidates"][0]["resource_costs"].values()))
        self.assertEqual(payload["candidates"][0]["budget_quota_status"], "evidence_gap")
        self.assertEqual(payload["candidates"][0]["quota_credit"], 0)
        self.assertEqual(payload["promotion_boundary"]["mechanism_deep_audit_count"], 0)

    def test_zero_paid_does_not_treat_founder_labor_as_free(self) -> None:
        payload = compile_seed_candidate_normalization(self._seed("cold_start_zero_paid"), self._capture(), [self._decision()])
        costs = payload["candidates"][0]["resource_costs"]
        self.assertEqual(costs["paid_media"]["disclosure_status"], "known_zero")
        self.assertEqual(costs["paid_media"]["amount_usd"], 0)
        self.assertEqual(costs["personnel"]["disclosure_status"], "unknown")
        self.assertIsNone(costs["personnel"]["amount_usd"])
        self.assertEqual(payload["candidates"][0]["quota_credit"], 0)

    def test_undisclosed_budget_or_missing_capture_fails(self) -> None:
        with self.assertRaisesRegex(GTMSeedCandidateNormalizationError, "disclosed budget"):
            compile_seed_candidate_normalization(self._seed("undisclosed"), self._capture(), [self._decision()])
        with self.assertRaisesRegex(GTMSeedCandidateNormalizationError, "successful public source capture"):
            compile_seed_candidate_normalization(self._seed(), {"records": []}, [self._decision()])

    def test_tampering_fails_closed(self) -> None:
        payload = compile_seed_candidate_normalization(self._seed(), self._capture(), [self._decision()])
        tampered = copy.deepcopy(payload)
        tampered["candidates"][0]["quota_credit"] = 1
        with self.assertRaisesRegex(GTMSeedCandidateNormalizationError, "seal"):
            verify_seed_candidate_normalization(tampered)


if __name__ == "__main__":
    unittest.main()
