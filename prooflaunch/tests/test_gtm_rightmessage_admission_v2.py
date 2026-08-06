from __future__ import annotations
import copy,hashlib,json,unittest
from pathlib import Path
from prooflaunch_remix.gtm_rightmessage_candidate_admission_v2 import GTMRightMessageCandidateAdmissionError,compile_rightmessage_candidate_admission,verify_rightmessage_candidate_admission
ROOT=Path(__file__).resolve().parents[1]
class GTMRightMessageAdmissionV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ledger=json.loads((ROOT/"evidence/v10/gtm-all-subvertical-unified-review-ledger-v2.json").read_text()); cls.dossier=json.loads((ROOT/"evidence/v10/gtm-rightmessage-admission-dossier-v2.json").read_text()); cls.proposal=json.loads((ROOT/"evidence/v10/gtm-rightmessage-named-review-proposal-v2.json").read_text())
    def intake(self):
        p=self.proposal; return {"schema":"ProofLaunchGTMAllSubverticalUnifiedReviewIntakeV2","review_ledger_sha256":p["source_unified_review_ledger_sha256"],"created_at":"2026-08-06T00:00:00Z","review_count":1,"records":[{"review_packet_id":p["review_packet_id"],"source_url":p["source_url"],"review_packet_sha256":p["review_packet_sha256"],"reviewer_name":"Named Test Reviewer","reviewed_at":"2026-08-06T00:00:00Z","source_inspected":True,"field_bindings":copy.deepcopy(p["field_bindings"]),"cost_components":copy.deepcopy(p["cost_components"]),"gate_decisions":{name:True for name in p["gate_evidence"]},"exact_claim_bindings":copy.deepcopy(p["exact_primary_claim_bindings"]),"decision":"submit_for_admission_gate","decision_notes":"I inspected all seven sources and retained the turnaround, mixed-budget, conflict and noncausal boundaries.","automatic_promotion_allowed":False,"formal_candidate_quota_credit":0}],"automatic_promotion_allowed":False,"formal_candidate_quota_credit":0}
    def test_dossier_is_strict_ten_of_eleven(self):
        unsigned=dict(self.dossier); supplied=unsigned.pop("content_sha256"); observed=hashlib.sha256(json.dumps(unsigned,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest(); self.assertEqual(supplied,observed); self.assertEqual(self.dossier["captured_source_count"],7); self.assertEqual(self.dossier["independent_captured_source_count"],4); self.assertEqual(self.dossier["evidence_ready_gate_count"],10); self.assertEqual(self.dossier["blocking_gate_count"],1); self.assertEqual(self.dossier["budget_context"]["historical_monthly_total_expense_estimate_usd"],20000)
    def test_valid_intake_issues_turnaround_mixed_budget_credit(self):
        admission=compile_rightmessage_candidate_admission(self.intake(),self.ledger,self.dossier,self.proposal); verify_rightmessage_candidate_admission(admission); self.assertEqual(admission["formal_candidate_quota_credit"],1); self.assertEqual(admission["candidate"]["outcome_type"],"turnaround"); self.assertEqual(admission["candidate"]["budget_tier"],"mixed_budget")
    def test_zero_budget_relabel_and_duplicate_fail_closed(self):
        changed=self.intake(); changed["records"][0]["field_bindings"]["budget_tier"]="zero_paid"
        with self.assertRaisesRegex(GTMRightMessageCandidateAdmissionError,"field_bindings drifted"): compile_rightmessage_candidate_admission(changed,self.ledger,self.dossier,self.proposal)
        first=compile_rightmessage_candidate_admission(self.intake(),self.ledger,self.dossier,self.proposal)["candidate"]
        with self.assertRaisesRegex(GTMRightMessageCandidateAdmissionError,"already exists"): compile_rightmessage_candidate_admission(self.intake(),self.ledger,self.dossier,self.proposal,[first])
if __name__=="__main__": unittest.main()
