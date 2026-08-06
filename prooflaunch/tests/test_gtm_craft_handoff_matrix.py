from __future__ import annotations

import json
import unittest
from pathlib import Path

from scripts.compile_gtm_craft_handoff_matrix import (
    compile_gtm_craft_handoff_matrix,
)


ROOT = Path(__file__).resolve().parents[1]


class GTMCraftHandoffMatrixTests(unittest.TestCase):
    def test_matrix_quantifies_real_work_orders_not_only_role_inventory(self) -> None:
        payload = compile_gtm_craft_handoff_matrix()
        coverage = payload["coverage"]
        self.assertEqual(coverage["context_count"], 144)
        self.assertEqual(coverage["territory_handoff_count"], 432)
        self.assertEqual(coverage["distinct_workflow_signature_count"], 432)
        self.assertEqual(coverage["total_work_order_count"], 3888)
        self.assertEqual(coverage["selected_atomic_skill_assignment_count"], 18144)
        self.assertEqual(coverage["professional_axis_assignment_count"], 181440)
        self.assertEqual(coverage["surface_specialist_lens_assignment_count"], 15552)
        self.assertEqual(coverage["unconventional_edge_play_binding_count"], 3888)
        self.assertEqual(coverage["producer_reviewer_separation_pass_count"], 432)
        self.assertEqual(coverage["human_release_required_count"], 432)
        self.assertEqual(coverage["maximum_model_calls_across_all_territories"], 3456)
        self.assertEqual(coverage["automatic_external_action_count"], 0)

    def test_checked_in_matrix_matches_compiler(self) -> None:
        expected = compile_gtm_craft_handoff_matrix()
        observed = json.loads(
            (ROOT / "evidence/v10/gtm-craft-handoff-matrix-v1.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(observed, expected)
