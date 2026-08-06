from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PreferenceCorpusTests(unittest.TestCase):
    def test_independent_audit_proves_exact_5k_contract_negative_pairs(self) -> None:
        report = json.loads(
            (ROOT / "evidence/v10/preference-pairs-5k-independent-audit.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(report["status"], "passed_independent_audit_not_training")
        self.assertEqual(report["pair_count"], 5_000)
        self.assertEqual(report["train_count"], 4_500)
        self.assertEqual(report["validation_count"], 500)
        self.assertEqual(report["error_kind_counts"], {
            "evidence_source_substitution": 1_000,
            "required_output_omitted": 1_000,
            "unapproved_external_action": 1_000,
            "unobserved_modality_inference": 1_000,
            "unsupported_outcome_claim": 1_000,
        })
        self.assertEqual(report["stage_count"], 14)
        self.assertEqual(report["input_kind_count"], 9)
        self.assertEqual(report["failure_count"], 0)
        self.assertFalse(report["training_observed"])


if __name__ == "__main__":
    unittest.main()
