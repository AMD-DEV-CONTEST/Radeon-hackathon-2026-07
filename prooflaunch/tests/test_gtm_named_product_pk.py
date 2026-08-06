from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from prooflaunch_remix.gtm_named_product_baseline import (  # noqa: E402
    CAPTURE_SCHEMA,
    content_sha256,
    import_capture,
)
from prooflaunch_remix.gtm_named_product_pk import (  # noqa: E402
    PREPARATION_ATTESTATIONS,
    REVIEW_ATTESTATION,
    REVIEW_SCHEMA,
    NamedProductPKConflictError,
    NamedProductPKError,
    NamedProductPKReviewService,
    compile_named_product_blind_packet,
    compile_named_product_pk_portfolio,
    create_preparation,
    sha256_json,
    validate_public_packet,
)
from scripts.export_gtm_named_product_baseline_capture_kit import export  # noqa: E402


LEDGER = ROOT / "evidence/v10/gtm-concrete-product-effect-pk-ledger-v1.json"
CHALLENGER_ADMISSION = ROOT / "artifacts/gtm-last-mile-pk-v1/named-product-challenger-dossiers-v3/manifest.json"


class GTMNamedProductPKTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(dir=ROOT)
        self.temp = Path(self.temporary.name)
        self.kit = self.temp / "capture-kit"
        export(self.kit)
        self.manifest = json.loads((self.kit / "manifest.json").read_text(encoding="utf-8"))
        self.slot = next(
            item for item in self.manifest["capture_slots"]
            if item["category_id"] == "content_scheduling_operations"
            and item["reference_product"] == "Hootsuite"
        )
        self.baseline = self.temp / "baseline.json"
        self.baseline.write_text('{"memory":"source-hidden baseline response"}\n', encoding="utf-8")
        capture = {
            "schema": CAPTURE_SCHEMA,
            "capture_slot_id": self.slot["capture_slot_id"],
            "category_id": self.slot["category_id"],
            "reference_product": self.slot["reference_product"],
            "reference_product_url": self.slot["reference_product_url"],
            "frozen_brief_sha256": self.slot["frozen_brief_sha256"],
            "operator_id": "qualified-capture-operator",
            "captured_at": "2026-08-03T08:00:00+00:00",
            "provider_model_or_version": "observed-authorized-build",
            "acquisition_method": "authorized_product_use",
            "rights_attestation": {
                "authorized_to_evaluate_and_retain": True,
                "same_frozen_brief_without_hidden_editing": True,
                "provider_and_version_recorded_truthfully": True,
            },
            "artifact": {
                "name": self.baseline.name,
                "mime_type": "application/json",
                "bytes": self.baseline.stat().st_size,
                "sha256": hashlib.sha256(self.baseline.read_bytes()).hexdigest(),
            },
        }
        capture["content_sha256"] = content_sha256(capture)
        capture_path = self.temp / "capture.json"
        capture_path.write_text(json.dumps(capture), encoding="utf-8")
        self.baseline_store = self.temp / "baselines"
        import_capture(
            manifest_path=self.kit / "manifest.json",
            capture_path=capture_path,
            artifact_path=self.baseline,
            store_root=self.baseline_store,
        )
        challenger_admission = json.loads(CHALLENGER_ADMISSION.read_text(encoding="utf-8"))
        category_admission = next(
            item for item in challenger_admission["categories"]
            if item["category_id"] == self.slot["category_id"]
        )
        self.candidate_source = ROOT / category_admission["dossier"]["project_relative_path"]
        self.baseline_review = self.temp / "anonymous-baseline.json"
        self.candidate_review = self.temp / "anonymous-candidate.html"
        self.baseline_review.write_bytes(self.baseline.read_bytes())
        self.candidate_review.write_bytes(self.candidate_source.read_bytes())
        self.prep = create_preparation(
            project_root=ROOT,
            capture_manifest_path=self.kit / "manifest.json",
            ledger_path=LEDGER,
            challenger_admission_path=CHALLENGER_ADMISSION,
            baseline_store_root=self.baseline_store,
            capture_slot_id=self.slot["capture_slot_id"],
            baseline_review_path=self.baseline_review,
            candidate_review_path=self.candidate_review,
            operator_id="qualified-anonymization-operator",
            prepared_at="2026-08-03T08:30:00+00:00",
            attestations={key: True for key in PREPARATION_ATTESTATIONS},
        )
        self.prep_path = self.temp / "preparation.json"
        self.prep_path.write_text(json.dumps(self.prep), encoding="utf-8")
        self.packet = self.temp / "packet"
        compile_named_product_blind_packet(
            project_root=ROOT,
            capture_manifest_path=self.kit / "manifest.json",
            ledger_path=LEDGER,
            challenger_admission_path=CHALLENGER_ADMISSION,
            baseline_store_root=self.baseline_store,
            capture_slot_id=self.slot["capture_slot_id"],
            preparation_path=self.prep_path,
            baseline_review_path=self.baseline_review,
            candidate_review_path=self.candidate_review,
            output_root=self.packet,
        )
        self.public = json.loads((self.packet / "public/packet.json").read_text(encoding="utf-8"))
        self.private = json.loads((self.packet / "private/mapping.json").read_text(encoding="utf-8"))

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _review(self, slot: int, *, defect: bool = False, pseudonym: str | None = None) -> Path:
        task = next(item for item in self.public["review_tasks"] if item["reviewer_slot"] == slot)
        mapping = self.private["task_side_mapping"][task["review_task_id"]]
        candidate_side = next(side for side, role in mapping.items() if role == "candidate")
        review = {
            "schema": REVIEW_SCHEMA,
            "review_task_id": task["review_task_id"],
            "comparison_id": task["comparison_id"],
            "pair_sha256": task["pair_sha256"],
            "reviewer_slot": slot,
            "reviewer_pseudonym": pseudonym or f"qualified-human-{slot}",
            "human_attestation": REVIEW_ATTESTATION,
            "choice": candidate_side,
            "axis_winners": {
                axis: candidate_side for axis in task["quality_axes"]
            },
            "left_directly_publishable": candidate_side == "left",
            "right_directly_publishable": candidate_side == "right",
            "left_major_rework": False,
            "right_major_rework": False,
            "blocking_defect_side": candidate_side if defect else "none",
            "blocking_defect_reason": "Located factual blocking defect." if defect else "",
            "rationale": "The candidate is more complete, traceable, and ready for this frozen brief.",
            "reviewed_at": "2026-08-03T09:00:00+00:00",
        }
        review["review_content_sha256"] = sha256_json(review)
        path = self.temp / f"review-{slot}.json"
        path.write_text(json.dumps(review), encoding="utf-8")
        return path

    def test_packet_is_source_hidden_balanced_and_five_kit_executable(self) -> None:
        validate_public_packet(self.public, public_root=self.packet / "public")
        self.assertEqual(len(self.public["review_tasks"]), 5)
        self.assertFalse(self.public["source_roles_exposed"])
        self.assertTrue(self.public["intrinsic_style_may_be_recognizable"])
        left_count = self.private["balanced_candidate_left_count"]
        self.assertIn(left_count, {2, 3})
        self.assertEqual(len(list((self.packet / "offline-kits").glob("reviewer-*.zip"))), 5)
        for slot in range(1, 6):
            html = (self.packet / f"public/reviewer-{slot:02d}.html").read_text(encoding="utf-8")
            self.assertNotIn("Hootsuite", html)
            self.assertNotIn("observed-authorized-build", html)
            self.assertIn("Source-hidden same-brief review", html)

    def test_five_unanimous_reviews_complete_one_row_without_auto_action_or_4a_claim(self) -> None:
        aggregate_root = self.temp / "aggregate-root"
        store = aggregate_root / self.slot["capture_slot_id"]
        service = NamedProductPKReviewService(packet_root=self.packet, store_root=store)
        for slot in range(1, 6):
            receipt = service.submit(self._review(slot))
        self.assertTrue(receipt["review_complete"])
        aggregate = service.aggregate()
        self.assertTrue(aggregate["named_product_pk_row_completed"])
        self.assertTrue(aggregate["candidate_won_same_brief_last_mile_pk"])
        self.assertGreater(aggregate["candidate_preference_wilson_lower_95"], 0.5)
        self.assertEqual(aggregate["candidate_quality_axis_losses"], [])
        self.assertTrue(
            aggregate["gate_checks"]["candidate_loses_no_declared_quality_axis"]
        )
        self.assertFalse(aggregate["automatic_runtime_switch_enabled"])
        self.assertFalse(aggregate["four_a_quality_proven"])
        portfolio = compile_named_product_pk_portfolio(
            capture_manifest_path=self.kit / "manifest.json",
            ledger_path=LEDGER,
            aggregate_root=aggregate_root,
        )
        self.assertEqual(portfolio["completed_product_pk_rows"], 1)
        self.assertEqual(portfolio["candidate_won_product_pk_rows"], 1)
        self.assertEqual(portfolio["effect_aligned_category_count"], 0)
        self.assertFalse(portfolio["named_product_last_mile_alignment_achieved"])
        self.assertFalse(portfolio["four_a_quality_proven"])

    def test_incomplete_duplicate_and_tampered_reviews_fail_closed(self) -> None:
        service = NamedProductPKReviewService(packet_root=self.packet, store_root=self.temp / "reviews")
        service.submit(self._review(1))
        with self.assertRaises(NamedProductPKConflictError):
            service.aggregate()
        with self.assertRaises(NamedProductPKConflictError):
            service.submit(self._review(2, pseudonym="qualified-human-1"))
        tampered = self._review(2)
        payload = json.loads(tampered.read_text(encoding="utf-8"))
        payload["choice"] = "abstain"
        tampered.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaises(NamedProductPKError):
            service.submit(tampered)

    def test_blocking_defect_prevents_named_product_win(self) -> None:
        service = NamedProductPKReviewService(packet_root=self.packet, store_root=self.temp / "defect-reviews")
        for slot in range(1, 6):
            service.submit(self._review(slot, defect=slot == 1))
        aggregate = service.aggregate()
        self.assertTrue(aggregate["named_product_pk_row_completed"])
        self.assertFalse(aggregate["candidate_won_same_brief_last_mile_pk"])
        self.assertEqual(aggregate["candidate_blocking_defect_count"], 1)

    def test_one_lost_quality_axis_prevents_named_product_win(self) -> None:
        service = NamedProductPKReviewService(
            packet_root=self.packet, store_root=self.temp / "axis-loss-reviews"
        )
        lost_axis = self.public["review_tasks"][0]["quality_axes"][0]
        for slot in range(1, 6):
            path = self._review(slot)
            payload = json.loads(path.read_text(encoding="utf-8"))
            task = next(
                item
                for item in self.public["review_tasks"]
                if item["reviewer_slot"] == slot
            )
            candidate_side = next(
                side
                for side, role in self.private["task_side_mapping"][
                    task["review_task_id"]
                ].items()
                if role == "candidate"
            )
            payload["axis_winners"][lost_axis] = (
                "right" if candidate_side == "left" else "left"
            )
            payload.pop("review_content_sha256")
            payload["review_content_sha256"] = sha256_json(payload)
            path.write_text(json.dumps(payload), encoding="utf-8")
            service.submit(path)
        aggregate = service.aggregate()
        self.assertFalse(aggregate["candidate_won_same_brief_last_mile_pk"])
        self.assertEqual(aggregate["candidate_quality_axis_losses"], [lost_axis])

    def test_preparation_or_review_asset_drift_blocks_pairing(self) -> None:
        self.candidate_review.write_text('{"tampered":true}\n', encoding="utf-8")
        with self.assertRaisesRegex(NamedProductPKError, "review artifact binding"):
            compile_named_product_blind_packet(
                project_root=ROOT,
                capture_manifest_path=self.kit / "manifest.json",
                ledger_path=LEDGER,
                challenger_admission_path=CHALLENGER_ADMISSION,
                baseline_store_root=self.baseline_store,
                capture_slot_id=self.slot["capture_slot_id"],
                preparation_path=self.prep_path,
                baseline_review_path=self.baseline_review,
                candidate_review_path=self.candidate_review,
                output_root=self.temp / "second-packet",
            )


if __name__ == "__main__":
    unittest.main()
