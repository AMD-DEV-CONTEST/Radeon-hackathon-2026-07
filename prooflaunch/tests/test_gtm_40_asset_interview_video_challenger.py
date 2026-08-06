from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RECEIPT = ROOT / "artifacts/gtm-last-mile-pk-v1/video-challenger-v8-40-asset-interview/video-challenger-receipt.json"


class FortyAssetInterviewVideoTests(unittest.TestCase):
    def test_dual_aspect_4k_challenger_is_truthful_and_temporally_distinct(self) -> None:
        payload = json.loads(RECEIPT.read_text(encoding="utf-8"))
        self.assertEqual(payload["creative_concept"], "The 40-Asset Interview")
        self.assertEqual(len(payload["variants"]), 2)
        self.assertEqual({(row["width"], row["height"]) for row in payload["variants"]}, {(3840, 2160), (2160, 3840)})
        self.assertTrue(payload["mechanical_dual_aspect_three_beat_gate_passed"])
        for row in payload["variants"]:
            self.assertGreaterEqual(row["duration_seconds"], 14)
            self.assertLessEqual(row["duration_seconds"], 16)
            self.assertGreater(min(row["adjacent_beat_rms_differences"]), 20)
        self.assertEqual(payload["new_image_generation_call_count"], 0)
        self.assertFalse(payload["human_preference_observed"])
        self.assertEqual(payload["completed_named_product_pk_count"], 0)
        self.assertEqual(payload["candidate_win_count"], 0)
        self.assertFalse(payload["four_a_quality_proven"])


if __name__ == "__main__":
    unittest.main()
