from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from prooflaunch_remix.gtm_first50_output_review import (
    FAILURE_BUCKETS,
    HUMAN_ATTESTATION,
    First50OutputReviewError,
    compile_first50_level1_seed_manifest,
    compile_first50_codex_prereview,
    compile_first50_output_review_queue,
    compile_named_human_read_receipt,
    verify_first50_level1_seed_manifest,
    verify_first50_codex_prereview,
    verify_first50_output_review_queue,
    verify_named_human_read_receipt,
)


ROOT = Path(__file__).resolve().parents[1]
PORTFOLIO = ROOT / "evidence/v10/gtm-codex-lighthouse-portfolio-v1.json"
QUALITY = ROOT / "evidence/v10/gtm-codex-lighthouse-quality-audit-v1.json"


class First50OutputReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.portfolio = json.loads(PORTFOLIO.read_text(encoding="utf-8"))
        cls.quality = json.loads(QUALITY.read_text(encoding="utf-8"))
        cls.queue = compile_first50_output_review_queue(cls.portfolio, cls.quality)

    def test_queue_has_fifty_distinct_real_outputs_balanced_b2b_b2c(self) -> None:
        verify_first50_output_review_queue(
            self.queue,
            portfolio=self.portfolio,
            quality_portfolio=self.quality,
        )
        self.assertEqual(self.queue["output_count"], 50)
        self.assertEqual(self.queue["business_model_counts"], {"b2b": 25, "b2c": 25})
        self.assertEqual(self.queue["machine_preflight_pass_count"], 50)
        self.assertEqual(self.queue["named_human_read_count"], 0)
        self.assertFalse(self.queue["t073_complete"])
        self.assertEqual(len({row["artifact_sha256"] for row in self.queue["outputs"]}), 50)

    def test_level1_seed_manifest_prepares_50_per_bucket_without_ci_authority(self) -> None:
        manifest = compile_first50_level1_seed_manifest(self.queue)
        verify_first50_level1_seed_manifest(manifest, queue=self.queue)
        self.assertEqual(manifest["seed_case_count"], 500)
        self.assertEqual(manifest["bucket_case_counts"], {key: 50 for key in FAILURE_BUCKETS})
        self.assertEqual(manifest["human_validated_bucket_count"], 0)
        self.assertEqual(manifest["ci_admitted_case_count"], 0)
        self.assertFalse(manifest["t074_complete"])

    def test_codex_prereview_locates_eight_quality_patterns_without_human_authority(self) -> None:
        prereview = compile_first50_codex_prereview(self.queue)
        verify_first50_codex_prereview(prereview, queue=self.queue)
        self.assertEqual(prereview["finding_count"], 50)
        self.assertEqual(prereview["observed_primary_bucket_count"], 8)
        self.assertEqual(prereview["named_human_read_count"], 0)
        self.assertFalse(prereview["t073_complete"])
        self.assertTrue(all(row["evidence_spans"] for row in prereview["findings"]))

    def test_codex_prereview_cannot_be_promoted_by_editing_counts(self) -> None:
        prereview = compile_first50_codex_prereview(self.queue)
        prereview["named_human_read_count"] = 50
        prereview["t073_complete"] = True
        with self.assertRaises(First50OutputReviewError):
            verify_first50_codex_prereview(prereview, queue=self.queue)

    def test_named_human_receipt_requires_all_fifty_located_reviews(self) -> None:
        bucket_ids = list(FAILURE_BUCKETS)
        reviews = []
        for index, row in enumerate(self.queue["outputs"]):
            reviews.append(
                {
                    "output_id": row["output_id"],
                    "direct_publishable": index % 4 != 0,
                    "major_rework": index % 4 == 0,
                    "blocking_defect": False,
                    "failure_bucket": bucket_ids[index % len(bucket_ids)],
                    "evidence_span": "located field: hook and proof",
                    "written_reason": "The located field provides enough detail for an independent editorial judgment.",
                }
            )
        receipt = compile_named_human_read_receipt(
            self.queue,
            {
                "reviewer_name": "Alexandra Rivera",
                "reviewer_email": "alexandra.rivera@agency.invalid",
                "attestation": HUMAN_ATTESTATION,
                "reviews": reviews,
            },
        )
        verify_named_human_read_receipt(receipt, queue=self.queue)
        self.assertEqual(receipt["review_count"], 50)
        self.assertEqual(receipt["observed_failure_bucket_count"], 10)
        self.assertTrue(receipt["t073_complete"])

    def test_digest_and_human_authority_tampering_fail_closed(self) -> None:
        tampered = copy.deepcopy(self.queue)
        tampered["named_human_read_count"] = 50
        with self.assertRaises(First50OutputReviewError):
            verify_first50_output_review_queue(tampered)
        submission = {
            "reviewer_name": "synthetic reviewer",
            "reviewer_email": "reviewer@prooflaunch.local",
            "attestation": HUMAN_ATTESTATION,
            "reviews": [],
        }
        with self.assertRaises(First50OutputReviewError):
            compile_named_human_read_receipt(self.queue, submission)


if __name__ == "__main__":
    unittest.main()
