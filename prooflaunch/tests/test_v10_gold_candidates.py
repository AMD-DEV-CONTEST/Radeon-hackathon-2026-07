from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class GoldCandidateTests(unittest.TestCase):
    def test_exact_300_briefs_and_150_campaigns_are_pre_review_candidates(self) -> None:
        report = json.loads(
            (ROOT / "evidence/v10/gold-candidates-independent-audit.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(report["status"], "passed_pre_review_candidates_not_human_gold")
        self.assertEqual(report["brief_candidate_count"], 300)
        self.assertEqual(report["campaign_candidate_count"], 150)
        self.assertEqual(report["unique_brief_count"], 300)
        self.assertEqual(report["unique_campaign_count"], 150)
        self.assertEqual(set(report["brief_channel_counts"].values()), {50})
        self.assertEqual(report["mechanical_brief_gate_failure_count"], 0)
        self.assertEqual(report["campaign_reference_failure_count"], 0)
        self.assertTrue(report["all_records_independently_reconstructed"])
        self.assertEqual(report["rights_failure_count"], 0)
        self.assertEqual(report["hidden_chain_of_thought_count"], 0)
        self.assertEqual(report["human_review_count"], 0)
        self.assertIsNone(report["human_mean_quality_score"])
        self.assertEqual(report["failure_count"], 0)


if __name__ == "__main__":
    unittest.main()
