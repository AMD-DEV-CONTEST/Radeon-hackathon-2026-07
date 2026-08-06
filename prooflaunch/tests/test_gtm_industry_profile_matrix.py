from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "evidence/v10/gtm-industry-profile-matrix-v1.json"


class IndustryProfileMatrixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.matrix = json.loads(EVIDENCE.read_text(encoding="utf-8"))

    def test_matrix_covers_every_frozen_dimension(self) -> None:
        self.assertEqual(self.matrix["schema"], "ProofLaunchIndustryGTMProfileMatrixV1")
        self.assertEqual(self.matrix["archetype_count"], 20)
        self.assertEqual(self.matrix["specific_archetype_count"], 18)
        self.assertEqual(self.matrix["business_model_count"], 2)
        self.assertEqual(self.matrix["lifecycle_count"], 4)
        self.assertEqual(self.matrix["budget_count"], 3)
        self.assertEqual(self.matrix["case_count"], 456)
        self.assertEqual(self.matrix["case_count"], self.matrix["expected_case_count"])
        self.assertEqual(self.matrix["zero_budget_case_count"], 152)
        self.assertEqual(self.matrix["regulated_case_count"], 72)

    def test_matrix_proves_nontrivial_industry_differentiation(self) -> None:
        self.assertEqual(self.matrix["distinct_zero_budget_engine_count"], 20)
        self.assertEqual(self.matrix["distinct_conversion_unit_count"], 20)
        self.assertEqual(self.matrix["distinct_unit_economics_signature_count"], 20)
        self.assertGreater(self.matrix["business_model_mismatch_case_count"], 0)
        self.assertGreaterEqual(
            self.matrix["human_confirmation_case_count"],
            self.matrix["business_model_mismatch_case_count"],
        )

    def test_all_cases_fail_closed_on_activation_budget_and_causal_claims(self) -> None:
        self.assertTrue(self.matrix["all_external_activation_disabled"])
        self.assertTrue(self.matrix["all_automatic_budget_allocation_disabled"])
        self.assertTrue(self.matrix["all_causal_revenue_claims_disabled"])
        self.assertTrue(all(row["external_activation_executed"] is False for row in self.matrix["cases"]))
        self.assertTrue(all(row["automatic_budget_allocation_enabled"] is False for row in self.matrix["cases"]))
        self.assertTrue(all(row["causal_revenue_claim_allowed"] is False for row in self.matrix["cases"]))

    def test_content_digest_binds_the_complete_matrix(self) -> None:
        payload = dict(self.matrix)
        supplied = payload.pop("content_sha256")
        expected = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        self.assertEqual(supplied, expected)


if __name__ == "__main__":
    unittest.main()
