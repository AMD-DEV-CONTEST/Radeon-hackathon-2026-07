from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from prooflaunch_remix.gtm_lifecycle_named_pk import GTMLifecycleNamedPKError, compile_lifecycle, verify_lifecycle


ROOT = Path(__file__).resolve().parents[1]
BINDINGS = [
    {"role": "strategy_and_creative", "path": "a", "bytes": 1, "sha256": "a" * 64},
    {"role": "text_assets", "path": "b", "bytes": 1, "sha256": "b" * 64},
    {"role": "content_schedule", "path": "c", "bytes": 1, "sha256": "c" * 64},
]


class GTMLifecycleNamedPKTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = json.loads((ROOT / "config/codex-gtm-lifecycle-named-pk-super-challenger-v1.json").read_text(encoding="utf-8"))

    def test_compiles_team_graph_harness_and_truth_boundary(self) -> None:
        result = compile_lifecycle(self.config, bindings=BINDINGS)
        verify_lifecycle(result)
        self.assertEqual(result["graph"]["node_count"], 10)
        self.assertEqual(len(result["team_cells"]), 8)
        self.assertEqual(len(result["opponent_stress_tests"]), 10)
        self.assertFalse(result["release_eligible"])

    def test_fails_closed_when_publish_block_is_removed(self) -> None:
        mutated = copy.deepcopy(self.config)
        mutated["harness"]["blocked"].remove("automatic publication")
        with self.assertRaises(GTMLifecycleNamedPKError):
            compile_lifecycle(mutated, bindings=BINDINGS)

    def test_v2_exposes_twelve_specialist_cells_and_response_learning_binding(self) -> None:
        config = json.loads(
            (ROOT / "config/codex-gtm-lifecycle-named-pk-super-challenger-v2.json").read_text(encoding="utf-8")
        )
        bindings = [*BINDINGS, {"role": "response_learning_contract", "path": "d", "bytes": 1, "sha256": "d" * 64}]
        result = compile_lifecycle(config, bindings=bindings)
        verify_lifecycle(result)
        self.assertEqual(len(result["team_cells"]), 12)
        self.assertTrue(all({"skills", "quality_gate", "failure_signature", "scorecard"}.issubset(cell) for cell in result["team_cells"]))
        self.assertEqual({row["role"] for row in result["asset_bindings"]}, {"text_assets", "content_schedule", "response_learning_contract"})
        self.assertIn("model judge counted as human preference", result["harness"]["blocked"])
        self.assertEqual(result["completed_named_product_pk_count"], 0)
        self.assertEqual(result["candidate_win_count"], 0)


if __name__ == "__main__":
    unittest.main()
