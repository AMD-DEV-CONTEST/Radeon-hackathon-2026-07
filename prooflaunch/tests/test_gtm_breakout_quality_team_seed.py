from __future__ import annotations

import copy
import unittest

from prooflaunch_remix.gtm_breakout_quality_team_seed import (
    GTMBreakoutQualityTeamSeedError,
    compile_breakout_quality_team_seed,
    verify_breakout_quality_team_seed,
)
from scripts.compile_gtm_breakout_quality_team_seed import CASES


class BreakoutQualityTeamSeedTests(unittest.TestCase):
    def test_seed_is_bounded_and_no_team_bypasses_promotion(self):
        payload = compile_breakout_quality_team_seed(CASES, captured_at="2026-08-04T00:00:00-04:00")
        verify_breakout_quality_team_seed(payload)
        self.assertEqual(payload["team_count"], 34)
        self.assertTrue(all(team["breakout_team_fully_promoted"] is False for team in payload["teams"]))
        self.assertTrue(all(team["zero_budget_proof"] is False for team in payload["teams"]))
        self.assertEqual(payload["selection_policy"]["accelerator_membership_weight"], 0)
        self.assertEqual(payload["selection_policy"]["funding_weight"], 0)
        self.assertFalse(payload["selection_policy"]["zero_budget_required"])
        self.assertEqual(payload["selection_policy"]["cold_start_resource_window_months"], [6, 12])
        self.assertGreaterEqual(payload["cold_start_budget_tier_counts"]["cold_start_zero_paid"], 4)
        priority_sectors = {
            team.get("sector_focus")
            for team in payload["teams"]
            if team["team_id"] in {
                "solberg-manufacturing", "reposit-power", "wingtra", "viessmann", "insinkerator",
                "rever-vn", "smash-my-trash", "fbi-buildings", "2030-builders", "pure-bookkeeping",
                "strategic-ic", "beard-and-blade-wholesale",
            }
        }
        self.assertEqual(len(priority_sectors), 12)
        self.assertEqual(sum(payload["sector_focus_counts"].values()), 12)
        self.assertIn("industrial manufacturing and distribution", payload["sector_focus_counts"])
        self.assertIn("post-frame construction", payload["sector_focus_counts"])
        self.assertIn("real-estate brokerage", payload["sector_focus_counts"])
        self.assertIn("B2B professional services", payload["sector_focus_counts"])

    def test_mechanism_ready_team_has_required_core_dimensions(self):
        payload = compile_breakout_quality_team_seed(CASES, captured_at="2026-08-04T00:00:00-04:00")
        for team in payload["teams"]:
            if team["promotion_status"] == "mechanism_distillation_ready":
                dimensions = team["evidence_dimensions"]
                self.assertEqual(dimensions["hard_outcome"], "verified")
                self.assertEqual(dimensions["current_operation"], "verified")
                self.assertIn(dimensions["channel_mechanism"], {"verified", "partial"})
                self.assertIn(dimensions["retention_or_repeatability"], {"verified", "partial"})

    def test_tamper_is_rejected(self):
        payload = compile_breakout_quality_team_seed(CASES, captured_at="2026-08-04T00:00:00-04:00")
        tampered = copy.deepcopy(payload)
        tampered["teams"][0]["zero_budget_proof"] = True
        with self.assertRaises(GTMBreakoutQualityTeamSeedError):
            verify_breakout_quality_team_seed(tampered)


if __name__ == "__main__":
    unittest.main()
