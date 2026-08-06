from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/export_gtm_platform_craft_review_kit.py"


class PlatformCraftReviewKitExportTests(unittest.TestCase):
    def test_exports_five_reviewer_sixty_five_task_public_only_zip(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            output = Path(temporary) / "kit"
            subprocess.run(
                [sys.executable, str(SCRIPT), "--output-dir", str(output)],
                check=True,
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            public = json.loads(
                (output / "public/platform-craft-review-public.json").read_text(
                    encoding="utf-8"
                )
            )
            private = json.loads(
                (output / "private/platform-craft-review-private.json").read_text(
                    encoding="utf-8"
                )
            )
            manifest = json.loads(
                (output / "public/manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(public["artifact_count"], 13)
            self.assertEqual(public["review_task_count"], 65)
            self.assertEqual(public["submitted_human_review_count"], 0)
            self.assertFalse(public["provider_identity_exposed"])
            self.assertFalse(public["model_identity_exposed"])
            self.assertFalse(public["named_product_comparison_executed"])
            self.assertEqual(private["mapping_count"], 13)
            self.assertIn("source_model", private)
            self.assertEqual(manifest["reviewer_page_count"], 5)
            self.assertEqual(manifest["artifact_count_per_reviewer"], 13)
            self.assertEqual(manifest["expected_human_review_count"], 65)
            self.assertEqual(manifest["submitted_human_review_count"], 0)
            self.assertFalse(manifest["private_mapping_included_in_public_package"])
            self.assertFalse(manifest["network_submission_enabled"])
            self.assertFalse(manifest["automatic_publish_enabled"])
            source_model_id = str(private["source_model"]["model_id"])
            public_text = json.dumps(public, ensure_ascii=False)
            self.assertNotIn(source_model_id, public_text)
            for slot in range(1, 6):
                html = (output / f"public/reviewer-{slot:02d}.html").read_text(
                    encoding="utf-8"
                )
                self.assertIn("13 hash-bound artifacts", html)
                self.assertIn("download JSONL", html)
                self.assertIn("ProofLaunchPlatformCraftHumanReviewV1", html)
                self.assertNotIn(source_model_id, html)
            receipt = json.loads(
                (output / "export-receipt.json").read_text(encoding="utf-8")
            )
            archive = ROOT / receipt["archive"]["path"]
            self.assertEqual(
                hashlib.sha256(archive.read_bytes()).hexdigest(),
                receipt["archive"]["sha256"],
            )
            with zipfile.ZipFile(archive) as bundle:
                names = bundle.namelist()
                self.assertIn("manifest.json", names)
                self.assertIn("reviewer-01.html", names)
                self.assertFalse(any("private" in name or "mapping" in name for name in names))
                self.assertNotIn(source_model_id, "\n".join(
                    bundle.read(name).decode("utf-8", errors="ignore") for name in names
                ))
            self.assertEqual(receipt["network_calls"], 0)
            self.assertEqual(receipt["automatic_external_actions"], 0)


if __name__ == "__main__":
    unittest.main()

