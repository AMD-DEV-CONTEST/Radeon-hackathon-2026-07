from __future__ import annotations

import json
import unittest
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]


class GTM40AssetCarouselChallengerTests(unittest.TestCase):
    def test_carousel_has_eight_exact_4_by_5_slides_and_truth_boundary(self) -> None:
        output = ROOT / "artifacts/gtm-last-mile-pk-v1/carousel-challenger-v1-40-asset-interview"
        receipt = json.loads((output / "carousel-receipt.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt["format"], {"aspect_ratio": "4:5", "height": 2700, "slide_count": 8, "width": 2160})
        self.assertEqual(len(receipt["slides"]), 8)
        self.assertFalse(receipt["human_preference_observed"])
        self.assertEqual(receipt["completed_named_product_pk_count"], 0)
        self.assertEqual(receipt["candidate_win_count"], 0)
        self.assertFalse(receipt["external_publish_executed"])
        for row in receipt["slides"]:
            path = ROOT / row["path"]
            self.assertTrue(path.is_file())
            with Image.open(path) as image:
                self.assertEqual(image.size, (2160, 2700))
        self.assertTrue((ROOT / receipt["pdf"]["path"]).is_file())
        self.assertTrue((ROOT / receipt["contact_sheet"]["path"]).is_file())


if __name__ == "__main__":
    unittest.main()
