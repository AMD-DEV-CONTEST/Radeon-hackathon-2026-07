from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from prooflaunch_remix.gtm_blind_review_service import (
    BlindReviewAuthorizationError,
    BlindReviewConflictError,
)
from prooflaunch_remix.gtm_portfolio_blind_review_service import (
    AGGREGATE_NAME,
    PRIVATE_NAME,
    PortfolioBlindReviewService,
)
from prooflaunch_remix.gtm_text_challenger_runner import (
    TEXT_BLIND_HUMAN_ATTESTATION,
    text_blind_review_digest,
)


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (
    ROOT
    / "artifacts/local-gtm-creative-benchmark-v11/portfolio-blind-review-v2"
)
TOKENS = {
    slot: f"portfolio-review-invitation-slot-{slot}-000000"
    for slot in range(1, 6)
}


class PortfolioBlindReviewServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.bundle = Path(self.temporary.name) / "portfolio"
        shutil.copytree(SOURCE, self.bundle)
        (self.bundle / PRIVATE_NAME).chmod(0o600)
        self.service = PortfolioBlindReviewService(
            self.bundle,
            reviewer_tokens=TOKENS,
        )
        self.private_mappings: dict[str, dict[str, dict[str, object]]] = {}
        for case_root in (self.bundle / "cases").iterdir():
            if not case_root.is_dir():
                continue
            payload = json.loads(
                (case_root / "text-creative-blind-review-private.json").read_text(
                    encoding="utf-8"
                )
            )
            self.private_mappings[case_root.name] = {
                row["pair_id"]: row for row in payload["pairs"]
            }

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def review(
        self,
        task: dict[str, object],
        *,
        pseudonym: str | None = None,
        prefer_territory: str = "decision_xray",
    ) -> dict[str, object]:
        case_id = str(task["portfolio_case"]["case_id"])
        mapping = self.private_mappings[case_id][str(task["pair_id"])]
        candidate_side = str(mapping["candidate_side"])
        choice = (
            candidate_side
            if mapping["candidate_territory_id"] == prefer_territory
            else "right" if candidate_side == "left" else "left"
        )
        review: dict[str, object] = {
            "schema": "ProofLaunchTextCreativeHumanBlindReviewV1",
            "review_task_id": task["review_task_id"],
            "pair_id": task["pair_id"],
            "pair_sha256": task["pair_sha256"],
            "reviewer_slot": task["reviewer_slot"],
            "reviewer_pseudonym": pseudonym
            or f"named-portfolio-human-{task['reviewer_slot']}",
            "human_attestation": TEXT_BLIND_HUMAN_ATTESTATION,
            "choice": choice,
            "reason": (
                "The selected side is clearer, more useful, and remains bound to "
                "the supplied evidence without unsupported effect claims."
            ),
            "critical_failure": False,
            "reviewed_at": "2026-08-02T12:00:00+00:00",
            "review_content_sha256": None,
        }
        review["review_content_sha256"] = text_blind_review_digest(review)
        return review

    def test_queue_exposes_54_tasks_per_slot_without_deblinding(self) -> None:
        status = self.service.status()
        self.assertEqual(status["case_count"], 9)
        self.assertEqual(status["pair_count"], 54)
        self.assertEqual(status["expected_review_count"], 270)
        self.assertEqual(status["submitted_review_count"], 0)
        self.assertFalse(status["human_preference_observed"])
        self.assertTrue(
            all(row["recommended_territory_id"] is None for row in status["cases"])
        )
        with self.assertRaises(BlindReviewAuthorizationError):
            self.service.tasks_for_slot(1, reviewer_token="wrong-token")
        assignment = self.service.tasks_for_slot(1, reviewer_token=TOKENS[1])
        self.assertEqual(assignment["task_count"], 54)
        serialized = json.dumps(assignment, sort_keys=True)
        self.assertNotIn("candidate_side", serialized)
        self.assertNotIn("candidate_territory_id", serialized)
        self.assertFalse(assignment["candidate_identity_exposed"])
        self.assertFalse(assignment["provider_identity_exposed"])

    def test_submission_is_global_identity_bound_and_idempotent(self) -> None:
        tasks = self.service.tasks_for_slot(1, reviewer_token=TOKENS[1])["tasks"]
        first = self.review(tasks[0])
        created = self.service.submit(first, reviewer_token=TOKENS[1])
        replay = self.service.submit(first, reviewer_token=TOKENS[1])
        self.assertFalse(created["idempotent_replay"])
        self.assertTrue(replay["idempotent_replay"])
        self.assertEqual(created["submitted_review_count"], 1)
        other_case = next(
            task
            for task in tasks[1:]
            if task["portfolio_case"]["case_id"]
            != tasks[0]["portfolio_case"]["case_id"]
        )
        drift = self.review(other_case, pseudonym="different-human")
        with self.assertRaisesRegex(BlindReviewConflictError, "drifted"):
            self.service.submit(drift, reviewer_token=TOKENS[1])

    def test_manifest_tamper_is_rejected(self) -> None:
        public_path = self.bundle / "portfolio-blind-review-public.json"
        payload = json.loads(public_path.read_text(encoding="utf-8"))
        payload["pair_count"] = 47
        public_path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "digest"):
            PortfolioBlindReviewService(self.bundle, reviewer_tokens=TOKENS)

    def test_all_270_reviews_deblind_once_and_survive_restart(self) -> None:
        for slot in range(1, 6):
            assignment = self.service.tasks_for_slot(
                slot, reviewer_token=TOKENS[slot]
            )
            for task in assignment["tasks"]:
                self.service.submit(
                    self.review(task), reviewer_token=TOKENS[slot]
                )
        status = self.service.status()
        self.assertEqual(status["submitted_review_count"], 270)
        self.assertTrue(status["review_complete"])
        self.assertTrue(status["human_preference_observed"])
        self.assertTrue(status["portfolio_promotion_passed"])
        self.assertTrue(
            all(
                row["recommended_territory_id"] == "decision_xray"
                for row in status["cases"]
            )
        )
        aggregate = self.service.aggregate()
        self.assertEqual(aggregate["recommendation_counts"]["all"], 9)
        self.assertEqual(aggregate["recommendation_counts"]["b2b"], 5)
        self.assertEqual(aggregate["recommendation_counts"]["b2c"], 4)
        self.assertEqual(aggregate["recommendation_counts"]["zero_budget"], 4)
        self.assertEqual(aggregate["recommendation_counts"]["high_regulation"], 2)
        self.assertTrue((self.bundle / AGGREGATE_NAME).is_file())
        self.assertFalse(aggregate["winner_selected"])
        self.assertFalse(aggregate["external_publish_executed"])

        recovered = PortfolioBlindReviewService(
            self.bundle, reviewer_tokens=TOKENS
        )
        recovered_status = recovered.status()
        self.assertTrue(recovered_status["review_complete"])
        self.assertEqual(
            recovered_status["portfolio_aggregate_sha256"],
            aggregate["content_sha256"],
        )


if __name__ == "__main__":
    unittest.main()
