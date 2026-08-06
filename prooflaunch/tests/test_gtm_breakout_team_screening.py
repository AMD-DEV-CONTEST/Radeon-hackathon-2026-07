from __future__ import annotations

import copy
import unittest

from prooflaunch_remix.gtm_breakout_team_screening import (
    GTMBreakoutTeamScreeningError,
    compile_breakout_team_screen,
    verify_breakout_team_screen,
)


def _fast500_rows():
    return [
        {
            "rank": rank,
            "company_name": f"Company {rank}",
            "primary_industry": "Software & services",
            "revenue_growth_percent": 10001 - rank,
            "city": "Test City",
            "state_or_province": "CA",
        }
        for rank in range(1, 501)
    ]


class BreakoutTeamScreeningTests(unittest.TestCase):
    def test_yc_identity_has_zero_quality_weight(self):
        landscape = {
            "records": [
                {
                    "name": "Company 500",
                    "company_id": "company-500",
                    "official_directory_url": "https://www.ycombinator.com/companies/company-500",
                    "business_model": "b2b",
                    "directory_status": "Active",
                }
            ]
        }
        screen = compile_breakout_team_screen(
            _fast500_rows(),
            landscape,
            source_url="https://example.com/fast500.pdf",
            source_pdf_sha256="a" * 64,
        )
        verify_breakout_team_screen(screen)
        first = screen["candidates"][0]
        last = screen["candidates"][-1]
        self.assertEqual(first["rank"], 1)
        self.assertEqual(last["rank"], 500)
        self.assertGreater(first["outcome_screen_score"], last["outcome_screen_score"])
        self.assertEqual(last["identity_evidence_completion_score"], 40)
        self.assertFalse(last["yc_identity_contributes_to_outcome_score"])
        self.assertEqual(screen["quality_screening_policy"]["yc_membership_quality_weight"], 0)
        self.assertEqual(screen["outcome_priority_band_counts"], {"p0": 50, "p1": 100, "p2": 350})

    def test_ambiguous_name_does_not_auto_match(self):
        rows = _fast500_rows()
        rows[-1] = {**rows[-1], "company_name": "Company 1"}
        landscape = {
            "records": [
                {
                    "name": "Company 1",
                    "company_id": "company-1",
                    "official_directory_url": "https://www.ycombinator.com/companies/company-1",
                    "business_model": "b2b",
                    "directory_status": "Active",
                }
            ]
        }
        screen = compile_breakout_team_screen(
            rows,
            landscape,
            source_url="https://example.com/fast500.pdf",
            source_pdf_sha256="b" * 64,
        )
        matches = [candidate for candidate in screen["candidates"] if candidate["company_name"] == "Company 1"]
        self.assertEqual(len(matches), 2)
        self.assertTrue(all(candidate["yc_company_id"] is None for candidate in matches))
        self.assertTrue(all(candidate["startup_identity_crosscheck"] == "ambiguous_name_requires_domain_review" for candidate in matches))

    def test_tamper_is_rejected(self):
        screen = compile_breakout_team_screen(
            _fast500_rows(),
            {"records": []},
            source_url="https://example.com/fast500.pdf",
            source_pdf_sha256="c" * 64,
        )
        tampered = copy.deepcopy(screen)
        tampered["candidates"][0]["outcome_screen_score"] = 0
        with self.assertRaises(GTMBreakoutTeamScreeningError):
            verify_breakout_team_screen(tampered)


if __name__ == "__main__":
    unittest.main()
