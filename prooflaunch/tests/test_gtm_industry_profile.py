from __future__ import annotations

import unittest
from dataclasses import replace

from prooflaunch_remix.gtm_industry_profile import (
    IndustryArchetype,
    IndustryProfileError,
    bind_industry_profile_strategy,
    compile_industry_gtm_profile,
    industry_archetype_contracts,
    verify_industry_gtm_profile,
)
from prooflaunch_remix.gtm_production_pack import ProductionPackCompiler, ProductionPackError
from prooflaunch_remix.gtm_strategy import BusinessModel, IndustryRisk, StrategyCompiler

from tests.test_gtm_production_pack import NOW, make_claim, make_request


SOURCE_SHA = "b" * 64


class IndustryProfileTests(unittest.TestCase):
    def compile_profile(
        self,
        industry: str,
        *,
        business_model: BusinessModel = BusinessModel.B2B,
        risk: IndustryRisk = IndustryRisk.STANDARD,
    ) -> dict[str, object]:
        request = make_request(
            industry=industry,
            business_model=business_model,
            risk=risk,
        )
        return bind_industry_profile_strategy(
            compile_industry_gtm_profile(request, source_strategy_sha256=SOURCE_SHA),
            strategy_id="strategy-test-001",
        )

    def test_representative_industries_compile_distinct_operating_contracts(self) -> None:
        cases = {
            "enterprise software": IndustryArchetype.B2B_SAAS,
            "developer tools": IndustryArchetype.DEVELOPER_TOOLS,
            "ecommerce": IndustryArchetype.ECOMMERCE_DTC,
            "marketplace": IndustryArchetype.MARKETPLACE,
            "manufacturing": IndustryArchetype.MANUFACTURING_INDUSTRIAL,
            "travel": IndustryArchetype.TRAVEL_HOSPITALITY,
        }
        profiles = [self.compile_profile(industry) for industry in cases]
        self.assertEqual(
            [profile["industry_archetype"] for profile in profiles],
            [archetype.value for archetype in cases.values()],
        )
        self.assertEqual(len({profile["zero_budget_growth_engine"] for profile in profiles}), len(profiles))
        self.assertEqual(len({profile["conversion_unit"] for profile in profiles}), len(profiles))
        self.assertEqual(len({profile["content_sha256"] for profile in profiles}), len(profiles))

    def test_unknown_industry_fails_safe_to_business_model_fallback(self) -> None:
        b2b = self.compile_profile("orbital ceramic orchestration", business_model=BusinessModel.B2B)
        b2c = self.compile_profile("orbital ceramic orchestration", business_model=BusinessModel.B2C)
        self.assertEqual(b2b["industry_archetype"], IndustryArchetype.GENERAL_B2B.value)
        self.assertEqual(b2c["industry_archetype"], IndustryArchetype.GENERAL_B2C.value)
        self.assertTrue(b2b["human_classification_confirmation_required"])
        self.assertTrue(b2c["human_classification_confirmation_required"])
        self.assertFalse(b2b["external_activation_executed"])

    def test_business_model_mismatch_requires_human_confirmation(self) -> None:
        profile = self.compile_profile("consumer app", business_model=BusinessModel.B2B)
        self.assertFalse(profile["business_model_fit"])
        self.assertTrue(profile["human_classification_confirmation_required"])

    def test_known_regulated_industry_rejects_standard_risk(self) -> None:
        for industry in ("fintech", "healthcare", "real estate"):
            with self.subTest(industry=industry), self.assertRaises(IndustryProfileError):
                self.compile_profile(industry)

    def test_regulated_industry_compiles_with_declared_risk_and_specialist(self) -> None:
        profile = self.compile_profile(
            "healthcare",
            business_model=BusinessModel.B2C,
            risk=IndustryRisk.HIGH_REGULATION,
        )
        self.assertEqual(profile["industry_archetype"], IndustryArchetype.HEALTHCARE.value)
        self.assertIn("named specialist approval", profile["proof_gate"])
        self.assertTrue(profile["specialist_roles"])

    def test_every_archetype_has_evidence_economics_and_zero_budget_engine(self) -> None:
        contracts = industry_archetype_contracts()
        self.assertEqual(len(contracts), len(IndustryArchetype))
        for archetype, contract in contracts.items():
            with self.subTest(archetype=archetype):
                self.assertGreaterEqual(len(contract["decision_unit"]), 3)
                self.assertGreaterEqual(len(contract["evidence_ladder"]), 4)
                self.assertGreaterEqual(len(contract["unit_economics_metrics"]), 4)
                self.assertGreaterEqual(len(contract["feedback_signals"]), 3)
                self.assertTrue(contract["zero_budget_growth_engine"])
                self.assertTrue(contract["creative_constraints"])

    def test_digest_tamper_is_rejected(self) -> None:
        profile = self.compile_profile("enterprise software")
        tampered = {**profile, "conversion_unit": "invented conversion"}
        with self.assertRaisesRegex(IndustryProfileError, "digest"):
            verify_industry_gtm_profile(tampered)

    def test_production_pack_binds_profile_and_injects_constraints(self) -> None:
        request = make_request(industry="developer tools")
        strategy = StrategyCompiler().compile(request, at=NOW)
        pack = ProductionPackCompiler().compile(request, strategy)
        profile = pack.industry_gtm_profile
        self.assertEqual(profile["strategy_id"], strategy.strategy_id)
        self.assertEqual(profile["industry_archetype"], IndustryArchetype.DEVELOPER_TOOLS.value)
        self.assertIn("industry-gtm-profile.json", pack.artifact_payloads())
        self.assertTrue(set(profile["creative_constraints"]).issubset(pack.safety_constraints))
        self.assertIn(profile["zero_budget_growth_engine"], pack.big_idea.organizing_idea)

    def test_production_pack_fails_closed_on_misdeclared_regulated_industry(self) -> None:
        request = make_request(industry="fintech")
        strategy = StrategyCompiler().compile(request, at=NOW)
        with self.assertRaisesRegex(ProductionPackError, "high_regulation"):
            ProductionPackCompiler().compile(request, strategy)

    def test_regulated_pack_compiles_with_named_specialist(self) -> None:
        request = make_request(
            industry="fintech",
            risk=IndustryRisk.HIGH_REGULATION,
            claim=make_claim(specialist_approved_by="licensed-reviewer-001"),
        )
        strategy = StrategyCompiler().compile(request, at=NOW)
        pack = ProductionPackCompiler().compile(request, strategy)
        self.assertTrue(pack.manual_release.specialist_gate_required)
        self.assertEqual(pack.industry_gtm_profile["industry_risk"], "high_regulation")


if __name__ == "__main__":
    unittest.main()
