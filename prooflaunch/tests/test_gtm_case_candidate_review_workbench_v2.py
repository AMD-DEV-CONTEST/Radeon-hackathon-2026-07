from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import unittest

from prooflaunch_remix.gtm_case_candidate_binding_v2 import GATES
from prooflaunch_remix.gtm_case_candidate_review_workbench_v2 import (
    GTMCaseCandidateReviewError,
    INTAKE_SCHEMA,
    REQUIRED_FIELD_BINDINGS,
    SIX_COST_COMPONENTS,
    compile_review_receipt,
    packet_digest,
    validate_review_intake,
    verify_review_receipt,
)


ROOT = Path(__file__).resolve().parents[1]
PACKETS = ROOT / "evidence/v10/gtm-case-candidate-binding-packets-v2.json"
WORKBENCH = ROOT / "artifacts/gtm-case-candidate-review-workbench-v2"


class GTMCaseCandidateReviewWorkbenchV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.packets = json.loads(PACKETS.read_text(encoding="utf-8"))

    def _intake(self, *, decision: str = "submit_for_admission_gate") -> dict:
        packet = self.packets["records"][0]
        excerpt = "Revenue increased during the bounded observation window."
        record = {
            "packet_id": packet["packet_id"],
            "source_url": packet["source_url"],
            "packet_sha256": packet_digest(packet),
            "reviewer_name": "A. Human Reviewer",
            "reviewed_at": "2026-08-05T08:00:00Z",
            "source_inspected": True,
            "field_bindings": {name: f"verified {name}" for name in REQUIRED_FIELD_BINDINGS},
            "cost_components": {name: f"source states {name} cost" for name in SIX_COST_COMPONENTS},
            "gate_decisions": {name: True for name in GATES},
            "exact_claim_bindings": [{
                "field": "result_summary",
                "source_url": packet["source_url"],
                "exact_excerpt": excerpt,
                "excerpt_sha256": hashlib.sha256(excerpt.encode("utf-8")).hexdigest(),
            }],
            "decision": decision,
            "decision_notes": "Inspected the source and preserved the exact evidence boundary.",
            "automatic_candidate_promotion_allowed": False,
            "candidate_quota_credit": 0,
        }
        return {
            "schema": INTAKE_SCHEMA,
            "binding_packet_set_sha256": self.packets["content_sha256"],
            "created_at": "2026-08-05T08:01:00Z",
            "review_count": 1,
            "records": [record],
            "automatic_candidate_promotion_allowed": False,
            "candidate_quota_credit": 0,
        }

    def test_workbench_exposes_all_packets_and_never_claims_review(self) -> None:
        manifest = json.loads((WORKBENCH / "workbench-manifest.json").read_text(encoding="utf-8"))
        page = (WORKBENCH / "index.html").read_text(encoding="utf-8")
        self.assertEqual(manifest["packet_count"], self.packets["packet_count"])
        self.assertEqual(
            manifest["machine_ready_for_human_binding_count"],
            self.packets["status_counts"]["machine_ready_for_human_binding"],
        )
        self.assertEqual(
            manifest["evidence_gap_count"],
            self.packets["status_counts"]["evidence_gap"],
        )
        self.assertEqual(manifest["observed_human_review_count"], 0)
        self.assertEqual(manifest["candidate_quota_credit"], 0)
        self.assertFalse(manifest["automatic_candidate_promotion_allowed"])
        self.assertIn("Inspect the source. Bind the claim. Mint nothing.", page)
        self.assertIn(self.packets["content_sha256"], page)
        self.assertIn("Submit for independent admission gate", page)
        self.assertIn("candidate_quota_credit:0", page)

    def test_complete_named_review_compiles_only_a_zero_credit_receipt(self) -> None:
        intake = self._intake()
        validate_review_intake(intake, self.packets)
        receipt = compile_review_receipt(intake, self.packets)
        verify_review_receipt(receipt)
        self.assertEqual(receipt["review_count"], 1)
        self.assertEqual(receipt["admission_submission_count"], 1)
        self.assertEqual(receipt["candidate_quota_credit"], 0)
        self.assertFalse(receipt["automatic_candidate_promotion_allowed"])

    def test_anonymous_or_uninspected_review_is_rejected(self) -> None:
        for field, value, message in (
            ("reviewer_name", "", "named human reviewer"),
            ("source_inspected", False, "source was not inspected"),
        ):
            intake = self._intake()
            intake["records"][0][field] = value
            with self.assertRaisesRegex(GTMCaseCandidateReviewError, message):
                validate_review_intake(intake, self.packets)

    def test_incomplete_admission_submission_is_rejected(self) -> None:
        intake = self._intake()
        intake["records"][0]["gate_decisions"]["independent_outcome_surface"] = False
        with self.assertRaisesRegex(GTMCaseCandidateReviewError, "failed gates"):
            validate_review_intake(intake, self.packets)

        intake = self._intake()
        intake["records"][0]["cost_components"]["media"] = ""
        with self.assertRaisesRegex(GTMCaseCandidateReviewError, "incomplete cost evidence"):
            validate_review_intake(intake, self.packets)

    def test_stale_packet_or_quota_promotion_is_rejected(self) -> None:
        intake = self._intake()
        intake["records"][0]["packet_sha256"] = "0" * 64
        with self.assertRaisesRegex(GTMCaseCandidateReviewError, "packet hash drifted"):
            validate_review_intake(intake, self.packets)

        for target in ("root", "record"):
            intake = self._intake()
            if target == "root":
                intake["candidate_quota_credit"] = 1
            else:
                intake["records"][0]["candidate_quota_credit"] = 1
            with self.assertRaisesRegex(GTMCaseCandidateReviewError, "quota"):
                validate_review_intake(intake, self.packets)

    def test_non_admission_decision_requires_a_reason(self) -> None:
        intake = self._intake(decision="needs_more_evidence")
        intake["records"][0]["decision_notes"] = ""
        with self.assertRaisesRegex(GTMCaseCandidateReviewError, "lacks notes"):
            validate_review_intake(intake, self.packets)


if __name__ == "__main__":
    unittest.main()
