from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "artifacts/gtm-last-mile-pk-v1"


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def assert_sealed(test: unittest.TestCase, payload: dict) -> None:
    unsigned = dict(payload)
    supplied = unsigned.pop("content_sha256")
    canonical = json.dumps(
        unsigned,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()
    test.assertEqual(hashlib.sha256(canonical).hexdigest(), supplied)


class KeepUnpostableProductionV1Tests(unittest.TestCase):
    def test_release_jury_is_five_empty_independent_slots(self) -> None:
        root = BASE / "keep-unpostable-release-jury-v1"
        receipt = json.loads((root / "receipt.json").read_text(encoding="utf-8"))
        assert_sealed(self, receipt)
        self.assertEqual(receipt["reviewer_count"], 5)
        self.assertEqual(receipt["expected_human_review_count"], 5)
        self.assertEqual(receipt["submitted_human_review_count"], 0)
        self.assertEqual(receipt["quality_axis_count"], 10)
        self.assertFalse(receipt["named_product_baseline_present"])
        self.assertFalse(receipt["human_review_completed"])
        self.assertFalse(receipt["release_approved"])
        for row in receipt["task_files"]:
            path = root / row["path"]
            self.assertEqual(digest(path), row["sha256"])
            source = path.read_text(encoding="utf-8")
            self.assertIn("DOWNLOAD REVIEW JSON", source)
            self.assertIn("Nothing transmitted.", source)

    def test_carousel_is_five_bound_images_without_effect_claim(self) -> None:
        root = BASE / "keep-unpostable-carousel-v1"
        receipt = json.loads((root / "receipt.json").read_text(encoding="utf-8"))
        assert_sealed(self, receipt)
        self.assertEqual(receipt["slide_count"], 5)
        self.assertEqual(receipt["first_frame_hook"], "DO NOT POST THIS.")
        for row in receipt["files"]:
            path = root / row["png"]["path"]
            self.assertEqual((row["png"]["width"], row["png"]["height"]), (1080, 1350))
            self.assertEqual(digest(path), row["png"]["sha256"])
        self.assertTrue(receipt["human_release_required"])
        self.assertFalse(receipt["external_publish_executed"])
        self.assertFalse(receipt["human_preference_observed"])
        self.assertFalse(receipt["organic_breakout_observed"])
        self.assertFalse(receipt["conversion_observed"])

    def test_audio_has_three_unique_local_candidates_pending_human_listening(self) -> None:
        root = BASE / "keep-unpostable-audio-v1"
        receipt = json.loads((root / "audio-candidate-receipt.json").read_text(encoding="utf-8"))
        assert_sealed(self, receipt)
        self.assertEqual(receipt["candidate_count"], 3)
        hashes = set()
        for row in receipt["candidates"]:
            path = ROOT / row["master"]["project_relative_path"]
            self.assertEqual(digest(path), row["master"]["sha256"])
            self.assertEqual(row["master"]["sample_rate_hz"], 48000)
            self.assertEqual(row["master"]["channels"], 2)
            self.assertEqual(row["master"]["sample_width_bits"], 24)
            self.assertLessEqual(abs(row["master"]["duration_seconds"] - 15.0), 0.10)
            self.assertEqual(row["human_listening_review_status"], "pending")
            hashes.add(row["master"]["sha256"])
        self.assertEqual(len(hashes), 3)
        self.assertFalse(receipt["human_preference_observed"])

    def test_video_is_bound_4k_fifteen_second_challenger(self) -> None:
        receipt = json.loads(
            (BASE / "keep-unpostable-video-v1/receipt.json").read_text(encoding="utf-8")
        )
        assert_sealed(self, receipt)
        video = ROOT / receipt["video"]["path"]
        self.assertEqual(digest(video), receipt["video"]["sha256"])
        self.assertEqual((receipt["video"]["width"], receipt["video"]["height"]), (2160, 3840))
        self.assertGreaterEqual(receipt["video"]["duration_seconds"], 14.8)
        self.assertLessEqual(receipt["video"]["duration_seconds"], 15.1)
        self.assertEqual(len(receipt["story_beats"]), 4)
        self.assertEqual(len(receipt["audit_frames"]), 4)
        for row in receipt["audit_frames"]:
            self.assertEqual(digest(ROOT / row["path"]), row["sha256"])
        self.assertTrue(receipt["human_release_required"])
        self.assertFalse(receipt["external_publish_executed"])
        self.assertFalse(receipt["human_preference_observed"])
        self.assertFalse(receipt["organic_breakout_observed"])
        self.assertFalse(receipt["conversion_observed"])


if __name__ == "__main__":
    unittest.main()
