from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from prooflaunch_remix.gtm_emailoctopus_candidate_admission_v2 import (
    GTMEmailOctopusCandidateAdmissionError,
    compile_emailoctopus_candidate_admission,
    verify_emailoctopus_candidate_admission,
)


ROOT = Path(__file__).resolve().parents[1]


class GTMEmailOctopusCandidateAdmissionV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ledger = json.loads((ROOT / "evidence/v10/gtm-all-subvertical-unified-review-ledger-v2.json").read_text())
        cls.dossier = json.loads((ROOT / "evidence/v10/gtm-emailoctopus-admission-dossier-v2.json").read_text())
        cls.proposal = json.loads((ROOT / "evidence/v10/gtm-emailoctopus-named-review-proposal-v2.json").read_text())

    def intake(self) -> dict:
        p = self.proposal
        return {
            "schema": "ProofLaunchGTMAllSubverticalUnifiedReviewIntakeV2",
            "review_ledger_sha256": p["source_unified_review_ledger_sha256"],
            "created_at": "2026-08-05T15:00:00Z",
            "review_count": 1,
            "records": [{
                "review_packet_id": p["review_packet_id"],
                "source_url": p["source_url"],
                "review_packet_sha256": p["review_packet_sha256"],
                "reviewer_name": "Named Test Reviewer",
                "reviewed_at": "2026-08-05T15:00:00Z",
                "source_inspected": True,
                "field_bindings": copy.deepcopy(p["field_bindings"]),
                "cost_components": copy.deepcopy(p["cost_components"]),
                "gate_decisions": {name: True for name in p["gate_evidence"]},
                "exact_claim_bindings": copy.deepcopy(p["exact_primary_claim_bindings"]),
                "decision": "submit_for_admission_gate",
                "decision_notes": "I inspected all seven sources and confirm the bounded noncausal episode bindings.",
                "automatic_promotion_allowed": False,
                "formal_candidate_quota_credit": 0,
            }],
            "automatic_promotion_allowed": False,
            "formal_candidate_quota_credit": 0,
        }

    def test_valid_named_intake_issues_exactly_one_candidate_credit(self) -> None:
        admission = compile_emailoctopus_candidate_admission(
            self.intake(), self.ledger, self.dossier, self.proposal
        )
        verify_emailoctopus_candidate_admission(admission)
        self.assertEqual(admission["formal_candidate_quota_credit"], 1)
        self.assertEqual(admission["candidate"]["quota_credit"], 1)
        self.assertEqual(len(admission["candidate"]["source_receipts"]), 7)
        self.assertEqual(set(admission["candidate"]["resource_costs"]), {
            "paid_media", "personnel", "tools", "creators", "channel_fees", "production"
        })

    def test_anonymous_or_mutated_binding_fails_closed(self) -> None:
        anonymous = self.intake()
        anonymous["records"][0]["reviewer_name"] = ""
        with self.assertRaisesRegex(Exception, "named human"):
            compile_emailoctopus_candidate_admission(anonymous, self.ledger, self.dossier, self.proposal)
        changed = self.intake()
        changed["records"][0]["field_bindings"]["budget_tier"] = "low_budget"
        with self.assertRaisesRegex(GTMEmailOctopusCandidateAdmissionError, "field bindings drifted"):
            compile_emailoctopus_candidate_admission(changed, self.ledger, self.dossier, self.proposal)

    def test_duplicate_episode_fails_closed(self) -> None:
        first = compile_emailoctopus_candidate_admission(
            self.intake(), self.ledger, self.dossier, self.proposal
        )["candidate"]
        with self.assertRaisesRegex(GTMEmailOctopusCandidateAdmissionError, "already exists"):
            compile_emailoctopus_candidate_admission(
                self.intake(), self.ledger, self.dossier, self.proposal, [copy.deepcopy(first)]
            )


if __name__ == "__main__":
    unittest.main()
