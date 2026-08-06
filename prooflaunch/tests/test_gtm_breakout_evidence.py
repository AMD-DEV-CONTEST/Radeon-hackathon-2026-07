from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from prooflaunch_remix.gtm_breakout_evidence import (
    GTMBreakoutEvidenceError,
    compile_evidence_ledger,
    verify_evidence_corpus,
    verify_evidence_ledger,
)


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "config" / "gtm-breakout-evidence-cases-v1.json"


def _source() -> dict:
    return json.loads(SOURCE.read_text(encoding="utf-8"))


class GTMBreakoutEvidenceTests(unittest.TestCase):
    def test_corpus_has_b2b_b2c_awards_growth_and_research(self) -> None:
        audit = verify_evidence_corpus(_source())
        self.assertGreaterEqual(audit["case_count"], 18)
        self.assertGreaterEqual(audit["business_model_counts"]["b2b"], 7)
        self.assertGreaterEqual(audit["business_model_counts"]["b2c"], 6)
        self.assertGreaterEqual(audit["kind_counts"]["award_creative"], 12)
        self.assertGreaterEqual(audit["kind_counts"]["growth_claim"], 2)
        self.assertGreaterEqual(audit["kind_counts"]["research_constraint"], 3)
        self.assertGreaterEqual(audit["industry_language_contract_count"], 8)

    def test_no_unverified_zero_spend_claim_is_promoted(self) -> None:
        audit = verify_evidence_corpus(_source())
        self.assertEqual(audit["verified_zero_paid_media_case_count"], 0)

    def test_mechanisms_require_multiple_valid_cases(self) -> None:
        source = _source()
        source["generalized_mechanisms"][0]["evidence_case_ids"] = [source["cases"][0]["case_id"]]
        with self.assertRaisesRegex(GTMBreakoutEvidenceError, "evidence_case_ids"):
            verify_evidence_corpus(source)

    def test_self_report_cannot_be_grade_a(self) -> None:
        source = _source()
        growth = next(case for case in source["cases"] if case["case_kind"] == "growth_claim")
        growth["evidence_grade"] = "A"
        with self.assertRaisesRegex(GTMBreakoutEvidenceError, "overstates grade A"):
            verify_evidence_corpus(source)

    def test_reference_copy_reuse_is_always_disabled(self) -> None:
        source = _source()
        source["cases"][0]["verbatim_copy_reuse_allowed"] = True
        with self.assertRaisesRegex(GTMBreakoutEvidenceError, "reference-copy reuse"):
            verify_evidence_corpus(source)

    def test_compiled_digest_detects_tampering(self) -> None:
        ledger = compile_evidence_ledger(_source())
        verify_evidence_ledger(ledger)
        tampered = copy.deepcopy(ledger)
        tampered["cases"][0]["company"] = "tampered"
        with self.assertRaisesRegex(GTMBreakoutEvidenceError, "digest"):
            verify_evidence_ledger(tampered)


if __name__ == "__main__":
    unittest.main()
