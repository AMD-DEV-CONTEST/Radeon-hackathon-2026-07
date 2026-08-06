from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from prooflaunch_remix.gtm_coverage_dashboard_v2 import (
    GTMCoverageDashboardError,
    build_coverage_dashboard,
    verify_coverage_dashboard,
)


ROOT = Path(__file__).resolve().parents[1]


class GTMCoverageDashboardV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.standard = json.loads((ROOT / "evidence/v10/gtm-case-evidence-funnel-v2/standard.json").read_text())
        cls.coverage = json.loads((ROOT / "evidence/v10/gtm-case-evidence-funnel-v2/coverage.json").read_text())
        cls.discovery = json.loads((ROOT / "evidence/v10/gtm-wave1-discovery-leads-v2.json").read_text())
        cls.identity = json.loads((ROOT / "evidence/v10/gtm-case-identity-resolution-v2.json").read_text())
        cls.queue = json.loads((ROOT / "evidence/v10/gtm-mechanism-review-queue-v2.json").read_text())

    def test_dashboard_renders_all_rows_and_truth_boundary(self) -> None:
        html, manifest = build_coverage_dashboard(self.standard, self.coverage, self.discovery, self.identity, self.queue)
        verify_coverage_dashboard(html, manifest)
        self.assertEqual(manifest["subvertical_row_count"], 81)
        self.assertFalse(manifest["completion_claim_allowed"])
        self.assertIn('"structured_candidates":0', html)
        self.assertIn('"structured_candidates":16200', html)
        self.assertNotIn("https://", html)

    def test_tampered_html_fails_hash_check(self) -> None:
        html, manifest = build_coverage_dashboard(self.standard, self.coverage, self.discovery, self.identity, self.queue)
        with self.assertRaisesRegex(GTMCoverageDashboardError, "HTML hash"):
            verify_coverage_dashboard(html + "tamper", manifest)

    def test_unsealed_coverage_fails_closed(self) -> None:
        broken = copy.deepcopy(self.coverage)
        broken["completion_claim_allowed"] = True
        with self.assertRaises(Exception):
            build_coverage_dashboard(self.standard, broken, self.discovery, self.identity, self.queue)


if __name__ == "__main__":
    unittest.main()
