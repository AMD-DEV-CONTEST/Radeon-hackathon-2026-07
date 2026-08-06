from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKET = ROOT / "artifacts/gtm-last-mile-pk-v1/claim-trial-creative-ab-v1"


class ClaimTrialCreativeABTests(unittest.TestCase):
    def test_packet_is_five_human_source_hidden_and_empty(self) -> None:
        public = json.loads((PACKET / "public/packet.json").read_text(encoding="utf-8"))
        private = json.loads((PACKET / "private/mapping.json").read_text(encoding="utf-8"))
        self.assertEqual(public["reviewer_count"], 5)
        self.assertEqual(public["submitted_review_count"], 0)
        self.assertFalse(public["source_roles_exposed"])
        self.assertFalse(public["automatic_promotion_enabled"])
        self.assertIn(private["v2_left_count"], {2, 3})
        self.assertEqual(len(private["task_side_mapping"]), 5)
        for task in public["review_tasks"]:
            self.assertEqual(task["left_asset"]["media_family"], "image")
            self.assertEqual(task["right_asset"]["media_family"], "image")
            self.assertNotEqual(task["left_asset"]["sha256"], task["right_asset"]["sha256"])

    def test_public_pages_do_not_expose_versions(self) -> None:
        for path in sorted((PACKET / "public").glob("reviewer-*.html")):
            page = path.read_text(encoding="utf-8").lower()
            self.assertNotIn("claim-trial-v1", page)
            self.assertNotIn("claim-trial-v2", page)
            self.assertEqual(page.count("<img "), 2)
            self.assertIn("prooflaunchcreativeabhumanreviewv1", page.lower())


if __name__ == "__main__":
    unittest.main()
