from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts/gtm-last-mile-pk-v1/claim-trial-share-card-v2"


class ClaimTrialShareCardV2Tests(unittest.TestCase):
    def test_receipt_and_exact_media_contract(self) -> None:
        receipt = json.loads((OUTPUT / "receipt.json").read_text(encoding="utf-8"))
        unsigned = dict(receipt)
        supplied = unsigned.pop("content_sha256")
        canonical = json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        self.assertEqual(hashlib.sha256(canonical).hexdigest(), supplied)
        self.assertEqual(receipt["format"], "social_feed_4x5")
        self.assertEqual(receipt["verified_candidate_count"], 26)
        self.assertEqual(receipt["selected_campaign_nucleus_count"], 1)
        self.assertFalse(receipt["human_preference_observed"])
        self.assertFalse(receipt["named_product_win_observed"])
        with Image.open(OUTPUT / "prooflaunch-performance-review-1080x1350.png") as image:
            self.assertEqual(image.size, (1080, 1350))

    def test_typography_is_deterministic_and_scene_has_no_text_role(self) -> None:
        html = (OUTPUT / "card.html").read_text(encoding="utf-8")
        self.assertIn("We put our own AI", html)
        self.assertIn("Grade the <i>work.</i>", html)
        self.assertIn("NO PREFERENCE · VIRALITY · CONVERSION · REVENUE EVIDENCE YET", html)
        self.assertIn("performance-review-scene.png", html)

    def test_bound_files_match_receipt(self) -> None:
        receipt = json.loads((OUTPUT / "receipt.json").read_text(encoding="utf-8"))
        for row in receipt["files"]:
            path = ROOT / row["path"]
            self.assertTrue(path.is_file())
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), row["sha256"])


if __name__ == "__main__":
    unittest.main()
