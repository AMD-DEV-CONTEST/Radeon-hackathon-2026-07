from __future__ import annotations

import json
import unittest
from pathlib import Path

from prooflaunch_remix.gtm_platform_craft_review import (
    DIMENSIONS,
    HUMAN_ATTESTATION,
    aggregate_platform_craft_reviews,
    build_platform_craft_review_bundle,
    review_digest,
    verify_platform_craft_review_aggregate,
    verify_platform_craft_review_bundle,
)


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_ROOT = ROOT / "artifacts/gtm-last-mile-pk-v1/platform-native-challengers-v1"


class PlatformCraftReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.plan = json.loads((ARTIFACT_ROOT / "b2b-plan.json").read_text(encoding="utf-8"))
        cls.receipt = json.loads(
            (ARTIFACT_ROOT / "b2b-publication-repaired-receipt.json").read_text(
                encoding="utf-8"
            )
        )
        cls.audit = json.loads(
            (ROOT / "evidence/v10/gtm-platform-native-publication-audit-v2.json").read_text(
                encoding="utf-8"
            )
        )

    def bundle(self) -> dict[str, dict]:
        return build_platform_craft_review_bundle(
            plan=self.plan,
            receipt=self.receipt,
            publication_audit=self.audit,
            randomization_secret="platform-craft-test-secret-00000000000000000000",
        )

    def test_builds_thirteen_by_five_empty_source_hidden_matrix(self) -> None:
        bundle = self.bundle()
        public = bundle["public_packet"]
        private = bundle["private_mapping"]
        verify_platform_craft_review_bundle(public, private)
        self.assertEqual(public["artifact_count"], 13)
        self.assertEqual(public["reviewer_count"], 5)
        self.assertEqual(public["review_task_count"], 65)
        self.assertEqual(public["submitted_human_review_count"], 0)
        self.assertFalse(public["provider_identity_exposed"])
        self.assertFalse(public["model_identity_exposed"])
        self.assertFalse(public["named_product_comparison_executed"])
        self.assertNotIn("source_model", json.dumps(public, ensure_ascii=False))
        self.assertIn("source_model", private)

    def test_complete_perfect_fixture_proves_craft_only(self) -> None:
        bundle = self.bundle()
        reviews = []
        for task in bundle["public_packet"]["review_tasks"]:
            review = {
                key: task[key]
                for key in (
                    "schema",
                    "review_task_id",
                    "blind_artifact_id",
                    "artifact_sha256",
                    "reviewer_slot",
                )
            }
            review.update(
                {
                    "reviewer_pseudonym": f"human-reviewer-{task['reviewer_slot']}",
                    "human_attestation": HUMAN_ATTESTATION,
                    "conflict_disclosed": True,
                    "dimension_scores": {dimension: 5 for dimension in DIMENSIONS},
                    "directly_publishable": True,
                    "major_rework": False,
                    "blocking_defect": False,
                    "blocking_defect_reason": "",
                    "rationale": "The platform treatment is specific, restrained, evidence-bound, and ready without substantive editing.",
                    "reviewed_at": "2026-08-03T12:00:00-04:00",
                }
            )
            review["review_content_sha256"] = review_digest(review)
            reviews.append(review)
        aggregate = aggregate_platform_craft_reviews(
            public_packet=bundle["public_packet"],
            private_mapping=bundle["private_mapping"],
            reviews=reviews,
        )
        verify_platform_craft_review_aggregate(aggregate)
        self.assertTrue(aggregate["review_complete"])
        self.assertTrue(aggregate["all_thirteen_craft_gates_passed"])
        self.assertFalse(aggregate["four_a_claim_eligible"])
        self.assertFalse(aggregate["top1_claim_eligible"])
        self.assertFalse(aggregate["production_effect_observed"])

    def test_empty_reviews_never_impute_a_craft_pass(self) -> None:
        bundle = self.bundle()
        aggregate = aggregate_platform_craft_reviews(
            public_packet=bundle["public_packet"],
            private_mapping=bundle["private_mapping"],
            reviews=[],
        )
        self.assertFalse(aggregate["review_complete"])
        self.assertEqual(aggregate["craft_gate_passed_count"], 0)
        self.assertFalse(aggregate["all_thirteen_craft_gates_passed"])


if __name__ == "__main__":
    unittest.main()
