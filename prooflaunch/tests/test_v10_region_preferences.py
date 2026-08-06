from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class RegionPreferenceTests(unittest.TestCase):
    def test_independent_recount_proves_exact_2k_mechanical_region_pairs(self) -> None:
        report = json.loads(
            (ROOT / "evidence/v10/region-preferences-2k-independent-audit.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(report["status"], "passed_independent_recount_not_training")
        self.assertEqual(report["pair_count"], 2_000)
        self.assertEqual(report["asset_count"], 500)
        self.assertEqual(report["train_pair_count"], 1_800)
        self.assertEqual(report["validation_pair_count"], 200)
        self.assertEqual(report["provider_asset_counts"], {
            "art-institute-chicago": 250,
            "cleveland-museum-art": 250,
        })
        self.assertEqual(report["duplicate_pair_count"], 0)
        self.assertEqual(report["nonpositive_margin_count"], 0)
        self.assertTrue(report["all_asset_hashes_and_region_scores_recomputed"])
        self.assertEqual(report["failure_count"], 0)
        self.assertFalse(report["teacher_model_used"])
        self.assertFalse(report["human_reviewed"])
        self.assertFalse(report["training_observed"])


if __name__ == "__main__":
    unittest.main()
