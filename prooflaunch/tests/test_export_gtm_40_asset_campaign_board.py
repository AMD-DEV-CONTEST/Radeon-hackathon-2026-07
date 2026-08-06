from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class GTM40AssetCampaignBoardTests(unittest.TestCase):
    def test_board_is_reviewable_and_keeps_pk_truth_boundary(self) -> None:
        output = ROOT / "artifacts/gtm-last-mile-pk-v1/40-asset-campaign-board-v1"
        receipt = json.loads((output / "board-receipt.json").read_text(encoding="utf-8"))
        page = (output / "index.html").read_text(encoding="utf-8")

        self.assertEqual(receipt["surface_count"], 13)
        self.assertEqual(receipt["b2c_surface_count"], 13)
        self.assertEqual(receipt["total_platform_candidate_count"], 26)
        self.assertEqual(receipt["mechanically_admitted_category_count"], 13)
        self.assertEqual(receipt["reference_product_row_count"], 130)
        self.assertEqual(receipt["completed_named_product_pk_count"], 0)
        self.assertEqual(receipt["candidate_win_count"], 0)
        self.assertFalse(receipt["human_review_completed"])
        self.assertFalse(receipt["production_effect_observed"])
        self.assertEqual(receipt["external_action_count"], 0)
        self.assertIn("The 40-Asset Interview", page)
        self.assertIn("0/130", page)
        self.assertIn("does not mean 13 categories aligned", page)
        self.assertIn("The Anti-Streak Memory Ritual", page)
        self.assertEqual(page.count('class="platform-card"'), 26)
        self.assertEqual(page.count("<audio controls"), 3)
        self.assertEqual(page.count("<video"), 2)


if __name__ == "__main__":
    unittest.main()
