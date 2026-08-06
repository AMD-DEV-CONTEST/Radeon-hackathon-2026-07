from __future__ import annotations

import copy
import hashlib
import json
import unittest
from dataclasses import replace
from pathlib import Path

from prooflaunch_remix.gtm_market_language import (
    MarketLanguageError,
    build_platform_copy_bible,
    compile_market_language_contract,
    verify_market_language_contract,
)
from prooflaunch_remix.gtm_strategy import BudgetTier, BusinessModel, ProductSurface
from scripts.compile_gtm_market_language_matrix import _template, compile_market_language_matrix


ROOT = Path(__file__).resolve().parents[1]


class MarketLanguageTests(unittest.TestCase):
    def test_b2b_roles_compile_different_last_mile_language_jobs(self) -> None:
        base = replace(
            _template(),
            product_category="software_ai_data",
            product_surface=ProductSurface.WEB_AGENT,
            distribution_platform="linkedin",
            audience_role="economic_buyer",
        )
        buyer = compile_market_language_contract(base)
        evaluator = compile_market_language_contract(
            replace(base, audience_role="technical_evaluator")
        )
        self.assertNotEqual(
            buyer["primary_audience_contract"]["decision_or_use_job"],
            evaluator["primary_audience_contract"]["decision_or_use_job"],
        )
        self.assertNotEqual(
            buyer["language_signature_sha256"],
            evaluator["language_signature_sha256"],
        )
        self.assertEqual(buyer["primary_audience_contract"]["primary_role_count"], 1)
        self.assertEqual(
            buyer["platform_copy_bible_binding"]["binding_status"],
            "sealed_platform_contract",
        )
        self.assertEqual(
            buyer["platform_copy_bible_binding"]["copy_bible_sha256"],
            build_platform_copy_bible()["content_sha256"],
        )

    def test_b2c_mobile_use_state_is_not_b2b_committee_language(self) -> None:
        template = _template()
        b2c = compile_market_language_contract(
            replace(
                template,
                audience=replace(template.audience, business_model=BusinessModel.B2C),
                product_category="health_fitness_medical",
                product_surface=ProductSurface.MOBILE_APP,
                distribution_platform="tiktok",
                audience_role="switcher",
            )
        )
        self.assertEqual(
            b2c["context"]["resolved_reference_family"],
            "health_fitness_medical",
        )
        self.assertEqual(b2c["context"]["resolved_primary_role"], "switcher")
        self.assertIn("first beat", b2c["platform_translation"]["opening_contract"])
        self.assertNotIn(
            "committee",
            b2c["primary_audience_contract"]["decision_or_use_job"],
        )

    def test_unknown_category_and_role_remain_owner_confirmed_not_inferred(self) -> None:
        contract = compile_market_language_contract(
            replace(
                _template(),
                product_category="a novel owner-only category",
                audience_role="a novel owner-only role",
            )
        )
        self.assertEqual(
            contract["context"]["resolved_reference_family"], "owner_declared_other"
        )
        self.assertEqual(
            contract["context"]["resolved_primary_role"], "owner_declared_other"
        )
        self.assertTrue(
            contract["audience_asset_contract"]["owner_confirmation_required"]
        )

    def test_zero_budget_and_release_boundaries_fail_closed(self) -> None:
        contract = compile_market_language_contract(
            replace(_template(), budget=BudgetTier.ZERO)
        )
        self.assertFalse(contract["budget_contract"]["paid_activation_allowed"])
        self.assertEqual(contract["external_action_count"], 0)
        tampered = copy.deepcopy(contract)
        tampered["budget_contract"]["paid_activation_allowed"] = True
        with self.assertRaisesRegex(MarketLanguageError, "digest"):
            verify_market_language_contract(tampered)

    def test_copy_bible_has_eight_distinct_platform_jobs(self) -> None:
        bible = build_platform_copy_bible()
        self.assertEqual(bible["platform_count"], 8)
        self.assertEqual(
            set(bible["platforms"]),
            {"linkedin", "reddit", "x", "tiktok", "instagram", "youtube", "email", "seo_geo"},
        )
        self.assertEqual(
            len({row["platform_job"] for row in bible["platforms"].values()}),
            8,
        )
        self.assertFalse(
            bible["cross_platform_rules"]["identical_copy_across_platforms_allowed"]
        )

    def test_full_market_language_matrix_is_exact_distinct_and_action_free(self) -> None:
        matrix = compile_market_language_matrix()
        coverage = matrix["coverage"]
        self.assertEqual(coverage["b2b_case_count"], 5_184)
        self.assertEqual(coverage["b2c_case_count"], 6_480)
        self.assertEqual(coverage["total_case_count"], 11_664)
        self.assertEqual(coverage["distinct_language_signature_count"], 11_664)
        self.assertEqual(coverage["zero_budget_paid_activation_count"], 0)
        self.assertEqual(coverage["missing_owner_confirmation_count"], 0)
        self.assertEqual(coverage["automatic_external_action_count"], 0)
        artifact = json.loads(
            (ROOT / "evidence/v10/gtm-market-language-matrix-v1.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(artifact, matrix)
        unsigned = dict(matrix)
        supplied = unsigned.pop("content_sha256")
        canonical = json.dumps(
            unsigned,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        self.assertEqual(
            supplied,
            hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        )


if __name__ == "__main__":
    unittest.main()
