from __future__ import annotations

import json
import unittest
from pathlib import Path

from prooflaunch_remix.v10_agentic_gtm_benchmark import score_agentic_gtm_output


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "data" / "v10_gtm_bench" / "agentic-scoring-fixtures.json"
OBSERVED_RECEIPT = ROOT / "evidence" / "v10" / "agentic-gtm-flagship-benchmark-2026-07-31.json"


class AgenticGtmBenchmarkTests(unittest.TestCase):
    def test_rights_clear_synthetic_candidate_passes_strict_gate(self) -> None:
        payload = json.loads(FIXTURES.read_text(encoding="utf-8"))
        score = score_agentic_gtm_output(
            json.dumps(payload["eligible_synthetic_output"], ensure_ascii=False)
        )
        self.assertTrue(score.promotion_eligible)

    def test_synthetic_baseline_does_not_pass_without_tools_or_dag(self) -> None:
        payload = json.loads(FIXTURES.read_text(encoding="utf-8"))
        score = score_agentic_gtm_output(
            json.dumps(payload["ineligible_synthetic_output"], ensure_ascii=False)
        )
        self.assertFalse(score.promotion_eligible)
        self.assertFalse(score.tool_calls_valid)
        self.assertFalse(score.dependency_graph_valid)

        observed = json.loads(OBSERVED_RECEIPT.read_text(encoding="utf-8"))
        self.assertFalse(observed["truth_boundary"]["raw_outputs_public_archive_eligible"])
        self.assertEqual(observed["training_admission"]["status"], "blocked")

    def test_invalid_or_truncated_json_fails_closed(self) -> None:
        score = score_agentic_gtm_output('{"decision":"launch"')
        self.assertFalse(score.json_valid)
        self.assertFalse(score.promotion_eligible)


if __name__ == "__main__":
    unittest.main()
