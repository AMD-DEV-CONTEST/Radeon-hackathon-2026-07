from __future__ import annotations

import json
from pathlib import Path
import unittest

from prooflaunch_remix.gtm_all_subvertical_review_queue_v2 import verify_all_subvertical_review_queue
from prooflaunch_remix.gtm_public_source_capture import verify_public_source_capture


ROOT = Path(__file__).resolve().parents[1]


class GTMHighTransparencyWave8V2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.leads = json.loads((ROOT / "data/gtm_case_funnel_v2/high-transparency-public-leads-wave8-v2.json").read_text())
        cls.capture = json.loads((ROOT / "evidence/v10/gtm-high-transparency-wave8-public-capture-v2.json").read_text())
        cls.queue = json.loads((ROOT / "evidence/v10/gtm-high-transparency-wave8-review-queue-v2.json").read_text())

    def test_ten_high_transparency_leads_are_attributed_and_zero_credit(self) -> None:
        self.assertEqual(self.leads["record_count"], 10)
        self.assertTrue(all(row["outcome_evidence_independence"] == "founder_or_company_attributed_not_independent" for row in self.leads["records"]))
        self.assertTrue(all(row["formal_candidate_quota_credit"] == 0 for row in self.leads["records"]))

    def test_all_ten_public_pages_have_bounded_capture_receipts(self) -> None:
        verify_public_source_capture(self.capture)
        self.assertEqual(self.capture["requested_unique_source_count"], 10)
        self.assertEqual(self.capture["status_counts"], {"captured_metadata_only": 10})
        self.assertTrue(all(row["raw_page_retained"] is False for row in self.capture["records"]))

    def test_all_ten_enter_review_without_promotion(self) -> None:
        verify_all_subvertical_review_queue(self.queue)
        self.assertEqual(self.queue["review_item_count"], 10)
        self.assertEqual(self.queue["machine_ready_for_named_review_count"], 10)
        self.assertEqual(self.queue["evidence_gap_count"], 0)
        self.assertEqual(self.queue["observed_named_human_review_count"], 0)
        self.assertEqual(self.queue["formal_candidate_quota_credit"], 0)


if __name__ == "__main__":
    unittest.main()
