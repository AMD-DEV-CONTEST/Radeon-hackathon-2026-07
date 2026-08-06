from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from prooflaunch_remix.gtm_parqet_candidate_admission_v2 import GTMParqetCandidateAdmissionError, compile_parqet_candidate_admission, verify_parqet_candidate_admission


ROOT = Path(__file__).resolve().parents[1]


class GTMParqetCandidateAdmissionV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ledger = json.loads((ROOT / "evidence/v10/gtm-all-subvertical-unified-review-ledger-v2.json").read_text())
        cls.dossier = json.loads((ROOT / "evidence/v10/gtm-parqet-admission-dossier-v2.json").read_text())
        cls.proposal = json.loads((ROOT / "evidence/v10/gtm-parqet-named-review-proposal-v2.json").read_text())

    def intake(self) -> dict:
        p = self.proposal
        return {"schema": "ProofLaunchGTMAllSubverticalUnifiedReviewIntakeV2", "review_ledger_sha256": p["source_unified_review_ledger_sha256"], "created_at": "2026-08-05T19:00:00Z", "review_count": 1, "records": [{"review_packet_id": p["review_packet_id"], "source_url": p["source_url"], "review_packet_sha256": p["review_packet_sha256"], "reviewer_name": "Named Test Reviewer", "reviewed_at": "2026-08-05T19:00:00Z", "source_inspected": True, "field_bindings": copy.deepcopy(p["field_bindings"]), "cost_components": copy.deepcopy(p["cost_components"]), "gate_decisions": {name: True for name in p["gate_evidence"]}, "exact_claim_bindings": copy.deepcopy(p["exact_primary_claim_bindings"]), "decision": "submit_for_admission_gate", "decision_notes": "I inspected all seven sources and retained the low-budget, unaudited and noncausal boundaries.", "automatic_promotion_allowed": False, "formal_candidate_quota_credit": 0}], "automatic_promotion_allowed": False, "formal_candidate_quota_credit": 0}

    def test_valid_named_intake_issues_one_parqet_credit(self) -> None:
        admission = compile_parqet_candidate_admission(self.intake(), self.ledger, self.dossier, self.proposal)
        verify_parqet_candidate_admission(admission)
        self.assertEqual(admission["formal_candidate_quota_credit"], 1)
        self.assertEqual(admission["candidate"]["business_model"], "b2c")
        self.assertEqual(admission["candidate"]["resource_costs"]["tools"]["amount_usd"], 500)
        self.assertEqual(admission["candidate"]["resource_costs"]["paid_media"]["disclosure_status"], "unknown")

    def test_mutation_and_duplicate_fail_closed(self) -> None:
        changed = self.intake()
        changed["records"][0]["cost_components"]["media"] = "zero"
        with self.assertRaisesRegex(GTMParqetCandidateAdmissionError, "cost_components drifted"):
            compile_parqet_candidate_admission(changed, self.ledger, self.dossier, self.proposal)
        first = compile_parqet_candidate_admission(self.intake(), self.ledger, self.dossier, self.proposal)["candidate"]
        with self.assertRaisesRegex(GTMParqetCandidateAdmissionError, "already exists"):
            compile_parqet_candidate_admission(self.intake(), self.ledger, self.dossier, self.proposal, [first])


if __name__ == "__main__":
    unittest.main()
