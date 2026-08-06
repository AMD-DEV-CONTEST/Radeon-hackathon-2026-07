from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/compile_gtm_multimodal_review_packets.py"


class GTMMultimodalReviewPacketTests(unittest.TestCase):
    def test_compiles_identity_hidden_fourteen_lane_review_inventory(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            output = Path(temporary) / "packet"
            subprocess.run(
                [
                    "python3",
                    str(SCRIPT),
                    "--output-dir",
                    str(output),
                    "--audio-key",
                    "audio-test-private-key-0123456789",
                    "--video-key",
                    "video-test-private-key-0123456789",
                ],
                check=True,
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            unified = json.loads((output / "unified-last-mile-review.json").read_text(encoding="utf-8"))
            unsigned = dict(unified)
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
            self.assertEqual(unified["lane_count"], 14)
            self.assertEqual(unified["comparison_pair_count"], 16)
            self.assertEqual(unified["expected_human_review_count"], 80)
            self.assertEqual(unified["submitted_human_review_count"], 0)
            self.assertFalse(unified["top_product_baselines_present"])
            self.assertFalse(unified["four_a_quality_proven"])
            self.assertFalse(unified["automatic_publish_enabled"])

            audio_manifest = json.loads((output / "audio/manifest.json").read_text(encoding="utf-8"))
            video_manifest = json.loads((output / "video/manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(audio_manifest["pair_count"], 3)
            self.assertEqual(video_manifest["pair_count"], 1)
            self.assertTrue((output / "audio/REVIEW_INSTRUCTIONS.md").is_file())
            self.assertTrue((output / "video/REVIEW_INSTRUCTIONS.md").is_file())

            public_audio = (output / "audio/public/blind-pairs.jsonl").read_text(encoding="utf-8")
            for identity in (
                "voice-restraint-a",
                "voice-documentary-b",
                "voice-inquisitive-c",
                "prooflaunch-audio-master-48k-stereo-24bit.wav",
            ):
                self.assertNotIn(identity, public_audio)

            public_video = (output / "video/public/blind-pairs.jsonl").read_text(encoding="utf-8")
            for identity in (
                "prooflaunch-three-beat-challenger-4k.mp4",
                "prooflaunch-campaign-film-4k.mp4",
                "video-film-candidate",
                "video-film-baseline",
            ):
                self.assertNotIn(identity, public_video)
            video_scope = json.loads((output / "video/scope.json").read_text(encoding="utf-8"))
            self.assertTrue(video_scope["mechanical_three_beat_gate_passed"])
            self.assertFalse(video_scope["human_preference_observed"])


if __name__ == "__main__":
    unittest.main()
