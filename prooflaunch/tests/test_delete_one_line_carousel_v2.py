from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts/gtm-last-mile-pk-v1/delete-one-line-carousel-v2"


class DeleteOneLineCarouselV2Tests(unittest.TestCase):
    def test_five_exact_4x5_slides_are_bound_without_effect_claims(self) -> None:
        receipt = json.loads((OUTPUT / "receipt.json").read_text(encoding="utf-8"))
        unsigned = dict(receipt)
        supplied = unsigned.pop("content_sha256")
        canonical = json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        self.assertEqual(hashlib.sha256(canonical).hexdigest(), supplied)
        self.assertEqual(receipt["slide_count"], 5)
        self.assertFalse(receipt["generation_model_used"])
        self.assertTrue(receipt["exact_visible_copy_preserved"])
        self.assertEqual(receipt["qualified_human_review_count"], 0)
        self.assertFalse(receipt["external_publish_executed"])
        self.assertFalse(receipt["production_effect_observed"])
        for row in receipt["files"]:
            for key in ("html", "png"):
                metadata = row[key]
                path = OUTPUT / metadata["path"]
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), metadata["sha256"])
            with Image.open(OUTPUT / row["png"]["path"]) as image:
                self.assertEqual(image.size, (1080, 1350))


if __name__ == "__main__":
    unittest.main()
