from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import unittest

from prooflaunch_remix.gtm_all_subvertical_review_queue_v2 import (
    GTMAllSubverticalReviewQueueError,
    build_all_subvertical_review_queue,
    verify_all_subvertical_review_queue,
)


ROOT = Path(__file__).resolve().parents[1]


class GTMAllSubverticalReviewQueueV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        discovery = json.loads((ROOT / "evidence/v10/gtm-all-subvertical-discovery-v2.json").read_text())
        capture = json.loads((ROOT / "evidence/v10/gtm-all-subvertical-wave1-public-capture-v2.json").read_text())
        cls.payload = build_all_subvertical_review_queue(
            discovery,
            capture,
            source_origin="data/gtm_case_funnel_v2/all-subvertical-public-leads-wave1-v2.json",
        )

    def test_builds_fifteen_zero_credit_review_items(self) -> None:
        verify_all_subvertical_review_queue(self.payload)
        self.assertEqual(self.payload["review_item_count"], 15)
        self.assertEqual(self.payload["formal_candidate_quota_credit"], 0)
        self.assertEqual(self.payload["observed_named_human_review_count"], 0)

    def test_pdf_failure_and_unnamed_identity_are_explicit_gaps(self) -> None:
        pdf = next(row for row in self.payload["records"] if ".pdf" in row["source_url"])
        self.assertEqual(pdf["status"], "evidence_gap")
        self.assertIn("public_source_capture", pdf["candidate_gate_blockers"])
        unnamed = next(row for row in self.payload["records"] if row["company"].startswith("Undisclosed"))
        self.assertIn("named_company_identity", unnamed["candidate_gate_blockers"])

    def test_ready_means_reviewable_not_admitted(self) -> None:
        ready = [row for row in self.payload["records"] if row["machine_ready_for_named_review"]]
        self.assertTrue(ready)
        self.assertTrue(all(row["formal_candidate_quota_credit"] == 0 for row in ready))
        self.assertTrue(all(row["human_source_inspection_completed"] is False for row in ready))

    def test_resealed_human_review_tamper_fails(self) -> None:
        tampered = copy.deepcopy(self.payload)
        tampered["records"][0]["named_reviewer"] = "fabricated-reviewer"
        tampered["records"][0]["human_source_inspection_completed"] = True
        inner = tampered["records"][0]
        inner["packet_sha256"] = hashlib.sha256(
            json.dumps({key: value for key, value in inner.items() if key != "packet_sha256"}, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        ).hexdigest()
        unsigned = dict(tampered)
        unsigned.pop("content_sha256")
        tampered["content_sha256"] = hashlib.sha256(
            json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        ).hexdigest()
        with self.assertRaises(GTMAllSubverticalReviewQueueError):
            verify_all_subvertical_review_queue(tampered)


if __name__ == "__main__":
    unittest.main()
