from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from prooflaunch_remix.gtm_breakout_evidence import (
    GTMBreakoutEvidenceError,
    compile_case_promotion_queue,
    compile_expanded_case_index,
    verify_case_promotion_queue,
    verify_expanded_case_index,
)


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "evidence" / "v10" / "gtm-breakout-expanded-case-index-v2.json"
QUEUE_ARTIFACT = ROOT / "evidence" / "v10" / "gtm-breakout-case-promotion-queue-v2.json"


def _index() -> dict:
    return json.loads(ARTIFACT.read_text(encoding="utf-8"))


class GTMBreakoutExpandedCaseIndexTests(unittest.TestCase):
    def test_index_has_broad_year_business_and_industry_coverage(self) -> None:
        index = _index()
        verify_expanded_case_index(index)
        self.assertGreaterEqual(index["case_count"], 100)
        self.assertEqual(set(index["year_counts"]), {str(year) for year in range(2020, 2027)})
        self.assertGreaterEqual(index["business_model_counts"]["b2b"], 20)
        self.assertGreaterEqual(index["business_model_counts"]["b2c"], 50)
        self.assertGreaterEqual(index["business_model_counts"]["mixed"], 3)
        self.assertGreaterEqual(index["business_model_counts"]["public_interest"], 5)
        self.assertGreaterEqual(len(index["industry_family_counts"]), 80)
        self.assertGreaterEqual(index["official_source_page_count"], 20)

    def test_discovery_rows_are_never_training_eligible(self) -> None:
        index = _index()
        self.assertTrue(all(case["training_eligible"] is False for case in index["cases"]))
        self.assertTrue(
            all(case["promotion_status"] == "pending_case_level_claim_audit" for case in index["cases"])
        )

    def test_missing_promotion_evidence_fails(self) -> None:
        cases = copy.deepcopy(_index()["cases"])
        cases[0]["required_next_evidence"].remove("causal_confounds")
        with self.assertRaisesRegex(GTMBreakoutEvidenceError, "required_next_evidence"):
            compile_expanded_case_index(cases)

    def test_training_promotion_without_audit_fails(self) -> None:
        cases = copy.deepcopy(_index()["cases"])
        cases[0]["training_eligible"] = True
        with self.assertRaisesRegex(GTMBreakoutEvidenceError, "discovery-only boundary"):
            compile_expanded_case_index(cases)

    def test_non_official_source_class_fails(self) -> None:
        cases = copy.deepcopy(_index()["cases"])
        cases[0]["source_class"] = "blog"
        with self.assertRaisesRegex(GTMBreakoutEvidenceError, "official award-body"):
            compile_expanded_case_index(cases)

    def test_digest_detects_tampering(self) -> None:
        index = _index()
        tampered = copy.deepcopy(index)
        tampered["cases"][0]["campaign"] = "tampered"
        with self.assertRaisesRegex(GTMBreakoutEvidenceError, "digest"):
            verify_expanded_case_index(tampered)

    def test_promotion_queue_has_five_blocking_tasks_per_case(self) -> None:
        index = _index()
        queue = json.loads(QUEUE_ARTIFACT.read_text(encoding="utf-8"))
        verify_case_promotion_queue(queue, index)
        self.assertEqual(queue["case_count"], index["case_count"])
        self.assertEqual(queue["audit_unit_count"], index["case_count"] * 5)
        self.assertTrue(all(len(item["tasks"]) == 5 for item in queue["queue"]))
        self.assertTrue(all(item["training_eligible"] is False for item in queue["queue"]))
        self.assertGreaterEqual(queue["priority_band_counts"]["p0"], 5)

    def test_promotion_queue_tamper_fails(self) -> None:
        index = _index()
        queue = compile_case_promotion_queue(index)
        queue["queue"][0]["training_eligible"] = True
        with self.assertRaisesRegex(GTMBreakoutEvidenceError, "digest"):
            verify_case_promotion_queue(queue, index)


if __name__ == "__main__":
    unittest.main()
