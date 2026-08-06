from __future__ import annotations

import json
import unittest
from pathlib import Path

from prooflaunch_remix.gtm_named_pk_learning_bridge import (
    GTMNamedPKLearningBridgeError,
    compile_named_pk_learning_bridge,
)


ROOT = Path(__file__).resolve().parents[1]


class GTMNamedPKLearningBridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        portfolio = json.loads((ROOT / "evidence/v10/gtm-multimodal-breakout-factory-v1.json").read_text(encoding="utf-8"))
        cls.factory = portfolio["factories"][0]
        cls.distillation = json.loads((ROOT / "evidence/v10/gtm-named-capability-distillation-v1.json").read_text(encoding="utf-8"))
        category = next(row for row in cls.distillation["categories"] if row["category_id"] == "text_content_generation")
        cls.products = category["reference_products"]
        candidate = cls.factory["candidate_campaigns"][0]
        cls.genome_id = candidate["genome_id"]
        blueprint = next(row for row in cls.factory["creative_kernel"]["candidate_blueprints"] if row["genome_id"] == cls.genome_id)
        cls.pairs = [f"hook:{blueprint['genome']['hook']['id']}", f"narrative:{blueprint['genome']['narrative']['id']}"]

    def _rows(self, *, critical_defect: bool = False):
        return [{
            "reference_product": product,
            "candidate_genome_id": self.genome_id,
            "reviewer_ids": [f"reviewer-{index}-{n}" for n in range(5)],
            "source_hidden": True,
            "authorized_baseline_present": True,
            "candidate_preference_rate": 1.0,
            "wilson_lower_95": 0.565,
            "direct_publishable_rate": 1.0,
            "major_rework_rate": 0.0,
            "critical_defect_count": 1 if critical_defect and index == 0 else 0,
            "diagnostic_axis_pairs": list(self.pairs),
            "evidence_sha256": f"{index + 1:064x}"[-64:],
            "approved_by": "named-creative-owner",
            "human_approved": True,
        } for index, product in enumerate(self.products)]

    def test_ten_of_ten_passes_create_one_next_run_promote_prior(self) -> None:
        bridge = compile_named_pk_learning_bridge(
            factory=self.factory, distillation=self.distillation,
            category_id="text_content_generation", review_rows=self._rows(),
        )
        self.assertEqual(bridge["named_product_review_count"], 10)
        self.assertEqual(bridge["verdict"], "promote")
        self.assertTrue(bridge["all_rows_passed"])
        self.assertEqual(bridge["learning_memory"]["record_count"], 1)
        self.assertEqual(bridge["learning_memory"]["records"][0]["axis_pairs"], sorted(self.pairs))
        self.assertFalse(bridge["current_run_mutation"])

    def test_missing_tenth_product_and_one_critical_defect_fail_closed(self) -> None:
        with self.assertRaisesRegex(GTMNamedPKLearningBridgeError, "exactly ten"):
            compile_named_pk_learning_bridge(
                factory=self.factory, distillation=self.distillation,
                category_id="text_content_generation", review_rows=self._rows()[:9],
            )
        retired = compile_named_pk_learning_bridge(
            factory=self.factory, distillation=self.distillation,
            category_id="text_content_generation", review_rows=self._rows(critical_defect=True),
        )
        self.assertEqual(retired["verdict"], "retire")
        self.assertFalse(retired["all_rows_passed"])


if __name__ == "__main__":
    unittest.main()
