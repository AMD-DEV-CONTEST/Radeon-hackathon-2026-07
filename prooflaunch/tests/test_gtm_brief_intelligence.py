from __future__ import annotations

import unittest

from prooflaunch_remix.gtm_brief_intelligence import (
    BriefIntelligenceError,
    ProductEvidenceInput,
    compile_brief_intelligence,
    compile_product_evidence_register,
    verify_brief_intelligence,
)


def claim(**overrides: object) -> ProductEvidenceInput:
    values: dict[str, object] = {
        "claim_id": "claim-feature-001",
        "claim_type": "feature",
        "claim_text": "The workflow emits a content-addressed trace.",
        "source_uri": "owner://product/trace-specification",
        "source_sha256": "a" * 64,
        "rights_status": "owner_attested",
        "rights_reference": "Owned product specification.",
        "release_scope": "draft_only",
        "valid_from": "2026-08-01T00:00:00Z",
        "valid_until": None,
        "approved_by": None,
        "specialist_approved_by": None,
    }
    values.update(overrides)
    return ProductEvidenceInput(**values)  # type: ignore[arg-type]


class BriefIntelligenceTests(unittest.TestCase):
    def test_mapping_rejects_null_required_claim_text_instead_of_stringifying_it(self) -> None:
        candidate = {
            "claim_id": "claim-feature-001",
            "claim_type": "feature",
            "claim_text": None,
            "source_uri": "owner://product/trace-specification",
            "source_sha256": "a" * 64,
            "rights_status": "owner_attested",
            "rights_reference": "Owned product specification.",
            "release_scope": "draft_only",
            "valid_from": "2026-08-01T00:00:00Z",
        }
        with self.assertRaisesRegex(BriefIntelligenceError, "claim_text"):
            ProductEvidenceInput.from_mapping(candidate)

    def test_owner_attestation_supports_draft_but_not_public_release(self) -> None:
        register = compile_product_evidence_register(
            [claim()],
            evaluated_at="2026-08-05T00:00:00Z",
            high_regulation=False,
        )
        self.assertTrue(register["all_claims_draft_generation_eligible"])
        self.assertFalse(register["all_claims_public_release_eligible"])
        self.assertIn(
            "named_claim_approver_missing",
            register["claims"][0]["release_blockers"],
        )
        self.assertFalse(register["training_admitted"])

    def test_named_approved_scope_makes_claim_release_eligible(self) -> None:
        register = compile_product_evidence_register(
            [
                claim(
                    rights_status="owner_approved",
                    release_scope="campaign_public_channels",
                    approved_by="Named Product Owner",
                )
            ],
            evaluated_at="2026-08-05T00:00:00Z",
            high_regulation=False,
        )
        self.assertTrue(register["all_claims_public_release_eligible"])
        self.assertEqual(register["public_release_eligible_count"], 1)

    def test_brief_has_one_tension_and_at_most_five_material_questions(self) -> None:
        register = compile_product_evidence_register(
            [claim()],
            evaluated_at="2026-08-05T00:00:00Z",
            high_regulation=False,
        )
        tension = {
            "tension_id": "tension-001",
            "audience": "founder-led B2B teams",
            "problem": "content volume rises while decision-grade trust falls",
            "business_constraint": "no paid media in the first seven-day flight",
            "evidence_ids": ["claim-feature-001"],
            "falsifier": "qualified action does not beat the frozen baseline",
            "primary_outcome_metric": "qualified_action_rate",
        }
        brief = compile_brief_intelligence(
            {
                "campaign_id": "campaign-001",
                "product_name": "ProofLaunch",
                "industry": "unspecified",
                "business_model": "b2b",
                "lifecycle": "launch",
                "budget": "zero",
                "brand_reach": "emerging",
                "product_category": "owner_category_unspecified",
                "audience_role": "owner_role_unspecified",
                "buying_context": "owner context not supplied",
                "goal": "Guarantee a viral launch",
            },
            product_evidence_register=register,
            growth_tension=tension,
        )
        verify_brief_intelligence(brief)
        self.assertEqual(len(brief["growth_tensions"]), 1)
        self.assertLessEqual(brief["critical_question_count"], 5)
        self.assertTrue(brief["goal_feasibility"]["challenged"])
        self.assertFalse(brief["automatic_strategy_mutation_executed"])

    def test_tamper_and_multiple_tensions_fail_closed(self) -> None:
        with self.assertRaisesRegex(BriefIntelligenceError, "incomplete"):
            compile_brief_intelligence(
                {
                    "business_model": "b2c",
                    "lifecycle": "launch",
                    "budget": "zero",
                    "brand_reach": "emerging",
                },
                product_evidence_register={},
                growth_tension={},
            )


if __name__ == "__main__":
    unittest.main()
