from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from prooflaunch_remix.gtm_four_case_batch_admission_v2 import (
    GTMFourCaseBatchAdmissionError,
    compile_four_case_batch_admission,
    verify_four_case_batch_admission,
)


ROOT = Path(__file__).resolve().parents[1]


class GTMFourCaseBatchAdmissionV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ledger = json.loads((ROOT / "evidence/v10/gtm-all-subvertical-unified-review-ledger-v2.json").read_text())
        cls.slugs = {
            "EmailOctopus": "emailoctopus",
            "Buffer": "buffer",
            "Flodesk": "flodesk",
            "Post Bridge": "postbridge",
        }
        cls.dossiers = {
            company: json.loads((ROOT / f"evidence/v10/gtm-{slug}-admission-dossier-v2.json").read_text())
            for company, slug in cls.slugs.items()
        }
        cls.proposals = {
            company: json.loads((ROOT / f"evidence/v10/gtm-{slug}-named-review-proposal-v2.json").read_text())
            for company, slug in cls.slugs.items()
        }

    def intake(self) -> dict:
        records = []
        for company, proposal in self.proposals.items():
            records.append({
                "review_packet_id": proposal["review_packet_id"],
                "source_url": proposal["source_url"],
                "review_packet_sha256": proposal["review_packet_sha256"],
                "reviewer_name": "Named Test Reviewer",
                "reviewed_at": "2026-08-05T18:00:00Z",
                "source_inspected": True,
                "field_bindings": copy.deepcopy(proposal["field_bindings"]),
                "cost_components": copy.deepcopy(proposal["cost_components"]),
                "gate_decisions": {name: True for name in proposal["gate_evidence"]},
                "exact_claim_bindings": copy.deepcopy(proposal["exact_primary_claim_bindings"]),
                "decision": "submit_for_admission_gate",
                "decision_notes": f"I inspected every bound source for {company} and retained all unknown and noncausal boundaries.",
                "automatic_promotion_allowed": False,
                "formal_candidate_quota_credit": 0,
            })
        return {
            "schema": "ProofLaunchGTMAllSubverticalUnifiedReviewIntakeV2",
            "review_ledger_sha256": self.ledger["content_sha256"],
            "created_at": "2026-08-05T18:00:00Z",
            "review_count": 4,
            "records": records,
            "automatic_promotion_allowed": False,
            "formal_candidate_quota_credit": 0,
        }

    def test_four_valid_reviews_issue_four_atomic_admissions(self) -> None:
        batch = compile_four_case_batch_admission(
            self.intake(), self.ledger, self.dossiers, self.proposals
        )
        verify_four_case_batch_admission(batch)
        self.assertEqual(batch["candidate_count"], 4)
        self.assertEqual(batch["formal_candidate_quota_credit"], 4)
        self.assertEqual(len({row["candidate"]["case_id"] for row in batch["admissions"]}), 4)

    def test_incomplete_batch_fails_before_credit(self) -> None:
        intake = self.intake()
        intake["records"].pop()
        intake["review_count"] = 3
        with self.assertRaisesRegex(GTMFourCaseBatchAdmissionError, "exactly the four"):
            compile_four_case_batch_admission(intake, self.ledger, self.dossiers, self.proposals)


if __name__ == "__main__":
    unittest.main()
