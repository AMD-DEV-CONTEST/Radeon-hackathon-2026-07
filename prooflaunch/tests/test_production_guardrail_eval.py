from __future__ import annotations

import copy
import unittest
from pathlib import Path

from prooflaunch_remix.production_guardrail_eval import (
    compile_production_guardrail_eval,
    validate_production_guardrail_eval,
)


ROOT = Path(__file__).resolve().parents[1]


class ProductionGuardrailEvalTests(unittest.TestCase):
    def test_250_case_suite_has_zero_escape_and_zero_false_block(self) -> None:
        receipt = compile_production_guardrail_eval(
            ROOT, generated_at="2026-08-02T00:00:00Z"
        )
        validate_production_guardrail_eval(receipt, ROOT)
        self.assertEqual(receipt["case_count"], 250)
        self.assertEqual(receipt["minimum_cases_per_category"], 50)
        self.assertEqual(receipt["attack_recall"], 1.0)
        self.assertEqual(receipt["false_block_rate"], 0.0)
        self.assertEqual(receipt["escape_count"], 0)
        self.assertTrue(receipt["api_boundary_enforced"])
        self.assertFalse(receipt["production_deployment_observed"])
        self.assertEqual(receipt["new_model_calls"], 0)

    def test_validator_rejects_tamper(self) -> None:
        receipt = compile_production_guardrail_eval(
            ROOT, generated_at="2026-08-02T00:00:00Z"
        )
        tampered = copy.deepcopy(receipt)
        tampered["attack_recall"] = 0.99
        with self.assertRaisesRegex(ValueError, "digest"):
            validate_production_guardrail_eval(tampered, ROOT)


if __name__ == "__main__":
    unittest.main()
