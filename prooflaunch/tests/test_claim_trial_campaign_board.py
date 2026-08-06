from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ClaimTrialCampaignBoardTests(unittest.TestCase):
    def test_board_binds_real_multimodal_assets_without_effect_claims(self) -> None:
        root = ROOT / "artifacts/gtm-last-mile-pk-v1/claim-trial-campaign-board-v1"
        receipt = json.loads((root / "receipt.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt["capability_lane_count"], 13)
        self.assertGreaterEqual(len(receipt["bound_assets"]), 6)
        self.assertTrue(all((ROOT / row["path"]).is_file() for row in receipt["bound_assets"]))
        self.assertEqual(receipt["external_publish_count"], 0)
        self.assertEqual(receipt["observed_effect_count"], 0)
        self.assertEqual(receipt["completed_named_product_pk_count"], 0)
        self.assertEqual(receipt["named_product_win_count"], 0)
        page = (root / "index.html").read_text(encoding="utf-8")
        self.assertIn("The product is the content", page)
        self.assertIn("prooflaunch-claim-trial-vertical-4k.mp4", page)
        self.assertEqual(page.count("<audio "), 3)
        self.assertIn("Named-product PK remains 0/130", page)


if __name__ == "__main__":
    unittest.main()
