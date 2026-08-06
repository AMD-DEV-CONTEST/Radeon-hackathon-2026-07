from __future__ import annotations

import unittest

from scripts.validate_amd_track1_package import EXPECTED_TITLE, validate


class AMDTrack1PackageTests(unittest.TestCase):
    def test_official_package_structure_is_consistent(self) -> None:
        report = validate()
        self.assertEqual(report["structural_status"], "passed", report["errors"])
        self.assertEqual(report["competition_status"], "blocked")
        self.assertTrue(report["runtime_blockers"])

    def test_final_title_has_team_product_and_direction(self) -> None:
        self.assertEqual(
            EXPECTED_TITLE,
            "Track 1, Banyan, ProofLaunch: Multimodal GTM Studio",
        )


if __name__ == "__main__":
    unittest.main()
