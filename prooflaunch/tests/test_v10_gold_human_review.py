from __future__ import annotations

import json
import unittest
from pathlib import Path

from prooflaunch_remix.v10_gold_human_review import (
    ATTESTATION,
    EXPECTED_REVIEW_COUNT,
    RUBRIC_DIMENSIONS,
    aggregate_completed_reviews,
    review_digest,
)


ROOT = Path(__file__).resolve().parents[1]


class GoldHumanReviewProtocolTests(unittest.TestCase):
    def test_packet_has_exact_blind_five_reviewer_coverage_without_fake_scores(self) -> None:
        root = ROOT / "data/v10_gold_human_review"
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        cases = [json.loads(line) for line in (root / "blind-cases.jsonl").read_text(encoding="utf-8").splitlines() if line]
        assignments = [json.loads(line) for line in (root / "assignments.jsonl").read_text(encoding="utf-8").splitlines() if line]
        self.assertEqual(manifest["case_count"], 450)
        self.assertEqual(manifest["brief_case_count"], 300)
        self.assertEqual(manifest["campaign_case_count"], 150)
        self.assertEqual(manifest["reviewer_slot_count"], 5)
        self.assertEqual(manifest["assignment_count"], EXPECTED_REVIEW_COUNT)
        self.assertEqual(len(cases), 450)
        self.assertEqual(len(assignments), EXPECTED_REVIEW_COUNT)
        self.assertFalse(any(case["source_provider_names_exposed"] for case in cases))
        self.assertFalse(any(case["source_urls_exposed"] for case in cases))
        for slot in range(1, 6):
            rows = [json.loads(line) for line in (root / f"review-templates/reviewer-{slot:02d}.jsonl").read_text(encoding="utf-8").splitlines() if line]
            self.assertEqual(len(rows), 450)
            self.assertTrue(all(set(row["scores"]) == set(RUBRIC_DIMENSIONS) for row in rows))
            self.assertTrue(all(all(value is None for value in row["scores"].values()) for row in rows))
        self.assertEqual(manifest["human_reviews_observed"], 0)
        self.assertIsNone(manifest["mean_score_observed"])
        self.assertFalse(manifest["promotion_passed"])

    def test_empty_review_directory_cannot_claim_five_people_or_4_7(self) -> None:
        report = json.loads(
            (ROOT / "evidence/v10/gold-five-human-review-gate.json").read_text(encoding="utf-8")
        )
        self.assertEqual(report["status"], "not_observed_incomplete_human_review")
        self.assertEqual(report["submitted_review_count"], 0)
        self.assertFalse(report["review_set_complete"])
        self.assertIsNone(report["mean_score"])
        self.assertFalse(report["human_review_claim_allowed"])
        self.assertFalse(report["gold_mean_4_7_claim_allowed"])

    def test_complete_high_quality_fixture_passes_without_loosening_real_gate(self) -> None:
        cases = [
            {"case_id": "case-a", "case_sha256": "a" * 64},
            {"case_id": "case-b", "case_sha256": "b" * 64},
        ]
        reviews = []
        for slot in range(1, 6):
            for case in cases:
                row = {
                    "reviewer_slot": slot,
                    "reviewer_pseudonym": f"human-{slot}",
                    "reviewer_attestation": ATTESTATION,
                    "reviewed_at": "2026-07-31T12:00:00Z",
                    "case_id": case["case_id"],
                    "case_sha256": case["case_sha256"],
                    "scores": {dimension: 5 for dimension in RUBRIC_DIMENSIONS},
                    "strengths": "Evidence, strategy, and execution are unusually coherent.",
                    "required_rework": "none",
                    "publishable": True,
                    "review_content_sha256": None,
                }
                row["review_content_sha256"] = review_digest(row)
                reviews.append(row)
        result = aggregate_completed_reviews(cases, reviews)
        # The production gate still requires all 450 cases / 2,250 reviews.
        self.assertEqual(result["submitted_review_count"], 10)
        self.assertFalse(result["review_set_complete"])
        self.assertFalse(result["promotion_passed"])


if __name__ == "__main__":
    unittest.main()
