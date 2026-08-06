from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from prooflaunch_remix.gtm_decision_intelligence_named_pk import DecisionIntelligenceNamedPKError, MEMO_SCHEMA, MEASUREMENT_SCHEMA, compile_decision_intelligence, verify


ROOT = Path(__file__).resolve().parents[1]
LINEAGE = [{"role": role, "path": role, "bytes": 1, "sha256": char * 64} for role, char in (("text", "a"), ("schedule", "b"), ("image", "c"))]


class DecisionIntelligenceNamedPKTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = json.loads((ROOT / "config/codex-decision-intelligence-super-challengers-v1.json").read_text(encoding="utf-8"))

    def test_compiles_two_truthful_ten_product_candidates(self) -> None:
        memo, measurement = compile_decision_intelligence(self.config, lineage=LINEAGE)
        verify(memo, MEMO_SCHEMA)
        verify(measurement, MEASUREMENT_SCHEMA)
        self.assertEqual(len(memo["opponent_stress_tests"]), 10)
        self.assertEqual(len(measurement["opponent_stress_tests"]), 10)
        self.assertIsNone(measurement["primary_metric"]["value"])
        self.assertFalse(measurement["incrementality"]["causal_claim_allowed"])

    def test_rejects_fabricated_metric(self) -> None:
        mutated = copy.deepcopy(self.config)
        mutated["measurement_system"]["primary_metric"]["value"] = 0.8
        with self.assertRaises(DecisionIntelligenceNamedPKError):
            compile_decision_intelligence(mutated, lineage=LINEAGE)


if __name__ == "__main__":
    unittest.main()
