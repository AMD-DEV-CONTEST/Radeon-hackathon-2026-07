from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from scripts.export_gtm_codex_lighthouse_human_review_kit import export


class CodexLighthouseHumanReviewKitTests(unittest.TestCase):
    def test_export_is_source_hidden_hash_bound_and_truthful(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "kit"
            receipt = export(output)
            manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
            mapping = json.loads((output / "private/blind-case-mapping.json").read_text(encoding="utf-8"))

            self.assertEqual(manifest["candidate_count"], 8)
            self.assertEqual(manifest["reviewer_count"], 5)
            self.assertEqual(manifest["expected_human_review_count"], 40)
            self.assertEqual(manifest["submitted_human_review_count"], 0)
            self.assertEqual(manifest["qualified_human_review_count"], 0)
            self.assertFalse(manifest["four_a_claim_eligible"])
            self.assertFalse(manifest["network_submission_enabled"])
            self.assertFalse(manifest["automatic_publish_enabled"])
            self.assertEqual(len(mapping["rows"]), 8)
            self.assertEqual(len({row["blind_case_id"] for row in mapping["rows"]}), 8)

            reviewer = (output / "public/reviewer-01.html").read_text(encoding="utf-8")
            self.assertEqual(reviewer.count('class="case"'), 8)
            self.assertNotIn("codex-lighthouse-", reviewer)
            self.assertNotIn("candidate_id", reviewer)
            self.assertIn("Nothing transmitted or promoted", reviewer)
            self.assertIn("Directly publishable", reviewer)

            self.assertEqual(receipt["expected_human_review_count"], 40)
            self.assertEqual(receipt["submitted_human_review_count"], 0)
            self.assertEqual(receipt["network_calls"], 0)
            with zipfile.ZipFile(output / "prooflaunch-codex-lighthouse-coordinator-kit-v1.zip") as bundle:
                coordinator_names = set(bundle.namelist())
            self.assertIn("manifest.json", coordinator_names)
            self.assertIn("public/reviewer-05.html", coordinator_names)
            self.assertIn("private/blind-case-mapping.json", coordinator_names)
            with zipfile.ZipFile(output / "prooflaunch-codex-lighthouse-reviewer-pages-v1.zip") as bundle:
                reviewer_names = set(bundle.namelist())
            self.assertIn("public/reviewer-05.html", reviewer_names)
            self.assertFalse(any(name.startswith("private/") for name in reviewer_names))
            self.assertFalse(receipt["reviewer_archive_contains_private_mapping"])


if __name__ == "__main__":
    unittest.main()
