from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts/gtm-last-mile-pk-v1/text-campaign-ab-v2"


class TextCampaignABV2Tests(unittest.TestCase):
    def test_packet_is_five_human_source_hidden_and_fail_closed(self) -> None:
        public_path = OUTPUT / "public/packet.json"
        private_path = OUTPUT / "private/mapping.json"
        receipt = json.loads((OUTPUT / "packet-receipt.json").read_text(encoding="utf-8"))
        public = json.loads(public_path.read_text(encoding="utf-8"))
        private = json.loads(private_path.read_text(encoding="utf-8"))
        self.assertEqual(public["reviewer_count"], 5)
        self.assertEqual(public["expected_review_count"], 5)
        self.assertEqual(public["submitted_review_count"], 0)
        self.assertFalse(public["source_roles_exposed"])
        self.assertFalse(public["model_judge_can_promote"])
        self.assertFalse(public["automatic_promotion_enabled"])
        self.assertFalse(public["market_effect_observed"])
        self.assertEqual(len(private["task_side_mapping"]), 5)
        self.assertEqual(private["v2_left_count"], 3)
        self.assertEqual(receipt["reviewer_kit_count"], 5)
        self.assertEqual(receipt["submitted_review_count"], 0)
        self.assertEqual(hashlib.sha256(public_path.read_bytes()).hexdigest(), receipt["public_packet_sha256"])
        self.assertEqual(hashlib.sha256(private_path.read_bytes()).hexdigest(), receipt["private_mapping_sha256"])
        for task in public["review_tasks"]:
            self.assertEqual(set(task["left_assets"]), {"linkedin", "partner_community", "landing_hero", "lifecycle_email"})
            self.assertEqual(set(task["right_assets"]), set(task["left_assets"]))
            self.assertNotIn(task["review_task_id"], json.dumps(public.get("task_side_mapping", {})))


if __name__ == "__main__":
    unittest.main()
