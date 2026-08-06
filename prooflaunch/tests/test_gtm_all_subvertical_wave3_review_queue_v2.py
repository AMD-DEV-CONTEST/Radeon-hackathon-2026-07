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


class GTMAllSubverticalWave3ReviewQueueV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        discovery = json.loads((ROOT / "evidence/v10/gtm-all-subvertical-discovery-v2.json").read_text())
        capture = json.loads(
            (ROOT / "evidence/v10/gtm-all-subvertical-wave3-b2c-public-capture-v2.json").read_text()
        )
        cls.payload = build_all_subvertical_review_queue(
            discovery,
            capture,
            source_origin="data/gtm_case_funnel_v2/all-subvertical-public-leads-wave3-b2c-v2.json",
        )

    def test_builds_thirty_five_zero_credit_review_items(self) -> None:
        verify_all_subvertical_review_queue(self.payload)
        self.assertEqual(self.payload["review_item_count"], 35)
        self.assertEqual(self.payload["formal_candidate_quota_credit"], 0)
        self.assertEqual(self.payload["observed_named_human_review_count"], 0)

    def test_every_previously_unrouted_b2c_subvertical_has_one_review_item(self) -> None:
        routes = {
            subvertical_id
            for row in self.payload["records"]
            for subvertical_id in row["provisional_subvertical_ids"]
        }
        self.assertEqual(len(routes), 35)
        self.assertTrue(all(subvertical_id.startswith("b2c.") for subvertical_id in routes))

    def test_capture_and_robots_failures_remain_explicit_gaps(self) -> None:
        failures = [row for row in self.payload["records"] if row["source_capture_status"] != "captured_metadata_only"]
        self.assertEqual(len(failures), 5)
        self.assertTrue(all("public_source_capture" in row["candidate_gate_blockers"] for row in failures))
        self.assertTrue(any(row["source_capture_status"] == "blocked_by_robots" for row in failures))

    def test_resealed_human_review_tamper_fails(self) -> None:
        tampered = copy.deepcopy(self.payload)
        tampered["records"][0]["named_reviewer"] = "fabricated-reviewer"
        tampered["records"][0]["human_source_inspection_completed"] = True
        inner = tampered["records"][0]
        inner["packet_sha256"] = hashlib.sha256(
            json.dumps(
                {key: value for key, value in inner.items() if key != "packet_sha256"},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode()
        ).hexdigest()
        unsigned = dict(tampered)
        unsigned.pop("content_sha256")
        tampered["content_sha256"] = hashlib.sha256(
            json.dumps(
                unsigned,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode()
        ).hexdigest()
        with self.assertRaises(GTMAllSubverticalReviewQueueError):
            verify_all_subvertical_review_queue(tampered)


if __name__ == "__main__":
    unittest.main()
