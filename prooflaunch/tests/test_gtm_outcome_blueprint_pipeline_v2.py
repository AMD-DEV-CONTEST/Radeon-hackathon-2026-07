from __future__ import annotations

import unittest

from prooflaunch_remix.gtm_outcome_blueprint_pipeline_v2 import (
    GTMOutcomeBlueprintPipelineError,
    compile_blueprint_review_queue,
    compile_mechanism_family_index,
    compile_outcome_review_queue,
    promote_blueprint_reviews,
    promote_outcome_reviews,
    verify_blueprint_review_queue,
    verify_mechanism_family_index,
    verify_outcome_review_queue,
)


H = "a" * 64


def candidate(index: int) -> dict:
    return {
        "case_id": f"case-{index}", "subvertical_id": "b2b.test.example",
        "company_scale": "small" if index % 2 else "mid_market",
        "budget_tier": "low_budget" if index % 2 else "capital_efficient",
        "lifecycle_state": "launch" if index % 2 else "growth",
        "outcome_type": "recent_breakout" if index % 2 else "durable_repeat",
    }


def mechanism(index: int) -> dict:
    return {"audit_id": f"mechanism:{index}", "case_id": f"case-{index}", "status": "mechanism_deep_audited", "human_review_status": "approved_for_mechanism_research"}


def outcome_draft(index: int) -> dict:
    return {
        "case_id": f"case-{index}", "mechanism_audit_id": f"mechanism:{index}",
        "outcome_category": "revenue", "business_outcome": "Revenue increased during the measured commercial window.",
        "baseline": "$1M baseline", "measurement_window": "six months", "attribution_method": "descriptive_multi_source",
        "confidence_grade": "moderate", "causal_claim_allowed": False,
        "independent_evidence_surfaces": [
            {"source_url": f"https://company{index}.example/results", "source_class": "official_company", "content_sha256": H, "claim_scope": "first-party reported revenue result"},
            {"source_url": f"https://media{index}.example/report", "source_class": "independent_media", "content_sha256": H, "claim_scope": "independent report of the result"},
        ],
    }


def blueprint_draft(index: int) -> dict:
    return {
        "case_id": f"case-{index}", "outcome_audit_id": f"outcome:case-{index}",
        "applicability": "Use only when the same problem, resources and audience evidence are present.",
        "proof_object": "A first-party operational proof with independently checked outcome evidence.",
        "primary_channel": "LinkedIn document post for the named buying committee.",
        "reinforcing_channel": "Consent-bound email follow-up for evidence consumers.",
        "measurement_chain": "qualified attention to proof consumption to qualified pipeline to revenue",
        "kill_rule": "Stop after the preregistered window if qualified proof consumption does not improve.",
        "forbidden_copy_boundary": "Do not reuse source wording, brand voice, artwork, identity, or unsupported outcome claims.",
        "execution_steps": ["diagnose", "bind proof", "adapt channels", "review", "measure"],
        "platform_adaptations": ["LinkedIn document sequence", "consent-bound email evidence digest"],
        "automatic_publish_or_spend_allowed": False,
    }


class GTMOutcomeBlueprintPipelineV2Tests(unittest.TestCase):
    def test_outcome_queue_caps_ten_and_requires_independent_surfaces(self) -> None:
        candidates = [candidate(i) for i in range(12)]
        mechanisms = [mechanism(i) for i in range(12)]
        drafts = [outcome_draft(i) for i in range(12)]
        queue = compile_outcome_review_queue(candidates, mechanisms, drafts)
        verify_outcome_review_queue(queue)
        self.assertEqual(queue["selected_review_item_count"], 10)
        self.assertTrue(all(row["quota_credit"] == 0 for row in queue["items"]))
        bad = outcome_draft(0)
        bad["independent_evidence_surfaces"][1]["source_url"] = "https://company0.example/other"
        with self.assertRaises(GTMOutcomeBlueprintPipelineError):
            compile_outcome_review_queue([candidate(0)], [mechanism(0)], [bad])

    def test_named_review_promotes_outcome(self) -> None:
        queue = compile_outcome_review_queue([candidate(0)], [mechanism(0)], [outcome_draft(0)])
        item = queue["items"][0]
        promoted = promote_outcome_reviews(queue, [{"review_item_id": item["review_item_id"], "verdict": "approved_for_outcome_research", "reviewer_name": "Riley Chen", "draft_sha256": item["draft_sha256"], "all_evidence_surfaces_inspected": True, "reviewed_at": "2026-08-05T00:00:00Z"}])
        self.assertEqual(promoted["promoted_outcome_count"], 1)

    def test_five_blueprints_require_diversity_and_human_review(self) -> None:
        candidates = [candidate(i) for i in range(5)]
        outcomes = [{"outcome_audit_id": f"outcome:case-{i}", "case_id": f"case-{i}", "status": "outcome_cross_verified"} for i in range(5)]
        queue = compile_blueprint_review_queue(candidates, outcomes, [blueprint_draft(i) for i in range(5)])
        verify_blueprint_review_queue(queue)
        self.assertEqual(queue["subvertical_summaries"][0]["status"], "ready_for_named_human_blueprint_review")
        reviews = [{"review_item_id": row["review_item_id"], "verdict": "approved_execution_blueprint", "reviewer_name": "Morgan Lee", "draft_sha256": row["draft_sha256"], "lineage_and_boundaries_inspected": True, "reviewed_at": "2026-08-05T00:00:00Z"} for row in queue["items"]]
        promoted = promote_blueprint_reviews(queue, reviews)
        self.assertEqual(promoted["promoted_blueprint_count"], 5)

    def test_blueprints_cluster_into_diagnostic_families_not_formulas(self) -> None:
        blueprints = [{"blueprint_id": f"blueprint:case-{i}"} for i in range(5)]
        assignments = [{
            "family_id": "proof-led-demand", "blueprint_ids": [row["blueprint_id"] for row in blueprints],
            "diagnostic_signals": ["high trust threshold", "inspectable proof exists", "buying committee needs shared evidence"],
            "exclusion_signals": ["no proof object", "regulated claim cannot be substantiated"],
            "invariant_principles": ["show evidence", "preserve claim boundary"],
            "adaptable_variables": ["channel", "format", "cadence", "role language"],
            "forbidden_copying_rule": "Never reproduce source wording, identity, artwork, or fixed step order.",
        }]
        index = compile_mechanism_family_index(blueprints, assignments)
        verify_mechanism_family_index(index)
        self.assertEqual(index["fixed_formula_count"], 0)


if __name__ == "__main__":
    unittest.main()
