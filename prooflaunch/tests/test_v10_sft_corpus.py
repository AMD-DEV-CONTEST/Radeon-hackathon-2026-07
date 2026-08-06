from __future__ import annotations

import json
import unittest
from pathlib import Path

from prooflaunch_remix.v10_contracts import V10ContractError
from prooflaunch_remix.v10_sft_corpus import TARGET_SFT_EPISODES, verify_sft_summary


ROOT = Path(__file__).resolve().parents[1]


class SFTCorpusTests(unittest.TestCase):
    def test_independent_audit_proves_exact_15k_without_training_claim(self) -> None:
        report = json.loads(
            (ROOT / "evidence/v10/sft-corpus-15k-independent-audit.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(report["status"], "passed_independent_audit_not_training")
        self.assertEqual(report["episode_count"], TARGET_SFT_EPISODES)
        self.assertEqual(report["train_count"], 13_500)
        self.assertEqual(report["validation_count"], 1_500)
        self.assertEqual(len(report["stage_counts"]), 14)
        self.assertEqual(len(report["input_counts"]), 9)
        self.assertEqual(report["failure_count"], 0)
        self.assertEqual(report["failures"], [])
        self.assertTrue(report["all_records_revalidated"])
        self.assertFalse(report["training_observed"])
        self.assertFalse(report["adapter_observed"])

    def test_summary_rejects_count_rights_and_distribution_drift(self) -> None:
        summary = json.loads(
            (ROOT / "data/v10_sft_corpus/manifest.json").read_text(encoding="utf-8")
        )
        verify_sft_summary(summary)
        for key in ("episode_count", "rights_failure_count"):
            broken = dict(summary)
            broken[key] += 1
            with self.assertRaises(V10ContractError):
                verify_sft_summary(broken)


if __name__ == "__main__":
    unittest.main()
