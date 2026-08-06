from __future__ import annotations

import hashlib
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

from prooflaunch_remix.gtm_production_quality_contract import (
    COPY_BIBLE_FIELDS,
    REQUIRED_COPY_BIBLE_PLATFORMS,
    build_production_quality_contract,
    evaluate_organic_breakout_candidate,
    evaluate_platform_copy_bible,
    evaluate_product_evidence_claims,
    evaluate_quality_ladder,
    evaluate_single_growth_tension,
    verify_production_quality_contract,
)
from scripts.compile_gtm_production_quality_contract import (
    build_current_evaluation,
    render_markdown,
)
from prooflaunch_remix.gtm_market_language import build_platform_copy_bible


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "config/gtm_production_quality_contract_v1.json"
EVIDENCE = ROOT / "evidence/v10/gtm-production-quality-current-v1.json"
REPORT = ROOT / "docs/product/GTM_PRODUCTION_QUALITY_OPERATING_CONTRACT_V1.md"
COPY_BIBLE = ROOT / "config/gtm_platform_copy_bible_v1.json"


def complete_evidence() -> dict[str, object]:
    return {
        "artifact_contract_passed": True,
        "rights_gate_passed": True,
        "claim_evidence_gate_passed": True,
        "platform_contract_passed": True,
        "identity_gate_passed": True,
        "accessibility_gate_passed": True,
        "blocking_defect_count": 0,
        "qualified_review_count": 10,
        "directly_publishable_count": 9,
        "major_rework_count": 1,
        "human_blocking_defect_count": 0,
        "blind_comparison_count": 5,
        "candidate_preferred_count": 5,
        "named_external_baseline_present": True,
        "source_hidden_review": True,
        "publication_receipt_count": 1,
        "authorized_observation_count": 1,
        "primary_metric_pre_registered": True,
        "observed_sample_size": 100,
        "registered_minimum_sample": 100,
        "primary_metric_decision": "success",
        "incremental_design_gate_passed": True,
        "attribution_integrity_passed": True,
        "safety_regression_observed": False,
        "qualified_conversion_rate": 0.12,
        "time_to_first_human_publishable_asset_hours": 1.5,
    }


