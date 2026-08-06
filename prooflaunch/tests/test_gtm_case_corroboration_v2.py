from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from prooflaunch_remix.gtm_case_corroboration_v2 import (
    GTMCaseCorroborationError,
    compile_case_corroboration,
    verify_case_corroboration,
)


ROOT = Path(__file__).resolve().parents[1]


class GTMCaseCorroborationV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.queue = json.loads((ROOT / "evidence/v10/gtm-gold-lead-review-queue-v2.json").read_text())
        cls.capture = json.loads((ROOT / "evidence/v10/gtm-case-corroboration-public-capture-v2.json").read_text())
        cls.sources = json.loads((ROOT / "data/gtm_case_funnel_v2/corroboration-public-leads-v2.json").read_text())["records"]

    def test_compiles_three_queries_per_lead_and_never_grants_credit(self) -> None:
        payload = compile_case_corroboration(
            self.queue, self.capture, self.sources, research_cutoff="2026-08-05"
        )
        verify_case_corroboration(payload)
        self.assertEqual(payload["query_count"], payload["review_lead_count"] * 3)
        self.assertEqual(payload["candidate_quota_credit"], 0)
        self.assertEqual(payload["outcome_audit_credit"], 0)
        self.assertEqual(payload["human_confirmed_independent_evidence_count"], 0)
        self.assertGreater(payload["query_status_counts"].get("prepared_with_provisional_entity_hint", 0), 0)
        self.assertTrue(all(not row["entity_hint_is_admission_identity"] for row in payload["queries"]))

    def test_partner_first_party_and_republication_are_not_independent(self) -> None:
        payload = compile_case_corroboration(
            self.queue, self.capture, self.sources, research_cutoff="2026-08-05"
        )
        self.assertEqual(payload["independent_same_claim_candidate_count"], 0)
        self.assertTrue(all(not row["automatic_independent_evidence_credit"] for row in payload["records"]))

    def test_unknown_lead_and_invalid_source_class_fail_closed(self) -> None:
        bad = copy.deepcopy(self.sources[0])
        bad["lead_id"] = "missing"
        with self.assertRaisesRegex(GTMCaseCorroborationError, "unknown lead"):
            compile_case_corroboration(self.queue, self.capture, [bad], research_cutoff="2026-08-05")
        bad = copy.deepcopy(self.sources[0])
        bad["source_class"] = "independent_by_assumption"
        with self.assertRaisesRegex(GTMCaseCorroborationError, "class or relation"):
            compile_case_corroboration(self.queue, self.capture, [bad], research_cutoff="2026-08-05")

    def test_resealed_credit_tamper_is_rejected(self) -> None:
        payload = compile_case_corroboration(
            self.queue, self.capture, self.sources, research_cutoff="2026-08-05"
        )
        tampered = copy.deepcopy(payload)
        tampered["records"][0]["candidate_quota_credit"] = 1
        unsigned = dict(tampered)
        unsigned.pop("content_sha256", None)
        import hashlib
        tampered["content_sha256"] = hashlib.sha256(
            json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        ).hexdigest()
        with self.assertRaisesRegex(GTMCaseCorroborationError, "review boundary"):
            verify_case_corroboration(tampered)


if __name__ == "__main__":
    unittest.main()
