from __future__ import annotations

import copy
import unittest

from prooflaunch_remix.gtm_candidate_triage_v2 import (
    SELECTION_MARGINAL_TARGETS,
    compile_candidate_triage,
    score_candidate,
    verify_candidate_triage,
)


def candidate(index: int, *, recency: str = "three_to_six_months") -> dict:
    return {
        "case_id": f"case-{index:04d}",
        "subvertical_id": "b2b.test.example",
        "company": f"Company {index}",
        "product": "Industrial product",
        "campaign_or_motion": "Proof-led launch",
        "primary_audience": "Operations buyers",
        "observed_start": "2026-01-01",
        "observed_end": "2026-06-01",
        "episode_key": f"episode-{index}",
        "mechanism_hypothesis": "A public proof sequence moves attention through evaluation into conversion and retention.",
        "result_summary": "$2M revenue and 35% conversion growth in six months with customer retention.",
        "resource_scope": "Named team and production scope",
        "platforms": ["linkedin"],
        "source_receipts": [{"source_class": "independent_media"}, {"source_class": "official_company"}],
        "resource_costs": {name: {"disclosure_status": "disclosed"} for name in ("paid_media", "personnel", "tools", "creators", "channel_fees", "production")},
        "company_scale": list(SELECTION_MARGINAL_TARGETS["company_scale"])[index % 3],
        "lifecycle_state": list(SELECTION_MARGINAL_TARGETS["lifecycle_state"])[index % 4],
        "budget_tier": list(SELECTION_MARGINAL_TARGETS["budget_tier"])[index % 5],
        "recency_bucket": recency,
        "outcome_type": list(SELECTION_MARGINAL_TARGETS["outcome_type"])[index % 5],
        "quota_market": list(SELECTION_MARGINAL_TARGETS["quota_market"])[index % 8],
    }


class GTMCandidateTriageV2Tests(unittest.TestCase):
    def test_four_scores_are_deterministic_and_recent_signal_scores_higher(self) -> None:
        recent = score_candidate(candidate(1))
        historical = score_candidate(candidate(2, recency="historical_mechanism"))
        self.assertEqual(recent, score_candidate(candidate(1)))
        self.assertGreater(recent["recency_score"], historical["recency_score"])
        self.assertEqual(recent["quota_credit"], 0)

    def test_small_pool_selects_without_overclaiming_readiness(self) -> None:
        payload = compile_candidate_triage([candidate(i) for i in range(15)], subvertical_ids=["b2b.test.example", "b2c.empty.example"])
        verify_candidate_triage(payload)
        self.assertEqual(payload["candidate_score_count"], 15)
        self.assertEqual(payload["ready_subvertical_count"], 0)
        self.assertTrue(all(row["status"] == "selection_gap" for row in payload["subvertical_selections"]))

    def test_two_hundred_candidates_produce_at_most_forty_review_slots(self) -> None:
        payload = compile_candidate_triage([candidate(i) for i in range(200)], subvertical_ids=["b2b.test.example"])
        verify_candidate_triage(payload)
        row = payload["subvertical_selections"][0]
        self.assertEqual(row["candidate_count"], 200)
        self.assertEqual(row["selected_for_mechanism_review_count"], 40)
        self.assertEqual(row["mechanism_audit_credit"], 0)

    def test_tampering_fails(self) -> None:
        payload = compile_candidate_triage([candidate(1)], subvertical_ids=["b2b.test.example"])
        broken = copy.deepcopy(payload)
        broken["candidate_scores"][0]["quota_credit"] = 1
        with self.assertRaises(Exception):
            verify_candidate_triage(broken)


if __name__ == "__main__":
    unittest.main()
