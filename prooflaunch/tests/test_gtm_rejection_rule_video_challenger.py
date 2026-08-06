from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RECEIPT = ROOT / "artifacts/gtm-last-mile-pk-v1/video-challenger-v6-rejection-rule/video-challenger-receipt.json"


class RejectionRuleVideoChallengerTests(unittest.TestCase):
    def test_video_is_three_beat_4k_and_truthful(self) -> None:
        payload = json.loads(RECEIPT.read_text(encoding="utf-8"))
        self.assertEqual(payload["creative_concept"], "The Rejection Rule Is the Product")
        self.assertEqual(len(payload["story_beats"]), 3)
        self.assertEqual((payload["video"]["width"], payload["video"]["height"]), (3840, 2160))
        self.assertGreaterEqual(payload["video"]["duration_seconds"], 14)
        self.assertLessEqual(payload["video"]["duration_seconds"], 16)
        self.assertTrue(payload["mechanical_three_beat_gate_passed"])
        self.assertFalse(payload["human_preference_observed"])
        self.assertEqual(payload["completed_named_product_pk_count"], 0)
        self.assertEqual(payload["candidate_win_count"], 0)
        self.assertGreater(min(payload["adjacent_beat_rms_differences"]), 20)


if __name__ == "__main__":
    unittest.main()
