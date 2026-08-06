from __future__ import annotations

import copy
import hashlib
import json
import unittest
from pathlib import Path

from prooflaunch_remix.gtm_codex_lighthouse_portfolio import (
    CodexLighthousePortfolioError,
    compile_lighthouse_portfolio,
    compile_lighthouse_quality_portfolio,
    verify_lighthouse_candidate,
    verify_lighthouse_portfolio,
    verify_lighthouse_quality_portfolio,
)


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config/codex-lighthouse-execution-candidates-v1.json"
SEALED_PORTFOLIO = ROOT / "evidence/v10/gtm-codex-lighthouse-portfolio-v1.json"
SEALED_QUALITY = ROOT / "evidence/v10/gtm-codex-lighthouse-quality-audit-v1.json"


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _drafts() -> list[dict[str, object]]:
    source = json.loads(CONFIG.read_text(encoding="utf-8"))
    assert source["schema"] == "ProofLaunchCodexLighthouseDraftSetV1"
    return source["drafts"]


class CodexLighthousePortfolioTests(unittest.TestCase):
    def test_eight_codex_workspace_candidates_cover_b2b_b2c_lifecycle_budget_and_industry(self) -> None:
        portfolio = compile_lighthouse_portfolio(_drafts())
        verify_lighthouse_portfolio(portfolio)
        self.assertEqual(portfolio["candidate_count"], 8)
        self.assertEqual(portfolio["workspace_authored_candidate_count"], 8)
        self.assertEqual(portfolio["platform_asset_count"], 16)
        self.assertEqual(portfolio["email_count"], 8)
        self.assertEqual(portfolio["seo_page_count"], 8)
        self.assertEqual(portfolio["geo_answer_count"], 8)
        self.assertEqual(portfolio["video_script_count"], 8)
        self.assertEqual(portfolio["experiment_count"], 8)
        selectors = [row["selector"] for row in portfolio["candidates"]]
        for model in ("b2b", "b2c"):
            rows = [row for row in selectors if row["business_model"] == model]
            self.assertEqual(len(rows), 4)
            self.assertEqual(
                {row["lifecycle"] for row in rows},
                {"pre_pmf", "launch", "growth", "mature"},
            )
        self.assertEqual({row["budget"] for row in selectors}, {"zero", "small", "scaled"})
        self.assertEqual(len({row["industry_archetype"] for row in selectors}), 8)
        self.assertEqual(portfolio["regulated_candidate_count"], 2)
        for candidate in portfolio["candidates"]:
            authorship = candidate["authorship"]
            self.assertTrue(authorship["workspace_model_authorship_asserted"])
            self.assertFalse(authorship["flagship_api_inference_observed"])
            self.assertEqual(authorship["api_call_count"], "not_measured_by_worktree")
            self.assertTrue(authorship["synthetic_reference_only"])
            state = candidate["execution_state"]
            self.assertFalse(state["level_1_mechanical_audit_present"])
            self.assertFalse(state["release_eligible"])
            self.assertFalse(state["external_publish_executed"])
            self.assertFalse(state["production_effect_observed"])

    def test_all_eight_content_addressed_level_one_audits_pass_without_authority_upgrade(self) -> None:
        portfolio = compile_lighthouse_portfolio(_drafts())
        quality = compile_lighthouse_quality_portfolio(portfolio)
        verify_lighthouse_quality_portfolio(quality, portfolio=portfolio)
        self.assertEqual(quality["level_1_audit_count"], 8)
        self.assertEqual(quality["level_1_pass_count"], 8)
        self.assertEqual(quality["level_1_reject_count"], 0)
        self.assertEqual(quality["located_critical_failure_count"], 0)
        self.assertEqual(quality["calibrated_model_critic_pass_count"], 0)
        self.assertEqual(quality["qualified_human_review_count"], 0)
        self.assertEqual(quality["release_eligible_count"], 0)
        self.assertEqual(quality["production_effect_observed_count"], 0)
        self.assertEqual(quality["causal_revenue_effect_proven_count"], 0)
        self.assertFalse(quality["model_critic_counts_in_preference_denominator"])
        self.assertFalse(quality["four_a_quality_proven"])
        self.assertFalse(quality["top1_claim_eligible"])
        self.assertTrue(all(receipt["passed"] for receipt in quality["audits"]))

    def test_sealed_portfolio_and_quality_artifacts_equal_the_compilers(self) -> None:
        compiled = compile_lighthouse_portfolio(_drafts())
        quality = compile_lighthouse_quality_portfolio(compiled)
        self.assertEqual(
            json.loads(SEALED_PORTFOLIO.read_text(encoding="utf-8")),
            compiled,
        )
        self.assertEqual(
            json.loads(SEALED_QUALITY.read_text(encoding="utf-8")),
            quality,
        )

    def test_candidate_and_quality_authority_tamper_fail_even_after_resealing(self) -> None:
        portfolio = compile_lighthouse_portfolio(_drafts())
        candidate = copy.deepcopy(portfolio["candidates"][0])
        candidate["execution_state"]["release_eligible"] = True
        unsigned_candidate = dict(candidate)
        unsigned_candidate.pop("content_sha256")
        candidate["content_sha256"] = _digest(unsigned_candidate)
        with self.assertRaisesRegex(CodexLighthousePortfolioError, "authority"):
            verify_lighthouse_candidate(candidate)

        quality = compile_lighthouse_quality_portfolio(portfolio)
        tampered = copy.deepcopy(quality)
        tampered["release_eligible_count"] = 1
        unsigned_quality = dict(tampered)
        unsigned_quality.pop("content_sha256")
        tampered["content_sha256"] = _digest(unsigned_quality)
        with self.assertRaisesRegex(CodexLighthousePortfolioError, "authority"):
            verify_lighthouse_quality_portfolio(tampered, portfolio=portfolio)


if __name__ == "__main__":
    unittest.main()
