from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from prooflaunch_remix.gtm_breakout_campaign import (
    GTMBreakoutCampaignError,
    compile_breakout_portfolio,
    seal_candidate,
    verify_breakout_candidate,
    verify_breakout_portfolio,
)


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "evidence" / "v10" / "gtm-breakout-release-candidates-v1.json"


def _portfolio() -> dict:
    return json.loads(ARTIFACT.read_text(encoding="utf-8"))


def _reseal(candidate: dict) -> dict:
    return seal_candidate(candidate)


class GTMBreakoutCampaignTests(unittest.TestCase):
    def test_release_portfolio_is_valid_and_cross_industry(self) -> None:
        portfolio = _portfolio()
        verify_breakout_portfolio(portfolio)
        self.assertEqual(portfolio["candidate_count"], 2)
        self.assertEqual(portfolio["surface_count"], 26)
        self.assertEqual({audit["business_model"] for audit in portfolio["audits"]}, {"b2b", "b2c"})
        self.assertTrue(all(audit["evidence_mechanism_count"] >= 5 for audit in portfolio["audits"]))
        self.assertTrue(all(audit["evidence_case_count"] >= 6 for audit in portfolio["audits"]))

    def test_cross_platform_copy_clone_fails(self) -> None:
        candidate = copy.deepcopy(_portfolio()["candidates"][0])
        linkedin = next(asset for asset in candidate["assets"] if asset["surface_id"] == "linkedin")
        facebook = next(asset for asset in candidate["assets"] if asset["surface_id"] == "facebook")
        facebook["publishable_copy"] = linkedin["publishable_copy"]
        with self.assertRaisesRegex(GTMBreakoutCampaignError, "cross-platform rewrites"):
            verify_breakout_candidate(_reseal(candidate))

    def test_generic_cta_fails(self) -> None:
        candidate = copy.deepcopy(_portfolio()["candidates"][1])
        candidate["assets"][0]["cta"] = "Learn more"
        with self.assertRaisesRegex(GTMBreakoutCampaignError, "generic CTA"):
            verify_breakout_candidate(_reseal(candidate))

    def test_automatic_publish_fails(self) -> None:
        candidate = copy.deepcopy(_portfolio()["candidates"][0])
        candidate["permissions"]["automatic_publish"] = True
        with self.assertRaisesRegex(GTMBreakoutCampaignError, "permissions escaped"):
            verify_breakout_candidate(_reseal(candidate))

    def test_missing_evidence_application_fails(self) -> None:
        candidate = copy.deepcopy(_portfolio()["candidates"][0])
        candidate.pop("evidence_application")
        with self.assertRaisesRegex(GTMBreakoutCampaignError, "evidence application"):
            verify_breakout_candidate(_reseal(candidate))

    def test_zero_paid_media_precedent_cannot_be_invented(self) -> None:
        candidate = copy.deepcopy(_portfolio()["candidates"][1])
        candidate["evidence_application"]["claims_zero_paid_media_precedent"] = True
        with self.assertRaisesRegex(GTMBreakoutCampaignError, "zero-paid-media precedent"):
            verify_breakout_candidate(_reseal(candidate))

    def test_tamper_without_reseal_fails_digest(self) -> None:
        candidate = copy.deepcopy(_portfolio()["candidates"][0])
        candidate["brief"]["voice"] = "tampered voice"
        with self.assertRaisesRegex(GTMBreakoutCampaignError, "digest"):
            verify_breakout_candidate(candidate)


if __name__ == "__main__":
    unittest.main()
