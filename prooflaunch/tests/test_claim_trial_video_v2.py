from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts/gtm-last-mile-pk-v1/claim-trial-video-v2"


class ClaimTrialVideoV2Tests(unittest.TestCase):
    def test_receipt_is_sealed_and_video_is_real_4k(self) -> None:
        receipt = json.loads((OUTPUT / "receipt.json").read_text(encoding="utf-8"))
        unsigned = dict(receipt)
        supplied = unsigned.pop("content_sha256")
        canonical = json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        self.assertEqual(hashlib.sha256(canonical).hexdigest(), supplied)
        self.assertEqual(receipt["video"]["width"], 2160)
        self.assertEqual(receipt["video"]["height"], 3840)
        self.assertAlmostEqual(receipt["video"]["duration_seconds"], 15.0, delta=.1)
        self.assertEqual(receipt["scene_count"], 6)
        self.assertEqual(len(receipt["audit_frames"]), 6)
        self.assertGreater(min(receipt["adjacent_beat_rms_differences"]), 25)
        self.assertFalse(receipt["external_publish_executed"])
        self.assertFalse(receipt["production_effect_observed"])
        self.assertEqual(receipt["named_product_win_count"], 0)

    def test_bound_video_audio_scenes_and_audits_exist(self) -> None:
        receipt = json.loads((OUTPUT / "receipt.json").read_text(encoding="utf-8"))
        rows = [receipt["video"], receipt["audio"], receipt["captions"], *receipt["scenes"], *receipt["audit_frames"]]
        for row in rows:
            path = ROOT / row["path"]
            self.assertTrue(path.is_file(), row["path"])
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), row["sha256"])


if __name__ == "__main__":
    unittest.main()
