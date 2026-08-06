from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts/gtm-last-mile-pk-v1/delete-one-line-experience-v1"


class DeleteOneLineExperienceTests(unittest.TestCase):
    def test_experience_is_local_actionable_and_truth_bounded(self) -> None:
        html = (OUTPUT / "index.html").read_text(encoding="utf-8")
        script = (OUTPUT / "delete-one-line.js").read_text(encoding="utf-8")
        receipt = json.loads((OUTPUT / "receipt.json").read_text(encoding="utf-8"))

        self.assertIn("DELETE<br><em>ONE LINE.</em>", html)
        self.assertIn('id="trial"', html)
        self.assertIn('id="output"', html)
        self.assertIn("One act. Three native jobs.", html)
        self.assertIn("records no input", html)
        self.assertNotIn("fetch(", script)
        self.assertNotIn("localStorage", script)
        self.assertNotIn("sessionStorage", script)
        self.assertIn("NO WITNESS", script)
        self.assertIn("HUMAN REVIEW REQUIRED", script)
        self.assertIn("demo') === 'no-witness'", script)
        self.assertIn("document.body.classList.add('demo-result')", script)
        self.assertIn("!document.body.classList.contains('demo-result')", script)
        self.assertIn("body.demo-result #trial", html)
        self.assertIn("Do not replace it with a softer unsupported synonym", script)
        self.assertEqual(receipt["surface_candidate_count"], 13)
        self.assertEqual(receipt["pre_human_quality_pass_count"], 13)
        self.assertEqual(receipt["network_requests_implemented"], 0)
        self.assertFalse(receipt["browser_persistence_implemented"])
        self.assertEqual(receipt["human_review_count"], 0)
        self.assertFalse(receipt["production_effect_observed"])
        for name, metadata in receipt["files"].items():
            path = OUTPUT / name
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), metadata["sha256"])
            self.assertEqual(path.stat().st_size, metadata["bytes"])


if __name__ == "__main__":
    unittest.main()
