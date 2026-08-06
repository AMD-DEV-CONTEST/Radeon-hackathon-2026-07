from __future__ import annotations

import hashlib
import importlib.util
import json
import unittest
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/render_gtm_three_beat_video_challenger.py"
RECEIPT = ROOT / "artifacts/gtm-last-mile-pk-v1/video-challenger-v5/video-challenger-receipt.json"
SPEC = importlib.util.spec_from_file_location("render_gtm_three_beat_video_challenger", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class GTMThreeBeatVideoChallengerTests(unittest.TestCase):
    def test_sealed_real_challenger_has_distinct_4k_beats_without_quality_overclaim(self) -> None:
        payload = json.loads(RECEIPT.read_text(encoding="utf-8"))
        unsigned = dict(payload)
        supplied = unsigned.pop("content_sha256")
        expected = hashlib.sha256(
            json.dumps(
                unsigned,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
        self.assertEqual(supplied, expected)
        self.assertEqual(len(payload["story_beats"]), 3)
        self.assertTrue(payload["mechanical_three_beat_gate_passed"])
        self.assertTrue(all(value >= 20.0 for value in payload["adjacent_beat_rms_differences"]))
        self.assertEqual(payload["video"]["width"], 3840)
        self.assertEqual(payload["video"]["height"], 2160)
        self.assertAlmostEqual(payload["video"]["duration_seconds"], 14.72, delta=0.08)
        video = ROOT / payload["video"]["path"]
        self.assertEqual(hashlib.sha256(video.read_bytes()).hexdigest(), payload["video"]["sha256"])
        for row in payload["scene_assets"]:
            with Image.open(ROOT / row["path"]) as image:
                self.assertEqual(image.size, (3840, 2160))
        self.assertEqual(len(payload["source_assets"]), 5)
        for row in payload["source_assets"]:
            source = ROOT / row["path"]
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), row["sha256"])
        self.assertFalse(payload["first_three_second_human_hook_reviewed"])
        self.assertFalse(payload["human_preference_observed"])
        self.assertFalse(payload["four_a_quality_proven"])
        self.assertFalse(payload["automatic_publish_enabled"])

    def test_three_scenes_are_not_duplicate_assets(self) -> None:
        payload = json.loads(RECEIPT.read_text(encoding="utf-8"))
        hashes = {row["sha256"] for row in payload["scene_assets"]}
        self.assertEqual(len(hashes), 3)
        self.assertIn("Output is cheap", payload["creative_concept"])


if __name__ == "__main__":
    unittest.main()
