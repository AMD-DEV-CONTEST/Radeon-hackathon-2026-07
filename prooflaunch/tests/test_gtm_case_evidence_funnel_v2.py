from __future__ import annotations

import copy
import hashlib
import unittest

from prooflaunch_remix.gtm_case_evidence_funnel_v2 import (
    GTMCaseEvidenceFunnelError,
    QUOTA_DIMENSIONS,
    build_case_evidence_funnel_standard,
    compile_case_evidence_funnel_coverage,
    compile_seed_migration_queue,
    verify_case_evidence_funnel_coverage,
    verify_case_evidence_funnel_standard,
)


def _expanded(quota: dict[str, int]) -> list[str]:
    return [bucket for bucket, count in quota.items() for _ in range(count)]


def _candidate(index: int, subvertical_id: str) -> dict:
    buckets = {dimension: _expanded(quota) for dimension, quota in QUOTA_DIMENSIONS.items()}
    receipt_sha = hashlib.sha256(f"source-{index}".encode()).hexdigest()
    budget_tier = buckets["budget_tier"][index]
    resource_costs = {
        component: {
            "disclosure_status": "unknown",
            "amount_usd": None,
            "evidence_receipt_sha256s": [],
            "notes": "The source does not disclose a complete numeric amount for this cost component.",
        }
        for component in ("paid_media", "personnel", "tools", "creators", "channel_fees", "production")
    }
    if budget_tier == "zero_paid":
        resource_costs["paid_media"] = {
            "disclosure_status": "known_zero",
            "amount_usd": 0,
            "evidence_receipt_sha256s": [receipt_sha],
            "notes": "The observed window explicitly reports zero paid media while other inputs remain recorded separately.",
        }
    else:
        resource_costs["paid_media"] = {
            "disclosure_status": "bounded_estimate",
            "amount_usd": 1000 + index,
            "evidence_receipt_sha256s": [receipt_sha],
            "notes": "A source-bounded media range supports this synthetic quota fixture.",
        }
    return {
        "case_id": f"case-{index:04d}",
        "status": "structured_candidate",
        "subvertical_id": subvertical_id,
        "company": f"Company {index}",
        "product": f"Product {index}",
        "campaign_or_motion": f"Motion {index}",
        "primary_audience": "A named buying or user segment",
        "observed_start": "2026-02-01",
        "observed_end": "2026-08-01",
        "episode_key": f"company-{index}:product-{index}:motion-{index}:window-2026",
        "mechanism_hypothesis": "A testable proof-led distribution mechanism",
        "result_summary": "Observed result is explicitly bounded to the source window",
        "resource_scope": "Labor, media, creator, tool, and production scope recorded",
        "resource_costs": resource_costs,
        "budget_quota_status": "source_bound",
        "budget_classification_evidence_receipt_sha256s": [receipt_sha],
        **{dimension: values[index] for dimension, values in buckets.items()},
        "platforms": ["linkedin", "owned_blog_newsletter"],
        "source_receipts": [
            {
                "source_url": f"https://example.com/cases/{index}",
                "source_class": "official_company",
                "access_method": "ordinary_public_page",
                "captured_at": "2026-08-04T12:00:00-04:00",
                "content_sha256": receipt_sha,
            }
        ],
        "copy_or_voice_reuse_allowed": False,
        "quota_credit": 1,
    }


def _mechanism(index: int) -> dict:
    return {
        "audit_id": f"mechanism-{index:04d}",
        "case_id": f"case-{index:04d}",
        "status": "mechanism_deep_audited",
        "problem": "A precise market and customer problem statement",
        "insight": "A falsifiable audience or buying insight with evidence",
        "strategy": "A bounded strategic choice with rejected alternatives",
        "creative_system": "A proof-led creative system rather than copied expression",
        "distribution": "A primary and reinforcing channel distribution design",
        "conversion_path": "Qualified attention through activation and business outcome",
        "resource_inputs": "Labor, media, tools, creator, and production inputs",
        "brand_advantage": "Existing brand, product, and distribution advantages",
        "competitive_alternative_explanation": "Demand or prior brand strength could explain the outcome",
        "nontransferable_conditions": "Named scale, category, market, and timing constraints",
        "evidence_receipt_sha256s": [hashlib.sha256(f"source-{index}".encode()).hexdigest()],
        "human_review_status": "approved_for_mechanism_research",
    }


def _outcome(index: int) -> dict:
    return {
        "outcome_audit_id": f"outcome-{index:04d}",
        "mechanism_audit_id": f"mechanism-{index:04d}",
        "case_id": f"case-{index:04d}",
        "status": "outcome_cross_verified",
        "business_outcome": "Qualified pipeline or retained revenue in the stated window",
        "baseline": "Pre-period baseline is recorded",
        "measurement_window": "Six-month observation window",
        "attribution_method": "descriptive_triangulation",
        "confidence_grade": "bounded_noncausal",
        "causal_claim_allowed": False,
        "independent_evidence_surfaces": [
            {"source_url": f"https://company.example/{index}", "source_class": "official_company"},
            {"source_url": f"https://media.example/{index}", "source_class": "independent_media"},
        ],
    }


def _blueprint(index: int) -> dict:
    return {
        "blueprint_id": f"blueprint-{index:04d}",
        "outcome_audit_id": f"outcome-{index:04d}",
        "case_id": f"case-{index:04d}",
        "status": "execution_case_blueprint",
        "applicability": "Named category, stage, scale, market, budget, and audience conditions",
        "proof_object": "A first-party product, data, test, or expert proof object",
        "primary_channel": "linkedin",
        "reinforcing_channel": "owned_blog_newsletter",
        "measurement_chain": "qualified attention to activation to retention to revenue",
        "kill_rule": "Stop when qualified action and retention guards fail",
        "forbidden_copy_boundary": "No source wording, voice, visual asset, or identity reuse",
        "execution_steps": ["diagnose", "create proof", "adapt natively", "measure"],
        "platform_adaptations": ["linkedin expert proof", "owned search answer asset"],
        "automatic_publish_or_spend_allowed": False,
    }


