from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.export_gtm_codex_lighthouse_human_review_kit import export
from prooflaunch_remix.gtm_codex_lighthouse_human_review import (
    ATTESTATION,
    DIMENSIONS,
    KIT_SCHEMA,
    REVIEW_SCHEMA,
    LighthouseHumanReviewError,
    aggregate_reviews,
    digest,
    verify_aggregate,
)


class CodexLighthouseHumanReviewTests(unittest.TestCase):
    def _kit(self, root: Path) -> tuple[Path, list[dict[str, object]]]:
        kit = root / "kit"
        export(kit)
        mapping = json.loads((kit / "private/blind-case-mapping.json").read_text(encoding="utf-8"))
        return kit, mapping["rows"]

    @staticmethod
    def _review(slot: int, reviewer: str, rows: list[dict[str, object]]) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema": REVIEW_SCHEMA,
            "kit_schema": KIT_SCHEMA,
            "reviewer_slot": slot,
            "reviewer_pseudonym": reviewer,
            "human_attestation": ATTESTATION,
            "independent_attestation": True,
            "conflict_disclosed": True,
            "reviewed_at": f"2026-08-03T1{slot}:00:00Z",
            "reviews": [
                {
                    "blind_case_id": row["blind_case_id"],
                    "candidate_content_sha256": row["candidate_content_sha256"],
                    "scores": {dimension: 5 for dimension in DIMENSIONS},
                    "directly_publishable": True,
                    "major_rework": False,
                    "blocking_defect": "none",
                    "rationale": "This case makes a coherent strategic choice and carries it through the complete platform execution.",
                    "strongest_element": "The platform-specific hook and evidence boundary reinforce one another.",
                    "first_repair": "No repair recommended before the separate legal and brand approval gates.",
                }
                for row in rows
            ],
        }
        payload["review_payload_sha256"] = digest(payload)
        return payload

    def test_empty_directory_stays_truthfully_incomplete(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            kit, _ = self._kit(Path(directory))
            aggregate = aggregate_reviews(kit, [])
            verify_aggregate(aggregate)
            self.assertEqual(aggregate["status"], "awaiting_40_human_reviews")
            self.assertEqual(aggregate["submitted_human_review_count"], 0)
            self.assertEqual(aggregate["qualified_candidate_count"], 0)
            self.assertFalse(aggregate["four_a_claim_eligible"])

    def test_five_distinct_complete_reviews_pass_development_eval_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            kit, rows = self._kit(Path(directory))
            reviews = [self._review(slot, f"human-reviewer-{slot}", rows) for slot in range(1, 6)]
            aggregate = aggregate_reviews(kit, reviews)
            verify_aggregate(aggregate)
            self.assertTrue(aggregate["human_review_set_complete"])
            self.assertEqual(aggregate["submitted_human_review_count"], 40)
            self.assertEqual(aggregate["qualified_candidate_count"], 8)
            self.assertTrue(aggregate["all_candidates_passed_human_development_eval"])
            self.assertEqual(aggregate["named_product_pk_completed_count"], 0)
            self.assertEqual(aggregate["production_effect_observed_count"], 0)
            self.assertEqual(aggregate["release_authorized_count"], 0)
            self.assertFalse(aggregate["four_a_claim_eligible"])

    def test_tamper_and_duplicate_reviewer_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            kit, rows = self._kit(Path(directory))
            tampered = self._review(1, "human-reviewer-1", rows)
            tampered["reviews"][0]["scores"]["originality"] = 1
            with self.assertRaisesRegex(LighthouseHumanReviewError, "seal"):
                aggregate_reviews(kit, [tampered])

            first = self._review(1, "same-human", rows)
            second = self._review(2, "same-human", rows)
            with self.assertRaisesRegex(LighthouseHumanReviewError, "same reviewer"):
                aggregate_reviews(kit, [first, second])


if __name__ == "__main__":
    unittest.main()
