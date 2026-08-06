from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import unittest

from prooflaunch_remix.gtm_all_subvertical_unified_review_v2 import (
    GTMAllSubverticalUnifiedReviewError,
    INTAKE_SCHEMA,
    build_unified_review_ledger,
    compile_unified_review_receipt,
    review_packet_digest,
    validate_unified_review_intake,
    verify_unified_review_ledger,
    verify_unified_review_receipt,
)
from prooflaunch_remix.gtm_case_candidate_binding_v2 import GATES
from prooflaunch_remix.gtm_case_candidate_review_workbench_v2 import REQUIRED_FIELD_BINDINGS, SIX_COST_COMPONENTS


ROOT = Path(__file__).resolve().parents[1]
LEDGER_PATH = ROOT / "evidence/v10/gtm-all-subvertical-unified-review-ledger-v2.json"
WORKBENCH = ROOT / "artifacts/gtm-all-subvertical-review-workbench-v2"


class GTMAllSubverticalUnifiedReviewV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.binding = json.loads((ROOT / "evidence/v10/gtm-case-candidate-binding-packets-v2.json").read_text())
        cls.queues = [json.loads((ROOT / path).read_text()) for path in (
            "evidence/v10/gtm-all-subvertical-review-queue-v2.json",
            "evidence/v10/gtm-all-subvertical-wave2-b2b-review-queue-v2.json",
            "evidence/v10/gtm-all-subvertical-wave3-b2c-review-queue-v2.json",
            "evidence/v10/gtm-all-subvertical-wave4-classified-review-queue-v2.json",
            "evidence/v10/gtm-all-subvertical-wave7-classified-review-queue-v2.json",
            "evidence/v10/gtm-high-transparency-wave8-review-queue-v2.json",
        )]
        cls.ledger = json.loads(LEDGER_PATH.read_text())

    def _intake(self, *, decision: str = "submit_for_admission_gate") -> dict:
        packet = self.ledger["records"][0]
        excerpt = "A bounded human-inspected excerpt tied to this exact source."
        record = {
            "review_packet_id": packet["review_packet_id"],
            "source_url": packet["source_url"],
            "review_packet_sha256": review_packet_digest(packet),
            "reviewer_name": "Named Human Reviewer",
            "reviewed_at": "2026-08-05T09:00:00Z",
            "source_inspected": True,
            "field_bindings": {name: ["verified route"] if name == "subvertical_ids" else f"verified {name}" for name in REQUIRED_FIELD_BINDINGS},
            "cost_components": {name: f"source-bound {name} evidence" for name in SIX_COST_COMPONENTS},
            "gate_decisions": {name: True for name in GATES},
            "exact_claim_bindings": [{
                "field": "result_summary",
                "source_url": packet["source_url"],
                "exact_excerpt": excerpt,
                "excerpt_sha256": hashlib.sha256(excerpt.encode()).hexdigest(),
            }],
            "decision": decision,
            "decision_notes": "The public source was inspected and remaining risks were recorded.",
            "automatic_promotion_allowed": False,
            "formal_candidate_quota_credit": 0,
        }
        return {
            "schema": INTAKE_SCHEMA,
            "review_ledger_sha256": self.ledger["content_sha256"],
            "created_at": "2026-08-05T09:01:00Z",
            "review_count": 1,
            "records": [record],
            "automatic_promotion_allowed": False,
            "formal_candidate_quota_credit": 0,
        }

    def test_compiler_unifies_all_packets_without_credit(self) -> None:
        rebuilt = build_unified_review_ledger(self.binding, self.queues)
        verify_unified_review_ledger(rebuilt)
        self.assertEqual(rebuilt, self.ledger)
        self.assertEqual(rebuilt["review_packet_count"], 382)
        self.assertEqual(rebuilt["machine_ready_for_named_review_count"], 247)
        self.assertEqual(rebuilt["evidence_gap_count"], 135)
        self.assertEqual(rebuilt["formal_candidate_quota_credit"], 0)

    def test_all_81_subverticals_are_filterable_but_provisional(self) -> None:
        self.assertEqual(self.ledger["represented_subvertical_count"], 81)
        self.assertEqual(len(set(self.ledger["represented_subvertical_ids"])), 81)
        self.assertEqual(self.ledger["observed_named_human_review_count"], 0)
        self.assertTrue(all(row["formal_candidate_quota_credit"] == 0 for row in self.ledger["records"]))

    def test_origin_and_packet_ids_are_unique(self) -> None:
        self.assertEqual(self.ledger["origin_counts"]["gold_candidate_binding_packet"], 220)
        self.assertEqual(self.ledger["origin_counts"]["targeted_subvertical_review_packet"], 162)
        ids = [row["review_packet_id"] for row in self.ledger["records"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_workbench_exposes_counts_filters_and_truth_boundary(self) -> None:
        manifest = json.loads((WORKBENCH / "workbench-manifest.json").read_text())
        page = (WORKBENCH / "index.html").read_text()
        self.assertEqual(manifest["review_packet_count"], 382)
        self.assertEqual(manifest["machine_ready_for_named_review_count"], 247)
        self.assertEqual(manifest["evidence_gap_count"], 135)
        self.assertEqual(manifest["represented_subvertical_count"], 81)
        self.assertEqual(manifest["formal_candidate_quota_credit"], 0)
        self.assertIn("382 source-bound packets · 81/81 subverticals", page)
        self.assertIn("All 81 subverticals", page)
        self.assertIn("Submit for independent admission gate", page)
        self.assertIn("formal_candidate_quota_credit:0", page)

    def test_named_review_yields_only_a_zero_credit_receipt(self) -> None:
        intake = self._intake()
        validate_unified_review_intake(intake, self.ledger)
        receipt = compile_unified_review_receipt(intake, self.ledger)
        verify_unified_review_receipt(receipt)
        self.assertEqual(receipt["review_count"], 1)
        self.assertEqual(receipt["admission_submission_count"], 1)
        self.assertEqual(receipt["formal_candidate_quota_credit"], 0)
        self.assertFalse(receipt["automatic_promotion_allowed"])

    def test_anonymous_uninspected_and_stale_reviews_fail(self) -> None:
        mutations = (
            ("reviewer_name", "", "named human"),
            ("source_inspected", False, "not inspected"),
            ("review_packet_sha256", "0" * 64, "binding drifted"),
        )
        for field, value, message in mutations:
            intake = self._intake()
            intake["records"][0][field] = value
            with self.assertRaisesRegex(GTMAllSubverticalUnifiedReviewError, message):
                validate_unified_review_intake(intake, self.ledger)

    def test_incomplete_submission_and_quota_minting_fail(self) -> None:
        intake = self._intake()
        intake["records"][0]["gate_decisions"]["independent_outcome_surface"] = False
        with self.assertRaisesRegex(GTMAllSubverticalUnifiedReviewError, "failed gates"):
            validate_unified_review_intake(intake, self.ledger)
        intake = self._intake()
        intake["records"][0]["cost_components"]["production"] = ""
        with self.assertRaisesRegex(GTMAllSubverticalUnifiedReviewError, "cost evidence"):
            validate_unified_review_intake(intake, self.ledger)
        intake = self._intake()
        intake["formal_candidate_quota_credit"] = 1
        with self.assertRaisesRegex(GTMAllSubverticalUnifiedReviewError, "quota"):
            validate_unified_review_intake(intake, self.ledger)

    def test_resealed_ledger_cannot_fabricate_human_review(self) -> None:
        tampered = copy.deepcopy(self.ledger)
        tampered["records"][0]["named_reviewer"] = "Fabricated Reviewer"
        tampered["records"][0]["human_source_inspection_completed"] = True
        unsigned = dict(tampered)
        unsigned.pop("content_sha256")
        tampered["content_sha256"] = hashlib.sha256(json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        with self.assertRaisesRegex(GTMAllSubverticalUnifiedReviewError, "escaped"):
            verify_unified_review_ledger(tampered)


if __name__ == "__main__":
    unittest.main()