class GTMProductionQualityContractTests(unittest.TestCase):
    def test_sealed_outputs_match_compilers(self) -> None:
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
        self.assertEqual(contract, build_production_quality_contract())
        self.assertEqual(evidence, build_current_evaluation())
        self.assertEqual(REPORT.read_text(encoding="utf-8"), render_markdown(contract, evidence))
        self.assertEqual(
            json.loads(COPY_BIBLE.read_text(encoding="utf-8")),
            build_platform_copy_bible(),
        )
        verify_production_quality_contract(contract)
        self.assertTrue(
            evidence["priority_capability_checks"]["T041_platform_copy_bible"]["passed"]
        )
        self.assertTrue(
            evidence["priority_capability_checks"]["T021_natural_breakout_admission"]["passed"]
        )
        self.assertEqual(
            evidence["priority_capability_checks"]["T021_natural_breakout_admission"]
            ["candidate_level_relative_breakouts_admitted"],
            9,
        )
        self.assertTrue(
            evidence["priority_capability_checks"]["T033_single_growth_tension"]["passed"]
        )
        self.assertFalse(
            evidence["priority_capability_checks"]["T014_product_evidence_extractor"]["passed"]
        )

    def test_current_run_is_only_mechanically_ready(self) -> None:
        current = build_current_evaluation()
        ladder = current["quality_ladder"]
        self.assertEqual(ladder["current_state"], "mechanically_ready")
        self.assertTrue(ladder["gates"]["G0_contract"]["passed"])
        self.assertFalse(ladder["gates"]["G1_professional_editor"]["passed"])
        self.assertFalse(ladder["gates"]["G2_same_brief_blind_pk"]["passed"])
        self.assertFalse(ladder["gates"]["G3_production_effect"]["passed"])
        self.assertFalse(ladder["promotion_allowed"])
        self.assertIsNone(ladder["observed_metrics"]["directly_publishable_rate"])

    def test_all_four_gates_are_required_for_production_proven(self) -> None:
        result = evaluate_quality_ladder(complete_evidence())
        self.assertEqual(result["current_state"], "production_proven")
        self.assertTrue(all(gate["passed"] for gate in result["gates"].values()))
        self.assertTrue(result["promotion_allowed"])
        self.assertFalse(result["automatic_release_allowed"])
        self.assertFalse(result["automatic_learning_allowed"])

    def test_missing_or_model_only_evidence_fails_closed(self) -> None:
        evidence = complete_evidence()
        evidence["qualified_review_count"] = 0
        evidence["directly_publishable_count"] = 0
        evidence["major_rework_count"] = 0
        evidence["model_judge_score"] = 1.0
        result = evaluate_quality_ladder(evidence)
        self.assertEqual(result["current_state"], "mechanically_ready")
        self.assertFalse(result["gates"]["G1_professional_editor"]["passed"])
        self.assertIsNone(result["observed_metrics"]["directly_publishable_rate"])

    def test_product_claims_require_release_rights_and_source_hash(self) -> None:
        base = {
            "claim_id": "claim-1",
            "claim_text": "The workflow emits an immutable trace.",
            "source_uri": "owner://evidence/claim-1",
            "source_sha256": "a" * 64,
            "rights_status": "owner_approved",
            "valid_at": "2026-08-05T00:00:00Z",
            "release_scope": "campaign-prooflaunch",
            "approved_by": "Named Product Owner",
        }
        self.assertTrue(evaluate_product_evidence_claims([base])["passed"])
        bad = {**base, "rights_status": "owner_attested", "source_sha256": "bad"}
        result = evaluate_product_evidence_claims([bad])
        self.assertFalse(result["passed"])
        self.assertGreaterEqual(len(result["blocking_findings"]), 2)

    def test_natural_breakout_requires_relative_baseline_and_paid_status(self) -> None:
        candidate = {
            "source_url": "https://example.com/public/post/1",
            "published_at": "2026-07-15T00:00:00Z",
            "account_baseline_item_count": 20,
            "item_attention": 2400,
            "baseline_median_attention": 1000,
            "item_interactions": 90,
            "baseline_median_interactions": 50,
            "paid_distribution_status": "organic_only_verified",
            "rights_status": "public_measurement",
            "source_sha256": "b" * 64,
            "capture_sha256": "c" * 64,
        }
        observed = datetime(2026, 8, 5, tzinfo=timezone.utc)
        result = evaluate_organic_breakout_candidate(candidate, observed_at=observed)
        self.assertTrue(result["passed"])
        self.assertFalse(result["causal_growth_claim_allowed"])
        self.assertFalse(result["training_admitted"])
        rejected = evaluate_organic_breakout_candidate(
            {**candidate, "paid_distribution_status": "unknown"},
            observed_at=observed,
        )
        self.assertFalse(rejected["passed"])

    def test_single_growth_tension_requires_one_falsifiable_choice(self) -> None:
        self.assertFalse(evaluate_single_growth_tension({})["passed"])
        strategy = {
            "growth_tensions": [
                {
                    "audience": "founder-led B2B teams",
                    "problem": "content volume rises while decision-grade trust falls",
                    "business_constraint": "zero paid media for the first seven-day flight",
                    "evidence_ids": ["claim-1", "signal-2"],
                    "falsifier": "qualified evidence engagement does not beat the frozen baseline",
                    "primary_outcome_metric": "qualified_action_rate",
                }
            ]
        }
        self.assertTrue(evaluate_single_growth_tension(strategy)["passed"])

    def test_copy_bible_requires_distinct_platform_native_contracts(self) -> None:
        platforms = {
            platform: {
                field: [f"{platform}:{field}"]
                for field in COPY_BIBLE_FIELDS
            }
            for platform in REQUIRED_COPY_BIBLE_PLATFORMS
        }
        self.assertTrue(evaluate_platform_copy_bible({"platforms": platforms})["passed"])
        duplicate = dict(platforms)
        duplicate["reddit"] = duplicate["linkedin"]
        result = evaluate_platform_copy_bible({"platforms": duplicate})
        self.assertFalse(result["passed"])
        self.assertTrue(any("duplicates" in failure for failure in result["failures"]))

    def test_evaluation_digest_covers_all_gate_results(self) -> None:
        result = evaluate_quality_ladder(complete_evidence())
        supplied = result.pop("content_sha256")
        encoded = json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        self.assertEqual(supplied, hashlib.sha256(encoded.encode("utf-8")).hexdigest())


if __name__ == "__main__":
    unittest.main()
