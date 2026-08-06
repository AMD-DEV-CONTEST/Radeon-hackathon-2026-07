from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/export_gtm_unified_offline_review_kit.py"


class GTMUnifiedOfflineReviewKitTests(unittest.TestCase):
    def test_exports_portable_five_reviewer_eighty_task_kit_without_deblinding(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            output = Path(temporary) / "kit"
            subprocess.run(
                ["python3", str(SCRIPT), "--output-dir", str(output)],
                check=True,
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
            unsigned = dict(manifest)
            supplied = unsigned.pop("content_sha256")
            expected = hashlib.sha256(
                json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
            ).hexdigest()
            self.assertEqual(supplied, expected)
            self.assertEqual(manifest["reviewer_page_count"], 5)
            self.assertEqual(manifest["pair_count_per_reviewer"], 16)
            self.assertEqual(manifest["expected_human_review_count"], 80)
            self.assertEqual(manifest["submitted_human_review_count"], 0)
            self.assertEqual(manifest["schema"], "ProofLaunchGTMUnifiedOfflineReviewKitV2")
            self.assertEqual(len(manifest["generic_pairs"]), 15)
            self.assertEqual(len(manifest["visual_tasks"]), 5)
            self.assertEqual(len({row["lane_id"] for row in manifest["generic_pairs"]} | {"visual-system"}), 14)
            self.assertFalse(manifest["candidate_identity_exposed"])
            self.assertFalse(manifest["private_mapping_included"])
            self.assertFalse(manifest["network_submission_enabled"])
            self.assertFalse(manifest["automatic_publish_enabled"])
            for slot in range(1, 6):
                html = (output / f"reviewer-{slot:02d}.html").read_text(encoding="utf-8")
                self.assertIn("16 hash-bound comparison pairs", html)
                self.assertIn("download results", html)
                self.assertIn("pair_sha256", html)
                self.assertIn("Blocking production defect", html)
                self.assertIn("ProofLaunchGTMGenericHumanBlindReviewV2", html)
                self.assertIn("ProofLaunchGTMVisualHumanBlindReviewV2", html)
                for forbidden in (
                    "video-film-candidate",
                    "video-film-baseline",
                    "voice-restraint-a",
                    "voice-documentary-b",
                    "voice-inquisitive-c",
                    "campaign-pack-v6",
                    "Qwen3-TTS",
                ):
                    self.assertNotIn(forbidden, html)
            receipt = json.loads((output / "export-receipt.json").read_text(encoding="utf-8"))
            archive = ROOT / receipt["archive"]["path"]
            self.assertEqual(hashlib.sha256(archive.read_bytes()).hexdigest(), receipt["archive"]["sha256"])
            self.assertGreater(receipt["archive"]["bytes"], 1_000_000)
            self.assertEqual(receipt["network_calls"], 0)
            self.assertEqual(receipt["automatic_external_actions"], 0)


if __name__ == "__main__":
    unittest.main()
