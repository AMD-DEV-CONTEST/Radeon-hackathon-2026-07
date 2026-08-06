from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts/gtm-last-mile-pk-v1/delete-one-line-video-v2"


class DeleteOneLineVideoV2Tests(unittest.TestCase):
    def test_encoded_video_and_audit_frames_are_bound(self) -> None:
        receipt = json.loads((OUTPUT / "receipt.json").read_text(encoding="utf-8"))
        unsigned = dict(receipt)
        supplied = unsigned.pop("content_sha256")
        canonical = json.dumps(
            unsigned,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
        self.assertEqual(hashlib.sha256(canonical).hexdigest(), supplied)
        self.assertEqual(receipt["video"]["width"], 2160)
        self.assertEqual(receipt["video"]["height"], 3840)
        self.assertGreaterEqual(receipt["video"]["duration_seconds"], 14.8)
        self.assertLessEqual(receipt["video"]["duration_seconds"], 15.1)
        self.assertEqual(len(receipt["encoded_audit_frames"]), 3)
        self.assertEqual(receipt["missing_witness_classes_visible"], 4)
        self.assertTrue(receipt["visible_browser_mechanism_present"])
        self.assertTrue(receipt["visible_deletion_present"])
        self.assertTrue(receipt["bounded_replacement_present"])
        self.assertFalse(receipt["first_three_second_human_hook_reviewed"])
        self.assertFalse(receipt["human_preference_observed"])
        self.assertFalse(receipt["external_publish_executed"])
        self.assertFalse(receipt["production_effect_observed"])
        for row in [receipt["video"], *receipt["scene_files"], *receipt["encoded_audit_frames"]]:
            path = ROOT / row["path"]
            self.assertTrue(path.is_file(), row["path"])
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), row["sha256"])
        for row in receipt["encoded_audit_frames"]:
            with Image.open(ROOT / row["path"]) as image:
                self.assertEqual(image.size, (2160, 3840))


if __name__ == "__main__":
    unittest.main()
