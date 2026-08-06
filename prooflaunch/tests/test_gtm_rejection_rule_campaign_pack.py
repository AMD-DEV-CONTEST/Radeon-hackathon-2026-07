from __future__ import annotations

import json
import unittest
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
DELIVERY = ROOT / "evidence/v10/local-campaign-pack-v1/delivery-v9-rejection-rule"
LEDGER = ROOT / "evidence/v10/gtm-concrete-product-effect-pk-ledger-v1.json"


class RejectionRuleCampaignPackTests(unittest.TestCase):
    def test_three_format_candidate_is_bound_without_false_effect_claim(self) -> None:
        manifest = json.loads((DELIVERY / "campaign-pack-manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["campaign"]["campaign_id"], "prooflaunch-rejection-rule-v9")
        self.assertIn("brief it should refuse", manifest["campaign"]["headline"])
        self.assertTrue(manifest["quality_gates"]["hero_true_4k_geometry"])
        self.assertTrue(manifest["quality_gates"]["social_geometry"])
        self.assertFalse(manifest["quality_gates"]["named_human_blind_review_passed"])
        self.assertFalse(manifest["quality_gates"]["product_admission_passed"])
        expected = {
            "prooflaunch-hero-4k.png": (3840, 2160),
            "prooflaunch-social-1080x1350.png": (1080, 1350),
            "prooflaunch-landing-1920x1080.png": (1920, 1080),
        }
        for name, dimensions in expected.items():
            with Image.open(DELIVERY / name) as image:
                self.assertEqual(image.size, dimensions)

    def test_named_pk_ledger_uses_new_candidate_and_keeps_zero_wins(self) -> None:
        ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
        rows = [row for row in ledger["product_pk_rows"] if row["category_id"] == "image_generation_editing"]
        self.assertEqual(len(rows), 10)
        paths = [item["path"] for item in rows[0]["candidate_artifacts"]]
        self.assertTrue(all("delivery-v9-rejection-rule" in path for path in paths))
        self.assertTrue(all(row["comparison_status"] == "not_completed" for row in rows))
        self.assertTrue(all(row["effect_alignment_achieved"] is False for row in rows))


if __name__ == "__main__":
    unittest.main()
