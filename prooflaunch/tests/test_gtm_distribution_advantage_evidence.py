from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

from scripts.compile_gtm_distribution_advantage_matrix import build_matrix


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "evidence/v10/gtm-distribution-advantage-matrix-v2.json"


class DistributionAdvantageEvidenceTests(unittest.TestCase):
    def test_sealed_matrix_matches_the_current_compiler(self) -> None:
        self.assertTrue(EVIDENCE.is_file())
        sealed = json.loads(EVIDENCE.read_text(encoding="utf-8"))
        self.assertEqual(sealed, build_matrix())

    def test_matrix_covers_1920_contexts_and_preserves_all_hard_boundaries(self) -> None:
        sealed = json.loads(EVIDENCE.read_text(encoding="utf-8"))
        cases = sealed["cases"]
        self.assertEqual(sealed["scenario_count"], 1_920)
        self.assertEqual(len(cases), 1_920)
        self.assertEqual(len({case["case_id"] for case in cases}), 1_920)
        self.assertEqual(len({case["strategy_id"] for case in cases}), 1_920)
        self.assertTrue(
            all(len(case["focus_channels"]) == 2 for case in cases)
        )
        self.assertTrue(
            all(len(case["test_channels"]) <= 2 for case in cases)
        )
        self.assertTrue(
            all(len(case["frontier_channels"]) == 4 for case in cases)
        )
        self.assertTrue(
            all(case["zero_budget_paid_exclusion_passed"] for case in cases)
        )
        self.assertTrue(
            all(case["automatic_activation_executed"] is False for case in cases)
        )
        self.assertTrue(
            all(case["automatic_reallocation_executed"] is False for case in cases)
        )
        self.assertEqual(
            {case["decision_confidence"] for case in cases},
            {"low", "medium", "high"},
        )

    def test_content_digest_covers_every_case(self) -> None:
        sealed = json.loads(EVIDENCE.read_text(encoding="utf-8"))
        supplied = sealed.pop("content_sha256")
        encoded = json.dumps(
            sealed,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        self.assertEqual(
            supplied,
            hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
        )


if __name__ == "__main__":
    unittest.main()
