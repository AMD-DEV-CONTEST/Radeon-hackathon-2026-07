from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts/gtm-last-mile-pk-v1/gtm-last-mile-copy-ab-v1"


class GTMLastMileCopyABV1Tests(unittest.TestCase):
    def test_packet_is_source_hidden_counterbalanced_and_empty(self) -> None:
        public_path = OUTPUT / "public/packet.json"
        private_path = OUTPUT / "private/mapping.json"
        public = json.loads(public_path.read_text(encoding="utf-8"))
        private = json.loads(private_path.read_text(encoding="utf-8"))
        receipt = json.loads((OUTPUT / "packet-receipt.json").read_text(encoding="utf-8"))
        self.assertEqual(public["reviewer_count"], 5)
        self.assertEqual(public["submitted_review_count"], 0)
        self.assertFalse(public["source_roles_exposed"])
        self.assertFalse(public["model_judge_can_promote"])
        self.assertFalse(public["automatic_promotion_enabled"])
        self.assertFalse(public["market_effect_observed"])
        self.assertEqual(private["candidate_b_left_count"], 3)
        self.assertEqual(len(private["task_side_mapping"]), 5)
        self.assertEqual(receipt["reviewer_kit_count"], 5)
        self.assertEqual(hashlib.sha256(public_path.read_bytes()).hexdigest(), receipt["public_packet_sha256"])
        self.assertEqual(hashlib.sha256(private_path.read_bytes()).hexdigest(), receipt["private_mapping_sha256"])
        rendered_public = public_path.read_text(encoding="utf-8")
        self.assertNotIn("candidate_a", rendered_public)
        self.assertNotIn("candidate_b", rendered_public)
        for task in public["review_tasks"]:
            self.assertEqual(set(task["left_assets"]), {"linkedin", "tiktok", "instagram", "null_result_receipt"})
            self.assertEqual(set(task["right_assets"]), set(task["left_assets"]))
            self.assertTrue((OUTPUT / "public" / f"reviewer-{task['reviewer_slot']:02d}.html").is_file())
            self.assertTrue((OUTPUT / "offline-kits" / f"reviewer-{task['reviewer_slot']:02d}.zip").is_file())


if __name__ == "__main__":
    unittest.main()
