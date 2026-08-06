from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "evidence/v10/local-gtm-creative-effect-audit-v1.json"


def canonical(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


class LocalGTMCreativeEffectAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.payload = json.loads(AUDIT.read_text(encoding="utf-8"))

    def test_audit_is_hash_bound_and_all_sources_match(self) -> None:
        unsigned = dict(self.payload)
        supplied = unsigned.pop("content_sha256")
        self.assertEqual(
            supplied, hashlib.sha256(canonical(unsigned).encode()).hexdigest()
        )
        for relative, expected in self.payload["source_file_sha256"].items():
            self.assertEqual(
                hashlib.sha256((ROOT / relative).read_bytes()).hexdigest(), expected
            )

    def test_effect_gate_requires_scenario_channel_and_expression_evidence(self) -> None:
        gate = self.payload["final_gate"]
        self.assertTrue(gate["passed"])
        self.assertEqual(gate["observed_case_count"], 9)
        self.assertEqual(gate["observed_candidate_count"], 27)
        self.assertEqual(gate["observed_channel_draft_count"], 54)
        self.assertEqual(gate["covered_channel_type_count"], 12)
        self.assertTrue(gate["all_candidates_have_two_native_markers"])
        self.assertTrue(gate["all_four_dimension_scenario_gates_pass"])
        self.assertLessEqual(
            gate["maximum_cross_scenario_pair_jaccard"],
            gate["maximum_allowed_pair_jaccard"],
        )
        self.assertGreater(gate["v8_to_final_jaccard_reduction"], 0)

    def test_truth_boundary_preserves_unproven_human_and_business_effects(self) -> None:
        self.assertFalse(self.payload["human_review_completed"])
        self.assertFalse(self.payload["winner_selected"])
        self.assertFalse(self.payload["radeon_local_inference_observed"])
        self.assertEqual(self.payload["cloud_api_calls"], 0)
        self.assertIn("does not prove human creative preference", self.payload["truth_boundary"])


if __name__ == "__main__":
    unittest.main()
