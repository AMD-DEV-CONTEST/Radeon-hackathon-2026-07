import json
import os
import tempfile
import unittest

from fencing_analysis.config import DEFAULT_CONFIG
from fencing_analysis.evidence.clips import extract_evidence
from webui.pipeline import evidence_playback_choices, render_evidence_windows


class EvidenceWindowTest(unittest.TestCase):
    def test_manifest_uses_time_windows_without_mp4_clips(self):
        events = {
            "video": {"name": "bout.mp4", "duration_sec": 20},
            "footwork": {"lunges": [{"fencer": "left", "start_sec": 4,
                                         "time_sec": 5, "confidence": 0.9}]},
            "actions": [], "reactions": [],
        }
        with tempfile.TemporaryDirectory() as output_dir:
            manifest_path, manifest = extract_evidence(
                output_dir, events, DEFAULT_CONFIG, include_keyframes=False,
            )
            self.assertTrue(os.path.exists(manifest_path))
            self.assertEqual(len(manifest), 1)
            event = manifest[0]
            self.assertIsNone(event["clip"])
            self.assertEqual(event["playback_start_sec"], 4)
            self.assertEqual(event["playback_end_sec"], 6)
            self.assertFalse(any(name.endswith(".mp4") for name in os.listdir(os.path.join(output_dir, "evidence"))))

            value = evidence_playback_choices(manifest)[0][1]
            self.assertEqual(json.loads(value)["start"], 4)
            self.assertIn("00:04.00", render_evidence_windows(manifest))


if __name__ == "__main__":
    unittest.main()
