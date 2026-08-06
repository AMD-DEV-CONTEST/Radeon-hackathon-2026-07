from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import unittest

from prooflaunch_remix.gtm_barn2_candidate_admission_v2 import GTMBarn2CandidateAdmissionError, compile_barn2_candidate_admission, verify_barn2_candidate_admission

ROOT = Path(__file__).resolve().parents[1]

class GTMBarn2AdmissionV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ledger = json.loads((ROOT / "evidence/v10/gtm-all-subvertical-unified-review-ledger-v2.json").read_text())
        cls.dossier = json.loads((ROOT / "evidence/v10/gtm-barn2-admission-dossier-v2.json").read_text())
        cls.proposal = json.loads((ROOT / "evidence/v10/gtm-barn2-named-review-proposal-v2.json").read_text())

    def intake(self) -> dict:
        p = self.proposal
        return {"schema": "ProofLaunchGTMAllSubverticalUnifiedReviewIntakeV2", "review_ledger_sha256": p["source_unified_review_ledger_sha256"], "created_at": "2026-08-05T23:00:00Z", "review_count": 1, "records": [{"review_packet_id": p["review_packet_id"], "source_url": p["source_url"], "review_packet_sha256": p["review_packet_sha256"], "reviewer_name": "Named Test Reviewer", "reviewed_at": "2026-08-05T23:00:00Z", "source_inspected": True, "field_bindings": copy.deepcopy(p["field_bindings"]), "cost_components": copy.deepcopy(p["cost_components"]), "gate_decisions": {name: True for name in p["gate_evidence"]}, "exact_claim_bindings": copy.deepcopy(p["exact_primary_claim_bindings"]), "decision": "submit_for_admission_gate", "decision_notes": "I inspected all seven sources and retained the plateau, capital-efficient, unknown-cost and noncausal boundaries.", "automatic_promotion_allowed": False, "formal_candidate_quota_credit": 0}], "automatic_promotion_allowed": False, "formal_candidate_quota_credit": 0}

    def test_dossier_is_strict_ten_of_eleven(self) -> None:
        unsigned = dict(self.dossier); supplied = unsigned.pop("content_sha256")
        observed = hashlib.sha256(json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        self.assertEqual(supplied, observed)
        self.assertEqual(self.dossier["captured_source_count"], 7)
        self.assertGreaterEqual(self.dossier["independent_captured_source_count"], 3)
        self.assertEqual(self.dossier["evidence_ready_gate_count"], 10)
        self.assertEqual(self.dossier["blocking_gate_count"], 1)
        self.assertEqual(self.dossier["cost_components"]["channel_fees"]["amount_usd"], 21155)

    def test_valid_intake_issues_failed_or_stalled_credit(self) -> None:
        admission = compile_barn2_candidate_admission(self.intake(), self.ledger, self.dossier, self.proposal)
        verify_barn2_candidate_admission(admission)
        self.assertEqual(admission["formal_candidate_quota_credit"], 1)
        self.assertEqual(admission["candidate"]["outcome_type"], "failed_or_stalled")
        self.assertEqual(admission["candidate"]["budget_tier"], "capital_efficient")
        self.assertEqual(admission["candidate"]["resource_costs"]["channel_fees"]["amount_usd"], 21155)

    def test_success_relabel_and_duplicate_fail_closed(self) -> None:
        changed = self.intake(); changed["records"][0]["field_bindings"]["outcome_type"] = "recent_breakout"
        with self.assertRaisesRegex(GTMBarn2CandidateAdmissionError, "field_bindings drifted"):
            compile_barn2_candidate_admission(changed, self.ledger, self.dossier, self.proposal)
        first = compile_barn2_candidate_admission(self.intake(), self.ledger, self.dossier, self.proposal)["candidate"]
        with self.assertRaisesRegex(GTMBarn2CandidateAdmissionError, "already exists"):
            compile_barn2_candidate_admission(self.intake(), self.ledger, self.dossier, self.proposal, [first])

if __name__ == "__main__":
    unittest.main()
