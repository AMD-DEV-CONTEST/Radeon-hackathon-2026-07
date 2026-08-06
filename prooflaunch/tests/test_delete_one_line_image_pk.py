from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKET = ROOT / "artifacts/gtm-last-mile-pk-v1/delete-one-line-qwen-image-ab-v1"
PORTFOLIO = ROOT / "evidence/v10/delete-one-line-four-lane-named-pk-portfolio-v2.json"


def verify(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    supplied = payload.pop("content_sha256")
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    if supplied != hashlib.sha256(canonical).hexdigest():
        raise AssertionError(f"sealed payload drifted: {path}")
    payload["content_sha256"] = supplied
    return payload


class DeleteOneLineImagePKTests(unittest.TestCase):
    def test_qwen_packet_is_source_hidden_and_empty(self) -> None:
        receipt = verify(PACKET / "packet-receipt.json")
        public = verify(PACKET / "public/packet.json")
        private = verify(PACKET / "private/mapping.json")
        self.assertEqual(receipt["reviewer_kit_count"], 5)
        self.assertEqual(receipt["submitted_review_count"], 0)
        self.assertTrue(public["reference_product_hidden_from_reviewers"])
        self.assertEqual(public["expected_review_count"], 5)
        self.assertEqual(public["submitted_review_count"], 0)
        self.assertEqual(len(private["task_side_mapping"]), 5)
        self.assertIn(private["challenger_left_count"], (2, 3))
        for slot in range(1, 6):
            page = (PACKET / f"public/reviewer-{slot:02d}.html").read_text(encoding="utf-8")
            self.assertNotIn("Qwen-Image", page)
            self.assertNotIn("CHALLENGER", page)

    def test_four_lane_portfolio_stays_truth_bound(self) -> None:
        payload = verify(PORTFOLIO)
        self.assertEqual(payload["lane_count"], 4)
        self.assertEqual(payload["named_product_row_count"], 40)
        self.assertEqual(payload["authorized_named_product_baseline_count"], 1)
        self.assertEqual(payload["source_hidden_five_human_packet_count"], 1)
        self.assertEqual(payload["qualified_human_review_count"], 0)
        self.assertEqual(payload["candidate_win_count"], 0)
        qwen = next(row for row in payload["rows"] if row["reference_product"] == "Qwen-Image")
        self.assertTrue(qwen["authorized_named_product_baseline_present"])
        self.assertTrue(qwen["source_hidden_five_human_packet_present"])
        self.assertFalse(qwen["candidate_won"])


if __name__ == "__main__":
    unittest.main()
