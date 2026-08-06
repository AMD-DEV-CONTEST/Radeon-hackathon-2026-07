from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import unittest

from prooflaunch_remix.gtm_spendbase_candidate_admission_v2 import (
    GTMSpendbaseCandidateAdmissionError,
    compile_spendbase_candidate_admission,
    verify_spendbase_candidate_admission,
)


ROOT = Path(__file__).resolve().parents[1]


class GTMSpendbaseAdmissionV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ledger = json.loads((ROOT / "evidence/v10/gtm-all-subvertical-unified-review-ledger-v2.json").read_text())
        cls.dossier = json.loads((ROOT / "evidence/v10/gtm-spendbase-admission-dossier-v2.json").read_text())
        cls.proposal = json.loads((ROOT / "evidence/v10/gtm-spendbase-named-review-proposal-v2.json").read_text())

    def intake(self) -> dict:
        p = self.proposal
        return {"schema": "ProofLaunchGTMAllSubverticalUnifiedReviewIntakeV2", "review_ledger_sha256": p["source_unified_review_ledger_sha256"], "created_at": "2026-08-05T22:00:00Z", "review_count": 1, "records": [{"review_packet_id": p["review_packet_id"], "source_url": p["source_url"], "review_packet_sha256": p["review_packet_sha256"], "reviewer_name": "Named Test Reviewer", "reviewed_at": "2026-08-05T22:00:00Z", "source_inspected": True, "field_bindings": copy.deepcopy(p["field_bindings"]), "cost_components": copy.deepcopy(p["cost_components"]), "gate_decisions": {name: True for name in p["gate_evidence"]}, "exact_claim_bindings": copy.deepcopy(p["exact_primary_claim_bindings"]), "decision": "submit_for_admission_gate", "decision_notes": "I inspected all seven sources and retained mature-scale, unaudited, unknown-cost and noncausal boundaries.", "automatic_promotion_allowed": False, "formal_candidate_quota_credit": 0}], "automatic_promotion_allowed": False, "formal_candidate_quota_credit": 0}

    def test_dossier_is_strict_ten_of_eleven(self) -> None:
        unsigned = dict(self.dossier)
        supplied = unsigned.pop("content_sha256")
        observed = hashlib.sha256(json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        self.assertEqual(supplied, observed)
        self.assertEqual(self.dossier["captured_source_count"], 7)
        self.assertGreaterEqual(self.dossier["independent_captured_source_count"], 3)
        self.assertEqual(self.dossier["evidence_ready_gate_count"], 10)
        self.assertEqual(self.dossier["blocking_gate_count"], 1)
        self.assertEqual(self.dossier["gates"]["named_human_exact_binding"], "pending_named_review")
        self.assertTrue(all(row["amount_usd"] is None for row in self.dossier["cost_components"].values()))

    def test_valid_named_intake_issues_one_mature_scale_credit(self) -> None:
        admission = compile_spendbase_candidate_admission(self.intake(), self.ledger, self.dossier, self.proposal)
        verify_spendbase_candidate_admission(admission)
        self.assertEqual(admission["formal_candidate_quota_credit"], 1)
        self.assertEqual(admission["candidate"]["business_model"], "b2b")
        self.assertEqual(admission["candidate"]["budget_tier"], "mature_scale")
        self.assertTrue(all(row["disclosure_status"] == "unknown" for row in admission["candidate"]["resource_costs"].values()))

    def test_mutation_and_duplicate_fail_closed(self) -> None:
        changed = self.intake()
        changed["records"][0]["field_bindings"]["budget_tier"] = "zero_paid"
        with self.assertRaisesRegex(GTMSpendbaseCandidateAdmissionError, "field_bindings drifted"):
            compile_spendbase_candidate_admission(changed, self.ledger, self.dossier, self.proposal)
        first = compile_spendbase_candidate_admission(self.intake(), self.ledger, self.dossier, self.proposal)["candidate"]
        with self.assertRaisesRegex(GTMSpendbaseCandidateAdmissionError, "already exists"):
            compile_spendbase_candidate_admission(self.intake(), self.ledger, self.dossier, self.proposal, [first])


if __name__ == "__main__":
    unittest.main()
