from __future__ import annotations

import copy
import unittest
from pathlib import Path

from prooflaunch_remix.gtm_context_quality import (
    compile_gtm_context_quality,
    validate_gtm_context_quality,
)


ROOT = Path(__file__).resolve().parents[1]


class GTMContextQualityTests(unittest.TestCase):
    def test_observed_tokens_and_long_session_preservation_pass(self) -> None:
        receipt = compile_gtm_context_quality(
            ROOT, generated_at="2026-08-02T00:00:00Z"
        )
        validate_gtm_context_quality(receipt, ROOT)
        self.assertEqual(receipt["observed_local_call_count"], 24)
        self.assertLess(receipt["median_context_utilization"], 0.40)
        self.assertLess(receipt["p95_context_utilization"], 0.60)
        self.assertEqual(receipt["long_session_eval_count"], 24)
        self.assertGreaterEqual(receipt["minimum_long_session_message_count"], 60)
        self.assertEqual(receipt["critical_state_preservation_count"], 24)
        self.assertEqual(receipt["archived_canary_exclusion_count"], 24)
        self.assertEqual(receipt["new_model_calls"], 0)

    def test_validator_rejects_tampered_gate(self) -> None:
        receipt = compile_gtm_context_quality(
            ROOT, generated_at="2026-08-02T00:00:00Z"
        )
        tampered = copy.deepcopy(receipt)
        tampered["critical_state_preservation_count"] = 23
        with self.assertRaisesRegex(ValueError, "digest"):
            validate_gtm_context_quality(tampered, ROOT)


if __name__ == "__main__":
    unittest.main()
