from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKET = ROOT / "artifacts/gtm-last-mile-pk-v1/named-product-pk-mem0-v2/review-packet"
PORTFOLIO = ROOT / "evidence/v10/delete-one-line-six-lane-named-pk-portfolio-v4.json"


def verify(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    supplied = payload.pop("content_sha256")
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    if supplied != hashlib.sha256(canonical).hexdigest():
        raise AssertionError(f"sealed payload drifted: {path}")
    payload["content_sha256"] = supplied
    return payload


class DeleteOneLineMemoryPKTests(unittest.TestCase):
    def test_mem0_packet_is_source_hidden_and_mechanically_complete(self) -> None:
        public = verify(PACKET / "public/packet.json")
        private = verify(PACKET / "private/mapping.json")
        self.assertEqual(public["expected_review_count"], 5)
        self.assertEqual(public["submitted_review_count"], 0)
        self.assertFalse(public["source_roles_exposed"])
        self.assertFalse(public["model_judge_can_promote"])
        self.assertEqual(len(private["task_side_mapping"]), 5)
        self.assertEqual(len({task["frozen_brief_sha256"] for task in public["review_tasks"]}), 1)
        for path in (PACKET / "public/assets").glob("*.json"):
            self.assertIsInstance(json.loads(path.read_text(encoding="utf-8")), dict)

    def test_six_lane_portfolio_adds_only_one_memory_baseline(self) -> None:
        payload = verify(PORTFOLIO)
        self.assertEqual(payload["lane_count"], 6)
        self.assertEqual(payload["named_product_row_count"], 60)
        self.assertEqual(payload["authorized_named_product_baseline_count"], 3)
        self.assertEqual(payload["source_hidden_five_human_packet_count"], 3)
        self.assertEqual(payload["qualified_human_review_count"], 0)
        self.assertEqual(payload["candidate_win_count"], 0)
        mem0 = next(row for row in payload["rows"] if row["reference_product"] == "Mem0")
        self.assertTrue(mem0["authorized_named_product_baseline_present"])
        self.assertTrue(mem0["source_hidden_five_human_packet_present"])
        self.assertFalse(mem0["candidate_won"])


if __name__ == "__main__":
    unittest.main()
