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


class GTMAllSubverticalWave4ReviewQueueV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        discovery = json.loads((ROOT / "evidence/v10/gtm-all-subvertical-discovery-v2.json").read_text())
        capture = json.loads((ROOT / "evidence/v10/gtm-all-subvertical-wave4-unrouted-public-capture-v2.json").read_text())
        cls.payload = build_all_subvertical_review_queue(
            discovery,
            capture,
            source_origin="data/gtm_case_funnel_v2/all-subvertical-public-leads-wave4-classified-v2.json",
        )

    def test_builds_thirty_one_zero_credit_review_items(self) -> None:
        verify_all_subvertical_review_queue(self.payload)
        self.assertEqual(self.payload["review_item_count"], 31)
        self.assertEqual(self.payload["machine_ready_for_named_review_count"], 27)
        self.assertEqual(self.payload["evidence_gap_count"], 4)
        self.assertEqual(self.payload["formal_candidate_quota_credit"], 0)
        self.assertEqual(self.payload["observed_named_human_review_count"], 0)

    def test_machine_ready_requires_both_capture_and_named_identity(self) -> None:
        for row in self.payload["records"]:
            expected = row["source_capture_status"] == "captured_metadata_only" and row["identity_is_named"]
            self.assertEqual(row["machine_ready_for_named_review"], expected)
            self.assertEqual(row["formal_candidate_quota_credit"], 0)

    def test_all_routes_remain_provisional_and_source_bound(self) -> None:
        self.assertEqual(len({route for row in self.payload["records"] for route in row["provisional_subvertical_ids"]}), 13)
        self.assertTrue(all(row["source_capture_content_sha256"] for row in self.payload["records"]))
        self.assertTrue(all(row["human_source_inspection_completed"] is False for row in self.payload["records"]))

    def test_resealed_human_review_tamper_fails(self) -> None:
        tampered = copy.deepcopy(self.payload)
        tampered["records"][0]["named_reviewer"] = "fabricated"
        tampered["records"][0]["human_source_inspection_completed"] = True
        inner = tampered["records"][0]
        inner["packet_sha256"] = hashlib.sha256(json.dumps(
            {key: value for key, value in inner.items() if key != "packet_sha256"},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()).hexdigest()
        unsigned = dict(tampered)
        unsigned.pop("content_sha256")
        tampered["content_sha256"] = hashlib.sha256(json.dumps(
            unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()).hexdigest()
        with self.assertRaises(GTMAllSubverticalReviewQueueError):
            verify_all_subvertical_review_queue(tampered)


if __name__ == "__main__":
    unittest.main()
