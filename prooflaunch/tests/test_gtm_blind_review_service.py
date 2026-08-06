from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from prooflaunch_remix.gtm_blind_review_service import (
    AGGREGATE_NAME,
    EXECUTION_NAME,
    MULTIMODAL_ADMISSION_NAME,
    MULTIMODAL_SELECTION_ATTESTATION,
    PLAN_NAME,
    PRIVATE_NAME,
    PUBLIC_NAME,
    BlindReviewAuthorizationError,
    BlindReviewConflictError,
    BlindReviewService,
)
from prooflaunch_remix.gtm_text_challenger_runner import (
    TEXT_BLIND_HUMAN_ATTESTATION,
    text_blind_review_digest,
)


ROOT = Path(__file__).resolve().parents[1]
SOURCE_BUNDLE = ROOT / "artifacts/aug3-gtm-employee-mission-v14/local-text-challenger"


class BlindReviewServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.bundle = Path(self.temporary.name) / "bundle"
        self.bundle.mkdir()
        for name in (PUBLIC_NAME, PRIVATE_NAME, EXECUTION_NAME, PLAN_NAME):
            shutil.copyfile(SOURCE_BUNDLE / name, self.bundle / name)
        self.tokens = {slot: f"reviewer-{slot}-invitation-token-20260803" for slot in range(1, 6)}
        self.service = BlindReviewService(self.bundle, reviewer_tokens=self.tokens)
        self.public = json.loads((self.bundle / PUBLIC_NAME).read_text(encoding="utf-8"))
        private = json.loads((self.bundle / PRIVATE_NAME).read_text(encoding="utf-8"))
        self.mapping = {row["pair_id"]: row for row in private["pairs"]}

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def review(self, task, *, choose_candidate: bool) -> dict[str, object]:
        candidate_side = self.mapping[task["pair_id"]]["candidate_side"]
        choice = candidate_side if choose_candidate else ("right" if candidate_side == "left" else "left")
        review: dict[str, object] = {
            **task,
            "reviewer_pseudonym": f"named-human-{task['reviewer_slot']}",
            "human_attestation": TEXT_BLIND_HUMAN_ATTESTATION,
            "choice": choice,
            "reason": "The selected side is clearer, more useful, and remains evidence-bound.",
            "critical_failure": False,
            "reviewed_at": datetime.now(timezone.utc).isoformat(),
            "review_content_sha256": None,
        }
        review["review_content_sha256"] = text_blind_review_digest(review)
        return review

    def test_public_queue_never_exposes_private_mapping_or_candidate_side(self) -> None:
        status = self.service.status()
        self.assertEqual(status["submitted_review_count"], 0)
        self.assertEqual(status["remaining_review_count"], 30)
        self.assertFalse(status["private_mapping_exposed"])
        with self.assertRaises(BlindReviewAuthorizationError):
            self.service.tasks_for_slot(1, reviewer_token="wrong-token")
        assignment = self.service.tasks_for_slot(1, reviewer_token=self.tokens[1])
        self.assertEqual(assignment["task_count"], 6)
        serialized = json.dumps(assignment, sort_keys=True)
        self.assertNotIn("candidate_side", serialized)
        self.assertNotIn("candidate_territory_id", serialized)
        self.assertFalse(assignment["candidate_identity_exposed"])
        self.assertFalse(assignment["provider_identity_exposed"])

    def test_submission_is_token_bound_idempotent_and_identity_stable(self) -> None:
        task = next(row for row in self.public["review_tasks"] if row["reviewer_slot"] == 1)
        review = self.review(task, choose_candidate=True)
        with self.assertRaises(BlindReviewAuthorizationError):
            self.service.submit(review, reviewer_token=self.tokens[2])
        created = self.service.submit(review, reviewer_token=self.tokens[1])
        replay = self.service.submit(review, reviewer_token=self.tokens[1])
        self.assertFalse(created["idempotent_replay"])
        self.assertTrue(replay["idempotent_replay"])
        drift = dict(review)
        drift["reason"] = "A different immutable answer."
        drift["review_content_sha256"] = text_blind_review_digest(drift)
        with self.assertRaises(BlindReviewConflictError):
            self.service.submit(drift, reviewer_token=self.tokens[1])

    def test_thirty_real_contract_rows_create_recommendation_but_never_a_winner(self) -> None:
        for task in self.public["review_tasks"]:
            territory = self.mapping[task["pair_id"]]["candidate_territory_id"]
            review = self.review(task, choose_candidate=territory == "decision_xray")
            self.service.submit(
                review,
                reviewer_token=self.tokens[int(task["reviewer_slot"])],
            )
        status = self.service.status()
        self.assertTrue(status["review_complete"])
        self.assertTrue(status["human_selection_eligible"])
        self.assertEqual(status["recommended_territory_id"], "decision_xray")
        self.assertFalse(status["winner_selected"])
        self.assertFalse(status["external_publish_executed"])
        aggregate = json.loads((self.bundle / AGGREGATE_NAME).read_text(encoding="utf-8"))
        self.assertTrue(aggregate["review_complete"])
        self.assertEqual(aggregate["submitted_review_count"], 30)
        self.assertFalse(aggregate["automatic_winner_selection_enabled"])

        selection_request = {
            "aggregate_content_sha256": aggregate["content_sha256"],
            "selected_territory_id": "decision_xray",
            "reason": "The completed five-person blind gate recommends this evidence-bound territory.",
            "human_attestation": MULTIMODAL_SELECTION_ATTESTATION,
            "idempotency_key": "selection-contract-test-0001",
        }
        admission = self.service.select_multimodal_seed(
            selection_request,
            authenticated_approver="named-creative-director@example.test",
        )
        replay = self.service.select_multimodal_seed(
            selection_request,
            authenticated_approver="named-creative-director@example.test",
        )
        self.assertFalse(admission["idempotent_replay"])
        self.assertTrue(replay["idempotent_replay"])
        self.assertEqual(admission["selected_territory_id"], "decision_xray")
        self.assertTrue(admission["prompt_compilation_authorized"])
        self.assertFalse(admission["gpu_execution_authorized"])
        self.assertFalse(admission["external_publish_authorized"])
        self.assertFalse(admission["effect_claim_eligible"])
        self.assertTrue((self.bundle / MULTIMODAL_ADMISSION_NAME).is_file())
        selected_status = self.service.status()
        self.assertTrue(selected_status["winner_selected"])
        self.assertTrue(selected_status["multimodal_production_entry_created"])


if __name__ == "__main__":
    unittest.main()
