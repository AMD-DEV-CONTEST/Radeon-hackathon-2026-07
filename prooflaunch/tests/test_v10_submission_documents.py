from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SubmissionDocumentTests(unittest.TestCase):
    def test_english_readme_exposes_run_verify_truth_boundary_and_evidence_paths(self) -> None:
        text = (ROOT / "README.md").read_text(encoding="utf-8")
        required = (
            "ProofLaunch", "Quick start", "Radeon", "Evidence", "Truth boundary",
            "evidence/v10/local-test-report.json", "evidence/v10/todo-closure-report.json",
        )
        for phrase in required:
            self.assertIn(phrase.lower(), text.lower())
        letters = re.findall(r"[A-Za-z]", text)
        non_ascii = [character for character in text if ord(character) > 127]
        self.assertGreater(len(letters), len(non_ascii) * 20)

    def test_architecture_diagram_maps_primary_flow_interfaces_nfrs_and_truth_boundary(self) -> None:
        text = (ROOT / "docs/ARCHITECTURE_V10.md").read_text(encoding="utf-8")
        self.assertIn("```mermaid", text)
        for phrase in (
            "Brief + licensed evidence", "Campaign world state", "Bounded Supervisor",
            "Named human release gate", "Evidence Ledger bundle", "/v1/health",
            "Security", "Reliability", "Auditability", "Performance truth",
        ):
            self.assertIn(phrase, text)
        self.assertIn("currently unobserved", text)


if __name__ == "__main__":
    unittest.main()
