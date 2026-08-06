from __future__ import annotations

import copy
import unittest

from prooflaunch_remix.gtm_mechanism_review_queue_v2 import (
    GTMMechanismReviewQueueError,
    compile_mechanism_review_queue,
    promote_approved_mechanisms,
    verify_mechanism_review_queue,
)


FIELDS = {
    "problem": "A sufficiently detailed problem statement for the target category and buying situation.",
    "insight": "A falsifiable audience insight grounded in the candidate source and bounded context.",
    "strategy": "A bounded strategic choice with a clear mechanism and a rejected generic alternative.",
    "creative_system": "A proof-led recurring creative system that does not copy source expression or identity.",
    "distribution": "A primary and reinforcing channel design with explicit platform-native adaptation.",
    "conversion_path": "Qualified attention through proof consumption, activation, retention, and business outcome.",
    "resource_inputs": "Labor, media, creator, tool, production, operational, and opportunity costs are explicit.",
    "brand_advantage": "Existing product, brand, distribution, trust, or community advantages are preserved.",
    "competitive_alternative_explanation": "Demand, timing, product quality, funding, or prior brand strength could explain the result.",
    "nontransferable_conditions": "Scale, category, market, timing, regulation, and operational boundaries remain explicit.",
}


class GTMMechanismReviewQueueV2Tests(unittest.TestCase):
    def _candidates(self) -> dict:
        return {"content_sha256": "a" * 64, "candidates": [{"case_id": "case-1", "source_receipts": [{"content_sha256": "b" * 64}]}]}

    def test_ai_draft_has_zero_credit_until_named_hash_bound_review(self) -> None:
        queue = compile_mechanism_review_queue(self._candidates(), [{"case_id": "case-1", **FIELDS}])
        verify_mechanism_review_queue(queue)
        self.assertEqual(queue["mechanism_quota_credit"], 0)
        self.assertEqual(promote_approved_mechanisms(queue, [])["promoted_mechanism_count"], 0)
        item = queue["items"][0]
        promoted = promote_approved_mechanisms(queue, [{
            "review_item_id": item["review_item_id"], "draft_sha256": item["draft_sha256"],
            "verdict": "approved_for_mechanism_research", "reviewer_name": "Named Reviewer",
            "source_receipts_inspected": True, "reviewed_at": "2026-08-04T14:00:00-04:00",
        }])
        self.assertEqual(promoted["promoted_mechanism_count"], 1)
        self.assertEqual(promoted["mechanism_audits"][0]["human_review_status"], "approved_for_mechanism_research")

    def test_wrong_hash_or_queue_tamper_fails(self) -> None:
        queue = compile_mechanism_review_queue(self._candidates(), [{"case_id": "case-1", **FIELDS}])
        with self.assertRaisesRegex(GTMMechanismReviewQueueError, "hash-bound"):
            promote_approved_mechanisms(queue, [{
                "review_item_id": "review:case-1", "draft_sha256": "0" * 64,
                "verdict": "approved_for_mechanism_research", "reviewer_name": "Named Reviewer", "source_receipts_inspected": True,
            }])
        tampered = copy.deepcopy(queue)
        tampered["items"][0]["quota_credit"] = 1
        with self.assertRaisesRegex(GTMMechanismReviewQueueError, "seal"):
            verify_mechanism_review_queue(tampered)


if __name__ == "__main__":
    unittest.main()
