from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from prooflaunch_remix.gtm_creative_alpha_flightbook import CreativeAlphaFlightbookError, compile_flightbook, verify


ROOT = Path(__file__).resolve().parents[1]


class CreativeAlphaFlightbookTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = json.loads((ROOT / "config/codex-creative-alpha-flightbook-v1.json").read_text(encoding="utf-8"))
        self.b2b = json.loads((ROOT / "artifacts/gtm-last-mile-pk-v1/platform-native-challengers-v6/b2b-gold-reference-v1-receipt.json").read_text(encoding="utf-8"))
        self.b2c = json.loads((ROOT / "artifacts/gtm-last-mile-pk-v1/platform-native-challengers-v14/b2c-codex-reference-v1-receipt.json").read_text(encoding="utf-8"))
        self.kernel = json.loads((ROOT / "evidence/v10/gtm-human-capability-kernel-v2.json").read_text(encoding="utf-8"))
        self.bindings = [{"path": str(index), "bytes": 1, "sha256": char * 64} for index, char in enumerate("abcd")]

    def compile(self):
        return compile_flightbook(self.config, b2b_receipt=self.b2b, b2c_receipt=self.b2c, human_kernel=self.kernel, source_bindings=self.bindings)

    def test_compiles_26_surface_candidates_and_10x_team_kernel(self) -> None:
        payload = self.compile()
        verify(payload)
        self.assertEqual(payload["candidate_count"], 26)
        self.assertEqual(payload["team_operating_system"]["role_count"], 22)
        self.assertEqual(payload["team_operating_system"]["professional_axis_count"], 2200)
        self.assertEqual(len(payload["unconventional_edge_play_cards"]), 26)
        self.assertTrue(all(len(case["focused_candidates"]) == 2 for case in payload["cases"]))

    def test_rejects_duplicate_surface_candidate(self) -> None:
        mutated = copy.deepcopy(self.b2b)
        mutated["accepted_candidates"][1]["content_sha256"] = mutated["accepted_candidates"][0]["content_sha256"]
        with self.assertRaises(CreativeAlphaFlightbookError):
            compile_flightbook(self.config, b2b_receipt=mutated, b2c_receipt=self.b2c, human_kernel=self.kernel, source_bindings=self.bindings)

    def test_rejects_publishable_synthetic_b2c_case(self) -> None:
        mutated = copy.deepcopy(self.config)
        mutated["cases"]["b2c"]["case_status"] = "publishable"
        with self.assertRaises(CreativeAlphaFlightbookError):
            compile_flightbook(mutated, b2b_receipt=self.b2b, b2c_receipt=self.b2c, human_kernel=self.kernel, source_bindings=self.bindings)


if __name__ == "__main__":
    unittest.main()
