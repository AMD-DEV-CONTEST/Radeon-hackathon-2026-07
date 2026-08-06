from __future__ import annotations

import copy
import hashlib
import json
import stat
import unittest
from pathlib import Path

from prooflaunch_remix.gtm_text_challenger_runner import (
    TextChallengerRunError,
    verify_text_blind_review_bundle,
)


ROOT = Path(__file__).resolve().parents[1]
PORTFOLIO = (
    ROOT
    / "artifacts/local-gtm-creative-benchmark-v11/portfolio-blind-review-v2"
)
PUBLIC_PATH = PORTFOLIO / "portfolio-blind-review-public.json"
PRIVATE_PATH = PORTFOLIO / "portfolio-blind-review-private.json"
STATUS_PATH = ROOT / "evidence/v10/local-gtm-portfolio-blind-review-status.json"


def canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value: object) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


class LocalGTMPortfolioBlindReviewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.public = json.loads(PUBLIC_PATH.read_text(encoding="utf-8"))
        self.private = json.loads(PRIVATE_PATH.read_text(encoding="utf-8"))
        self.status = json.loads(STATUS_PATH.read_text(encoding="utf-8"))

    def test_portfolio_is_9_cases_54_pairs_and_270_empty_human_tasks(self) -> None:
        unsigned = dict(self.public)
        supplied = unsigned.pop("content_sha256")
        self.assertEqual(supplied, digest(unsigned))
        self.assertEqual(self.public["case_count"], 9)
        self.assertEqual(self.public["pair_count"], 54)
        self.assertEqual(self.public["reviewer_slot_count"], 5)
        self.assertEqual(self.public["expected_review_count"], 270)
        self.assertEqual(self.public["review_tasks_per_slot"], 54)
        self.assertEqual(
            self.public["coverage"],
            {
                "business_models": ["b2b", "b2c"],
                "lifecycles": ["growth", "launch", "mature", "pre_pmf"],
                "budgets": ["scaled", "small", "zero"],
                "industry_risks": ["high_regulation", "standard"],
            },
        )
        task_ids = set()
        for case in self.public["cases"]:
            case_root = PORTFOLIO / Path(case["public_packet_path"]).parent
            public_path = PORTFOLIO / case["public_packet_path"]
            private_path = case_root / "text-creative-blind-review-private.json"
            public_packet = json.loads(public_path.read_text(encoding="utf-8"))
            private_mapping = json.loads(private_path.read_text(encoding="utf-8"))
            verify_text_blind_review_bundle(public_packet, private_mapping)
            self.assertEqual(hashlib.sha256(public_path.read_bytes()).hexdigest(), case["public_packet_file_sha256"])
            self.assertEqual(public_packet["content_sha256"], case["public_packet_content_sha256"])
            self.assertEqual(case["pair_count"], 6)
            self.assertEqual(case["expected_review_count"], 30)
            self.assertEqual(case["submitted_review_count"], 0)
            self.assertFalse(case["candidate_identity_exposed"])
            self.assertFalse(case["provider_identity_exposed"])
            for task in public_packet["review_tasks"]:
                self.assertTrue(
                    all(
                        task[field] is None
                        for field in (
                            "reviewer_pseudonym",
                            "human_attestation",
                            "choice",
                            "reason",
                            "critical_failure",
                            "reviewed_at",
                            "review_content_sha256",
                        )
                    )
                )
                self.assertNotIn(task["review_task_id"], task_ids)
                task_ids.add(task["review_task_id"])
        self.assertEqual(len(task_ids), 270)
        self.assertFalse(self.public["human_preference_observed"])
        self.assertFalse(self.public["portfolio_promotion_passed"])
        self.assertFalse(self.public["automatic_scoring_executed"])
        self.assertFalse(self.public["winner_selected"])
        self.assertFalse(self.public["external_publish_executed"])

    def test_portfolio_gate_requires_cross_segment_effect_not_one_lucky_case(self) -> None:
        gate = self.public["portfolio_promotion_gate"]
        self.assertTrue(gate["all_270_reviews_required"])
        self.assertTrue(gate["all_9_case_aggregates_required"])
        self.assertEqual(gate["minimum_case_recommendations"], 7)
        self.assertEqual(gate["minimum_b2b_case_recommendations"], 4)
        self.assertEqual(gate["minimum_b2c_case_recommendations"], 3)
        self.assertEqual(gate["minimum_zero_budget_case_recommendations"], 3)
        self.assertEqual(gate["required_high_regulation_case_recommendations"], 2)
        self.assertEqual(gate["per_case_minimum_eligible_comparisons_per_territory"], 8)
        self.assertEqual(gate["per_case_minimum_preference_rate"], 0.60)
        self.assertGreater(gate["per_case_wilson_lower_95_must_exceed"], 0.50 - 1e-9)
        self.assertEqual(gate["per_case_critical_failure_count_must_equal"], 0)

    def test_private_manifest_is_hash_bound_and_not_exposed_by_public_packet(self) -> None:
        unsigned = dict(self.private)
        supplied = unsigned.pop("content_sha256")
        self.assertEqual(supplied, digest(unsigned))
        self.assertEqual(
            self.private["public_packet_content_sha256"],
            self.public["content_sha256"],
        )
        self.assertFalse(self.private["randomization_secrets_persisted"])
        self.assertFalse(self.private["private_mapping_exposed"])
        self.assertNotIn("private_mapping_path", canonical(self.public))
        self.assertEqual(
            stat.S_IMODE(PRIVATE_PATH.stat().st_mode),
            0o600,
        )

    def test_case_tamper_is_rejected_by_existing_blind_protocol(self) -> None:
        case = self.public["cases"][0]
        case_root = PORTFOLIO / Path(case["public_packet_path"]).parent
        public_packet = json.loads(
            (case_root / "text-creative-blind-review-public.json").read_text(
                encoding="utf-8"
            )
        )
        private_mapping = json.loads(
            (case_root / "text-creative-blind-review-private.json").read_text(
                encoding="utf-8"
            )
        )
        tampered = copy.deepcopy(public_packet)
        tampered["pairs"][0]["left"]["hook"] += " tampered"
        with self.assertRaises(TextChallengerRunError):
            verify_text_blind_review_bundle(tampered, private_mapping)

    def test_status_is_truthful_and_contains_no_fabricated_effect(self) -> None:
        unsigned = dict(self.status)
        supplied = unsigned.pop("content_sha256")
        self.assertEqual(supplied, digest(unsigned))
        self.assertEqual(
            self.status["status"], "awaiting_270_named_human_reviews"
        )
        self.assertEqual(self.status["submitted_review_count"], 0)
        self.assertFalse(self.status["review_complete"])
        self.assertFalse(self.status["human_preference_observed"])
        self.assertFalse(self.status["portfolio_promotion_passed"])
        self.assertFalse(self.status["winner_selected"])
        self.assertFalse(self.status["external_publish_executed"])


if __name__ == "__main__":
    unittest.main()
