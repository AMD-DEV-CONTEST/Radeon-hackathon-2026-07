from __future__ import annotations

import json
import unittest
from pathlib import Path

from prooflaunch_remix.gtm_named_capability_distillation import verify_named_capability_distillation


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "evidence/v10/gtm-named-capability-distillation-v1.json"


class GTMNamedCapabilityDistillationV1Tests(unittest.TestCase):
    def test_all_named_products_become_transferable_noncopying_capability_atoms(self) -> None:
        payload = json.loads(OUTPUT.read_text(encoding="utf-8"))
        verify_named_capability_distillation(payload)
        self.assertEqual(payload["category_count"], 13)
        self.assertEqual(payload["capability_atom_count"], 130)
        self.assertEqual({row["reference_product_count"] for row in payload["categories"]}, {10})
        self.assertTrue(all(len(row["mechanism_repertoire"]) == 10 for row in payload["categories"]))
        self.assertTrue(all(row["distillation_boundary"]["transfer_mechanism_only"] for row in payload["capability_atoms"]))
        self.assertTrue(all(not row["distillation_boundary"]["copy_source_output"] for row in payload["capability_atoms"]))
        self.assertEqual(payload["completed_named_product_comparison_count"], 0)
        self.assertEqual(payload["effect_aligned_row_count"], 0)
        self.assertFalse(payload["portfolio_curriculum"]["automatic_winner_selection"])


if __name__ == "__main__":
    unittest.main()
