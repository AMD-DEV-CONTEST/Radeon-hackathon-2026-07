from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from prooflaunch_remix.gtm_control_plane_named_pk import AD_SCHEMA, AGENT_SCHEMA, MEMORY_SCHEMA, ControlPlaneNamedPKError, compile_control_plane, verify


ROOT = Path(__file__).resolve().parents[1]
LINEAGE = [{"path": f"asset-{index}", "bytes": 1, "sha256": char * 64} for index, char in enumerate("abcd", 1)]


class ControlPlaneNamedPKTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = json.loads((ROOT / "config/codex-control-plane-super-challengers-v1.json").read_text(encoding="utf-8"))

    def test_compiles_three_truthful_ten_product_candidates(self) -> None:
        memory, agent, ads = compile_control_plane(self.config, lineage=LINEAGE)
        verify(memory, MEMORY_SCHEMA)
        verify(agent, AGENT_SCHEMA)
        verify(ads, AD_SCHEMA)
        self.assertEqual(len(memory["opponent_stress_tests"]), 10)
        self.assertEqual(len(agent["opponent_stress_tests"]), 10)
        self.assertEqual(len(ads["opponent_stress_tests"]), 10)
        self.assertIsNone(ads["experiment"]["observed_incremental_lift"])

    def test_rejects_fabricated_ad_lift(self) -> None:
        mutated = copy.deepcopy(self.config)
        mutated["advertising_system"]["experiment"]["observed_incremental_lift"] = 0.42
        with self.assertRaises(ControlPlaneNamedPKError):
            compile_control_plane(mutated, lineage=LINEAGE)

    def test_rejects_external_authority(self) -> None:
        mutated = copy.deepcopy(self.config)
        mutated["employee_agent"]["harness"]["hard_limits"]["external_actions"] = 1
        with self.assertRaises(ControlPlaneNamedPKError):
            compile_control_plane(mutated, lineage=LINEAGE)


if __name__ == "__main__":
    unittest.main()
