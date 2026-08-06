from __future__ import annotations

import hashlib
import io
import json
import shutil
import tempfile
import unittest
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from prooflaunch_remix.campaign_pack_blind_review import (
    AGGREGATE_NAME,
    CampaignPackBlindReviewAuthorizationError,
    CampaignPackBlindReviewConflictError,
    CampaignPackBlindReviewService,
    DIMENSIONS,
    PRIVATE_NAME,
    PUBLIC_NAME,
    REVIEW_ATTESTATION,
    compile_campaign_pack_blind_review_bundle,
)


ROOT = Path(__file__).resolve().parents[1]
SOURCE_BUNDLE = ROOT / "artifacts/campaign-pack-visual-blind-review-v1"
TOKENS = {slot: f"campaign-review-token-{slot}-0123456789abcdef" for slot in range(1, 6)}


def digest(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


class CampaignPackBlindReviewTests(unittest.TestCase):
    def test_custom_candidate_pair_compiles_without_exposing_identity(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            result = compile_campaign_pack_blind_review_bundle(
                ROOT,
                Path(directory) / "review",
                seed=20260803,
                candidate_manifest_paths=(
                    ROOT / "evidence/v10/local-campaign-pack-v1/delivery-v6/campaign-pack-manifest.json",
                    ROOT / "evidence/v10/local-campaign-pack-v1/delivery-v7/campaign-pack-manifest.json",
                ),
            )
            public = json.loads(Path(result["public_path"]).read_text())
            private = json.loads(Path(result["private_path"]).read_text())
            self.assertFalse(public["candidate_identity_exposed"])
            self.assertEqual(
                set(private["private_core"]["candidates"]),
                {"campaign-pack-delivery-v6", "campaign-pack-delivery-v7"},
            )

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(dir=ROOT)
        self.bundle = Path(self.temporary.name) / "bundle"
        shutil.copytree(SOURCE_BUNDLE, self.bundle)
        reviews = self.bundle / "human-reviews"
        if reviews.exists():
            shutil.rmtree(reviews)
        aggregate = self.bundle / AGGREGATE_NAME
        if aggregate.exists():
            aggregate.unlink()
        (self.bundle / PRIVATE_NAME).chmod(0o600)
        self.service = CampaignPackBlindReviewService(
            self.bundle,
            project_root=ROOT,
            reviewer_tokens=TOKENS,
        )
        self.private = json.loads((self.bundle / PRIVATE_NAME).read_text(encoding="utf-8"))

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def review_for(
        self,
        slot: int,
        *,
        candidate_id: str = "campaign-pack-v6",
        defect: str = "none",
    ) -> dict[str, object]:
        assignment = self.service.tasks_for_slot(slot, reviewer_token=TOKENS[slot])
        task = assignment["tasks"][0]
        mapping = self.private["private_core"]["task_side_mapping"][task["review_task_id"]]
        winner = next(side for side, identity in mapping.items() if identity == candidate_id)
        review: dict[str, object] = {
            "schema": "ProofLaunchCampaignPackVisualHumanReviewV1",
            "review_task_id": task["review_task_id"],
            "pair_id": task["pair_id"],
            "pair_sha256": task["pair_sha256"],
            "reviewer_slot": slot,
            "reviewer_pseudonym": f"reviewer-{slot}",
            "human_attestation": REVIEW_ATTESTATION,
            "overall_winner": winner,
            "dimension_winners": {dimension: winner for dimension in DIMENSIONS},
            "blocking_defect_side": defect,
            "blocking_defect_reason": "" if defect == "none" else "The located proof line is materially illegible.",
            "notes": "The selected system has the clearer idea, evidence hierarchy, and cross-format campaign behavior.",
            "reviewed_at": datetime.now(timezone.utc).isoformat(),
        }
        review["review_content_sha256"] = digest(review)
        return review

    def test_compiler_seals_balanced_identity_hidden_public_and_private_packets(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            result = compile_campaign_pack_blind_review_bundle(ROOT, temporary, seed=20260802)
            public = json.loads(Path(result["public_path"]).read_text(encoding="utf-8"))
            private = json.loads(Path(result["private_path"]).read_text(encoding="utf-8"))
            self.assertEqual(public["task_count"], 5)
            self.assertEqual({row["reviewer_slot"] for row in public["review_tasks"]}, set(range(1, 6)))
            self.assertEqual(public["content_sha256"], digest({k: v for k, v in public.items() if k != "content_sha256"}))
            self.assertEqual(private["content_sha256"], digest({k: v for k, v in private.items() if k != "content_sha256"}))
            text = Path(result["public_path"]).read_text(encoding="utf-8")
            self.assertNotIn("campaign-pack-v5", text)
            self.assertNotIn("campaign-pack-v6", text)
            self.assertNotIn("openai/builtin", text)
            mappings = private["private_core"]["task_side_mapping"].values()
            v5_left = sum(row["left"] == "campaign-pack-v5" for row in mappings)
            self.assertIn(v5_left, {2, 3})
            self.assertEqual(Path(result["private_path"]).stat().st_mode & 0o077, 0)
            self.assertFalse(public["predeclared_promotion_gate"]["automatic_runtime_switch_enabled"])

    def test_assignment_auth_and_assets_are_hash_bound_without_deblinding(self) -> None:
        with self.assertRaises(CampaignPackBlindReviewAuthorizationError):
            self.service.tasks_for_slot(1, reviewer_token="wrong")
        assignment = self.service.tasks_for_slot(1, reviewer_token=TOKENS[1])
        self.assertEqual(assignment["task_count"], 1)
        self.assertFalse(assignment["candidate_identity_exposed"])
        asset = assignment["tasks"][0]["pair"]["sides"]["left"]["assets"][0]
        path, media_type, observed = self.service.asset_for_alias(asset["asset_alias"])
        self.assertTrue(path.is_file())
        self.assertEqual(media_type, "image/png")
        self.assertEqual(observed, asset["sha256"])
        with self.assertRaises(KeyError):
            self.service.asset_for_alias("asset-000000000000000000000000")

    def test_offline_kit_is_deterministic_identity_hidden_and_contains_no_token(self) -> None:
        first, first_digest, filename = self.service.offline_kit_for_slot(
            1,
            reviewer_token=TOKENS[1],
        )
        second, second_digest, _ = self.service.offline_kit_for_slot(
            1,
            reviewer_token=TOKENS[1],
        )
        self.assertEqual(first, second)
        self.assertEqual(first_digest, second_digest)
        self.assertEqual(hashlib.sha256(first).hexdigest(), first_digest)
        self.assertEqual(filename, "campaign-pack-review-slot-1.zip")
        with zipfile.ZipFile(io.BytesIO(first)) as archive:
            names = set(archive.namelist())
            self.assertEqual(
                names,
                {
                    "manifest.json",
                    "review-task.json",
                    "review.html",
                    *{
                        f"assets/{asset['asset_alias']}.png"
                        for side in ("left", "right")
                        for asset in self.service.tasks_for_slot(
                            1,
                            reviewer_token=TOKENS[1],
                        )["tasks"][0]["pair"]["sides"][side]["assets"]
                    },
                },
            )
            manifest = json.loads(archive.read("manifest.json"))
            self.assertFalse(manifest["invitation_token_included"])
            self.assertFalse(manifest["candidate_identity_exposed"])
            self.assertEqual(len(manifest["assets"]), 6)
            html = archive.read("review.html").decode("utf-8")
            task = archive.read("review-task.json").decode("utf-8")
        serialized = first.decode("latin-1", errors="ignore")
        for secret_or_identity in (
            TOKENS[1],
            "campaign-pack-v5",
            "campaign-pack-v6",
            "openai/builtin",
            "private_core",
        ):
            self.assertNotIn(secret_or_identity, serialized)
            self.assertNotIn(secret_or_identity, html)
            self.assertNotIn(secret_or_identity, task)
        self.assertIn("Download immutable review JSON", html)
        self.assertIn(REVIEW_ATTESTATION, html)

    def test_review_is_immutable_idempotent_and_aggregate_blocks_until_complete(self) -> None:
        review = self.review_for(1)
        receipt = self.service.submit(review, reviewer_token=TOKENS[1])
        self.assertFalse(receipt["idempotent"])
        duplicate = self.service.submit(review, reviewer_token=TOKENS[1])
        self.assertTrue(duplicate["idempotent"])
        changed = dict(review)
        changed["notes"] = "A different rationale cannot overwrite the already sealed independent human review record."
        changed["review_content_sha256"] = digest({k: v for k, v in changed.items() if k != "review_content_sha256"})
        with self.assertRaises(CampaignPackBlindReviewConflictError):
            self.service.submit(changed, reviewer_token=TOKENS[1])
        with self.assertRaises(CampaignPackBlindReviewConflictError):
            self.service.aggregate()

    def test_five_reviews_can_recommend_but_never_switch_publish_or_claim_four_a(self) -> None:
        for slot in range(1, 6):
            self.service.submit(self.review_for(slot), reviewer_token=TOKENS[slot])
        status = self.service.status()
        self.assertTrue(status["review_complete"])
        self.assertTrue(status["human_preference_observed"])
        self.assertTrue(status["offline_review_kit_available"])
        self.assertTrue(status["offline_review_kit_invitation_bound"])
        self.assertFalse(status["offline_review_kit_contains_invitation_token"])
        self.assertFalse(status["offline_review_kit_network_submission_enabled"])
        self.assertEqual(status["recommended_candidate_id"], "campaign-pack-v6")
        aggregate = self.service.aggregate()
        self.assertEqual(aggregate["overall_votes"]["campaign-pack-v6"], 5)
        self.assertTrue(aggregate["promotion_recommendation_eligible"])
        self.assertEqual(aggregate["recommended_candidate_id"], "campaign-pack-v6")
        self.assertFalse(aggregate["automatic_runtime_switch_enabled"])
        self.assertFalse(aggregate["automatic_publish_enabled"])
        self.assertFalse(aggregate["product_admission_passed"])
        self.assertFalse(aggregate["four_a_preference_proven"])
        self.assertFalse(aggregate["production_effect_proven"])
        self.assertTrue((self.bundle / AGGREGATE_NAME).is_file())
        self.assertEqual((self.bundle / AGGREGATE_NAME).stat().st_mode & 0o077, 0)


if __name__ == "__main__":
    unittest.main()
