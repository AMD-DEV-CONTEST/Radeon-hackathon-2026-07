from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from prooflaunch_remix.gtm_seven_case_batch_admission_v2 import GTMSevenCaseBatchAdmissionError, compile_seven_case_batch_admission, verify_seven_case_batch_admission


ROOT = Path(__file__).resolve().parents[1]
SPECS = (("EmailOctopus", "emailoctopus"), ("Buffer", "buffer"), ("Flodesk", "flodesk"), ("Post Bridge", "postbridge"), ("Parqet", "parqet"), ("Spendbase", "spendbase"), ("Barn2", "barn2"))


class GTMSevenCaseBatchAdmissionV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ledger = json.loads((ROOT / "evidence/v10/gtm-all-subvertical-unified-review-ledger-v2.json").read_text())
        cls.dossiers = {company: json.loads((ROOT / f"evidence/v10/gtm-{slug}-admission-dossier-v2.json").read_text()) for company, slug in SPECS}
        cls.proposals = {company: json.loads((ROOT / f"evidence/v10/gtm-{slug}-named-review-proposal-v2.json").read_text()) for company, slug in SPECS}

    def intake(self) -> dict:
        records = []
        for company, _ in SPECS:
            p = self.proposals[company]
            records.append({"review_packet_id": p["review_packet_id"], "source_url": p["source_url"], "review_packet_sha256": p["review_packet_sha256"], "reviewer_name": "Named Batch Reviewer", "reviewed_at": "2026-08-05T23:30:00Z", "source_inspected": True, "field_bindings": copy.deepcopy(p["field_bindings"]), "cost_components": copy.deepcopy(p["cost_components"]), "gate_decisions": {name: True for name in p["gate_evidence"]}, "exact_claim_bindings": copy.deepcopy(p["exact_primary_claim_bindings"]), "decision": "submit_for_admission_gate", "decision_notes": f"I inspected all bound sources for {company} and retained every cost, result and causality boundary.", "automatic_promotion_allowed": False, "formal_candidate_quota_credit": 0})
        return {"schema": "ProofLaunchGTMAllSubverticalUnifiedReviewIntakeV2", "review_ledger_sha256": self.ledger["content_sha256"], "created_at": "2026-08-05T23:30:00Z", "review_count": 7, "records": records, "automatic_promotion_allowed": False, "formal_candidate_quota_credit": 0}

    def test_seven_valid_reviews_issue_seven_atomic_admissions(self) -> None:
        payload = compile_seven_case_batch_admission(self.intake(), self.ledger, self.dossiers, self.proposals)
        verify_seven_case_batch_admission(payload)
        self.assertEqual(payload["candidate_count"], 7)
        self.assertEqual(payload["formal_candidate_quota_credit"], 7)
        self.assertEqual(len({row["candidate"]["episode_key"] for row in payload["admissions"]}), 7)

    def test_incomplete_or_mixed_reviewer_batch_fails_before_credit(self) -> None:
        incomplete = self.intake(); incomplete["records"].pop(); incomplete["review_count"] = 6
        with self.assertRaisesRegex(GTMSevenCaseBatchAdmissionError, "exactly the seven"):
            compile_seven_case_batch_admission(incomplete, self.ledger, self.dossiers, self.proposals)
        mixed = self.intake(); mixed["records"][6]["reviewer_name"] = "Different Reviewer"
        with self.assertRaisesRegex(GTMSevenCaseBatchAdmissionError, "one named reviewer"):
            compile_seven_case_batch_admission(mixed, self.ledger, self.dossiers, self.proposals)


class GTMSevenCaseBatchReviewV2Tests(unittest.TestCase):
    def test_manifest_and_page_preserve_human_gate(self) -> None:
        manifest = json.loads((ROOT / "artifacts/gtm-seven-case-batch-review-v2/manifest.json").read_text())
        self.assertEqual(manifest["case_count"], 7)
        self.assertEqual(manifest["source_link_count"], 49)
        self.assertEqual(manifest["formal_candidate_quota_credit"], 0)
        page = (ROOT / "artifacts/gtm-seven-case-batch-review-v2/index.html").read_text()
        self.assertIn("0/7 案完成实质检查", page)
        self.assertIn("admit_gtm_seven_case_batch_v2.py", page)
        self.assertNotIn("reviewer_name\":\"", page)


if __name__ == "__main__":
    unittest.main()
