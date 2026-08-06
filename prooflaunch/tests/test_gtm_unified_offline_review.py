from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src"
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))

from prooflaunch_remix.campaign_pack_blind_review import DIMENSIONS, REVIEW_ATTESTATION
from prooflaunch_remix.gtm_unified_offline_review import (
    GENERIC_ATTESTATION,
    GENERIC_REVIEW_SCHEMA,
    VISUAL_REVIEW_SCHEMA,
    UnifiedOfflineReviewConflictError,
    UnifiedOfflineReviewError,
    UnifiedOfflineReviewService,
    sha256_json,
)

from scripts.export_gtm_unified_offline_review_kit import export


GENERIC_MAPPINGS = [
    ROOT / "artifacts/gtm-last-mile-pk-v1/internal-text-review-v3/private/role-mapping.json",
    ROOT / "artifacts/gtm-last-mile-pk-v1/multimodal-review-v5/audio/private/role-mapping.json",
    ROOT / "artifacts/gtm-last-mile-pk-v1/multimodal-review-v5/video/private/role-mapping.json",
]
VISUAL_MAPPING = ROOT / "artifacts/campaign-pack-visual-blind-review-v1/campaign-pack-blind-review-private.json"
UNIFIED = ROOT / "artifacts/gtm-last-mile-pk-v1/multimodal-review-v5/unified-last-mile-review.json"


class GTMUnifiedOfflineReviewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(dir=ROOT)
        self.temp = Path(self.temporary.name)
        self.kit = self.temp / "kit"
        export(self.kit)
        self.manifest = json.loads((self.kit / "manifest.json").read_text(encoding="utf-8"))
        self.generic_mappings = {}
        for path in GENERIC_MAPPINGS:
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.generic_mappings.update({row["pair_id"]: row for row in payload["pairs"]})
        self.visual_mapping = json.loads(VISUAL_MAPPING.read_text(encoding="utf-8"))["private_core"]["task_side_mapping"]
        self.service = UnifiedOfflineReviewService(
            kit_root=self.kit,
            store_root=self.temp / "store",
            generic_mapping_paths=GENERIC_MAPPINGS,
            visual_private_path=VISUAL_MAPPING,
            unified_review_path=UNIFIED,
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _files(self, slot: int, *, defect_candidate: bool = False, pseudonym: str | None = None) -> tuple[Path, Path]:
        reviewer = pseudonym or f"qualified-reviewer-{slot}"
        rows = []
        for binding in self.manifest["generic_pairs"]:
            candidate_side = self.generic_mappings[binding["pair_id"]]["candidate_side"]
            other_side = "right" if candidate_side == "left" else "left"
            row = {
                "schema": GENERIC_REVIEW_SCHEMA,
                "reviewer_slot": slot,
                "pair_id": binding["pair_id"],
                "pair_sha256": binding["pair_sha256"],
                "choice": candidate_side,
                "reviewer_pseudonym": reviewer,
                "human_attestation": GENERIC_ATTESTATION,
                "independent_attestation": True,
                "conflict_disclosed": True,
                "reviewed_at": "2026-08-03T12:00:00+00:00",
                "left_directly_publishable": candidate_side == "left",
                "right_directly_publishable": candidate_side == "right",
                "left_major_rework": False,
                "right_major_rework": False,
                "blocking_defect_side": candidate_side if defect_candidate else "none",
                "blocking_defect_reason": "Located factual production blocker." if defect_candidate else "",
                "rationale": f"Candidate side {candidate_side} is more decision-ready than {other_side}.",
            }
            row["review_content_sha256"] = sha256_json(row)
            rows.append(row)
        task = next(row for row in self.manifest["visual_tasks"] if row["reviewer_slot"] == slot)
        candidate_side = next(
            side for side, candidate in self.visual_mapping[task["review_task_id"]].items()
            if candidate == "campaign-pack-v6"
        )
        visual = {
            "schema": VISUAL_REVIEW_SCHEMA,
            "review_task_id": task["review_task_id"],
            "pair_id": task["pair_id"],
            "pair_sha256": task["pair_sha256"],
            "reviewer_slot": slot,
            "reviewer_pseudonym": reviewer,
            "human_attestation": REVIEW_ATTESTATION,
            "overall_winner": candidate_side,
            "dimension_winners": {dimension: candidate_side for dimension in DIMENSIONS},
            "left_directly_publishable": candidate_side == "left",
            "right_directly_publishable": candidate_side == "right",
            "left_major_rework": False,
            "right_major_rework": False,
            "blocking_defect_side": candidate_side if defect_candidate else "none",
            "blocking_defect_reason": "Located factual production blocker." if defect_candidate else "",
            "notes": "The candidate system has stronger hierarchy, proof, and execution readiness.",
            "reviewed_at": "2026-08-03T12:00:00+00:00",
        }
        visual["review_content_sha256"] = sha256_json(visual)
        generic_path = self.temp / f"reviewer-{slot:02d}-generic.jsonl"
        generic_path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
        visual_path = self.temp / f"reviewer-{slot:02d}-visual.json"
        visual_path.write_text(json.dumps(visual, sort_keys=True) + "\n", encoding="utf-8")
        return generic_path, visual_path

    def test_five_complete_unanimous_bundles_yield_recommendation_only(self) -> None:
        for slot in range(1, 6):
            generic, visual = self._files(slot)
            receipt = self.service.import_reviewer(generic_reviews_path=generic, visual_review_path=visual)
        self.assertTrue(receipt["review_complete"])
        aggregate = self.service.aggregate()
        self.assertEqual(aggregate["submitted_human_review_count"], 80)
        self.assertEqual(len(aggregate["pair_results"]), 16)
        self.assertEqual(len(aggregate["lane_results"]), 14)
        self.assertTrue(aggregate["promotion_recommendation_eligible"])
        self.assertTrue(all(row["candidate_preference_wilson_lower_95"] > 0.5 for row in aggregate["pair_results"]))
        self.assertFalse(aggregate["automatic_runtime_switch_enabled"])
        self.assertFalse(aggregate["automatic_publish_enabled"])
        self.assertFalse(aggregate["four_a_quality_proven"])
        self.assertFalse(aggregate["top_product_effect_parity_proven"])

    def test_incomplete_reviews_cannot_aggregate(self) -> None:
        generic, visual = self._files(1)
        receipt = self.service.import_reviewer(generic_reviews_path=generic, visual_review_path=visual)
        self.assertEqual(receipt["submitted_human_review_count"], 16)
        self.assertFalse(receipt["review_complete"])
        with self.assertRaises(UnifiedOfflineReviewConflictError):
            self.service.aggregate()

    def test_digest_tamper_and_identity_drift_are_blocked(self) -> None:
        generic, visual = self._files(1)
        rows = [json.loads(line) for line in generic.read_text(encoding="utf-8").splitlines()]
        rows[0]["choice"] = "abstain"
        generic.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
        with self.assertRaises(UnifiedOfflineReviewError):
            self.service.import_reviewer(generic_reviews_path=generic, visual_review_path=visual)
        generic, visual = self._files(1)
        payload = json.loads(visual.read_text(encoding="utf-8"))
        payload["reviewer_pseudonym"] = "different-human"
        unsigned = dict(payload)
        unsigned.pop("review_content_sha256")
        payload["review_content_sha256"] = sha256_json(unsigned)
        visual.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaises(UnifiedOfflineReviewConflictError):
            self.service.import_reviewer(generic_reviews_path=generic, visual_review_path=visual)

    def test_one_blocking_defect_fails_portfolio_gate(self) -> None:
        for slot in range(1, 6):
            generic, visual = self._files(slot, defect_candidate=slot == 1)
            self.service.import_reviewer(generic_reviews_path=generic, visual_review_path=visual)
        aggregate = self.service.aggregate()
        self.assertFalse(aggregate["promotion_recommendation_eligible"])
        self.assertTrue(any(row["candidate_blocking_defect_count"] == 1 for row in aggregate["pair_results"]))


if __name__ == "__main__":
    unittest.main()
