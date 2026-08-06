from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "artifacts/gtm-last-mile-pk-v1/claim-trial-creative-v2"


class ClaimTrialCreativeV2Tests(unittest.TestCase):
    def test_feed_asset_is_exact_and_truth_bounded(self) -> None:
        receipt = json.loads((ARTIFACT / "receipt.json").read_text(encoding="utf-8"))
        unsigned = dict(receipt)
        supplied = unsigned.pop("content_sha256")
        canonical = json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        self.assertEqual(supplied, hashlib.sha256(canonical).hexdigest())
        self.assertFalse(receipt["human_preference_observed"])
        self.assertFalse(receipt["production_effect_observed"])
        self.assertFalse(receipt["external_publish_executed"])
        self.assertTrue(receipt["render_contract"]["exact_1080x1350"])
        png = ROOT / receipt["card_png"]["path"]
        with Image.open(png) as image:
            self.assertEqual(image.size, (1080, 1350))

    def test_copy_contains_conflict_evidence_and_response_trigger(self) -> None:
        page = (ARTIFACT / "claim-trial-v2-1080x1350.html").read_text(encoding="utf-8")
        for phrase in (
            "OUR AI",
            "PROMISED",
            "VIRAL.",
            "SO WE MADE IT TESTIFY.",
            "NO WITNESS",
            "independent wins entered",
            "organic breakouts observed",
            "conversions attributed",
            "DROP THE HOMEPAGE LINE YOU TRUST LEAST",
        ):
            self.assertIn(phrase, page)
        launch = json.loads((ARTIFACT / "launch-pack-v2.json").read_text(encoding="utf-8"))
        self.assertIn("reply_protocol", launch["primary_post"])
        self.assertIn("learning_signal", launch["organic_loop"])


if __name__ == "__main__":
    unittest.main()