class GTMCaseEvidenceFunnelV2Tests(unittest.TestCase):
    def test_standard_freezes_81_and_16200_3240_810_405(self) -> None:
        standard = build_case_evidence_funnel_standard()
        verify_case_evidence_funnel_standard(standard)
        self.assertEqual(standard["subvertical_count"], 81)
        self.assertEqual(
            standard["global_funnel_targets"],
            {
                "structured_candidates": 16200,
                "mechanism_deep_audits": 3240,
                "outcome_cross_verifications": 810,
                "execution_case_blueprints": 405,
            },
        )
        self.assertTrue(all(sum(quota.values()) == 200 for quota in standard["marginal_quotas_per_subvertical"].values()))

    def test_empty_inputs_report_81_real_gaps(self) -> None:
        standard = build_case_evidence_funnel_standard()
        coverage = compile_case_evidence_funnel_coverage(standard, [], [], [], [])
        verify_case_evidence_funnel_coverage(coverage)
        self.assertEqual(coverage["coverage_gap_subvertical_count"], 81)
        self.assertFalse(coverage["completion_claim_allowed"])
        self.assertEqual(coverage["global_funnel_gaps"]["structured_candidates"], 16200)

    def test_one_subvertical_can_pass_only_with_full_200_40_10_5_and_all_marginals(self) -> None:
        standard = build_case_evidence_funnel_standard()
        subvertical_id = standard["subverticals"][0]["subvertical_id"]
        coverage = compile_case_evidence_funnel_coverage(
            standard,
            [_candidate(index, subvertical_id) for index in range(200)],
            [_mechanism(index) for index in range(40)],
            [_outcome(index) for index in range(10)],
            [_blueprint(index) for index in range(5)],
        )
        self.assertEqual(coverage["complete_subvertical_count"], 1)
        row = next(row for row in coverage["subvertical_coverage"] if row["subvertical_id"] == subvertical_id)
        self.assertEqual(row["status"], "complete")
        self.assertEqual(row["marginal_quota_gaps"], {})

    def test_duplicate_cross_platform_episode_and_tamper_fail_closed(self) -> None:
        standard = build_case_evidence_funnel_standard()
        subvertical_id = standard["subverticals"][0]["subvertical_id"]
        first = _candidate(0, subvertical_id)
        duplicate = _candidate(1, subvertical_id)
        duplicate["episode_key"] = first["episode_key"]
        with self.assertRaisesRegex(GTMCaseEvidenceFunnelError, "cross-platform episode"):
            compile_case_evidence_funnel_coverage(standard, [first, duplicate], [], [], [])
        tampered = copy.deepcopy(standard)
        tampered["global_funnel_targets"]["structured_candidates"] = 1
        with self.assertRaisesRegex(GTMCaseEvidenceFunnelError, "seal"):
            verify_case_evidence_funnel_standard(tampered)

    def test_all_six_cost_components_are_required_and_non_media_is_not_assumed_free(self) -> None:
        standard = build_case_evidence_funnel_standard()
        subvertical_id = standard["subverticals"][0]["subvertical_id"]
        missing = _candidate(0, subvertical_id)
        del missing["resource_costs"]["production"]
        with self.assertRaisesRegex(GTMCaseEvidenceFunnelError, "six resource cost components"):
            compile_case_evidence_funnel_coverage(standard, [missing], [], [], [])
        free_labor = _candidate(0, subvertical_id)
        free_labor["resource_costs"]["personnel"] = {
            "disclosure_status": "known_zero",
            "amount_usd": 0,
            "evidence_receipt_sha256s": [free_labor["source_receipts"][0]["content_sha256"]],
            "notes": "Founder labor was incorrectly treated as free.",
        }
        with self.assertRaisesRegex(GTMCaseEvidenceFunnelError, "automatically free"):
            compile_case_evidence_funnel_coverage(standard, [free_labor], [], [], [])

    def test_legacy_seed_has_zero_credit_until_v2_normalization(self) -> None:
        standard = build_case_evidence_funnel_standard()
        queue = compile_seed_migration_queue(
            {
                "content_sha256": "a" * 64,
                "teams": [{"team_id": "seed-1", "team_name": "Seed One", "business_model": "b2b", "promotion_status": "mechanism_distillation_ready"}],
            },
            standard,
        )
        self.assertEqual(queue["migration_item_count"], 1)
        self.assertEqual(queue["quota_credit"], 0)
        self.assertEqual(queue["items"][0]["status"], "requires_v2_normalization")

    def test_budget_evidence_gap_record_is_preserved_but_not_counted(self) -> None:
        standard = build_case_evidence_funnel_standard()
        subvertical_id = standard["subverticals"][0]["subvertical_id"]
        pending = _candidate(1, subvertical_id)
        pending["quota_credit"] = 0
        pending["budget_quota_status"] = "evidence_gap"
        pending["budget_classification_evidence_receipt_sha256s"] = []
        coverage = compile_case_evidence_funnel_coverage(standard, [pending], [], [], [])
        self.assertEqual(coverage["global_funnel_counts"]["structured_candidates"], 0)
        self.assertEqual(coverage["global_funnel_gaps"]["structured_candidates"], 16_200)


if __name__ == "__main__":
    unittest.main()
