from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

from scripts.compile_gtm_effect_alignment_benchmark import build_benchmark, render_markdown


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "evidence/v10/gtm-ten-peer-effect-alignment-benchmark-v1.json"
REPORT = ROOT / "docs/product/GTM_TEN_PEER_EFFECT_ALIGNMENT_BENCHMARK_V1.md"


class GTMEffectAlignmentBenchmarkTests(unittest.TestCase):
    def test_sealed_outputs_match_current_compiler(self) -> None:
        sealed = json.loads(EVIDENCE.read_text(encoding="utf-8"))
        self.assertEqual(sealed, build_benchmark())
        self.assertEqual(REPORT.read_text(encoding="utf-8"), render_markdown(sealed))

    def test_all_thirteen_categories_have_ten_products_and_deep_action_contracts(self) -> None:
        sealed = json.loads(EVIDENCE.read_text(encoding="utf-8"))
        self.assertEqual(sealed["category_count"], 13)
        self.assertEqual(sealed["reference_product_count"], 130)
        self.assertEqual(len(sealed["categories"]), 13)
        for row in sealed["categories"]:
            self.assertEqual(len(row["reference_products"]), 10)
            self.assertGreaterEqual(len(row["benchmark_axes"]), 8)
            self.assertGreaterEqual(len(row["open_source_projects"]), 3)
            self.assertGreaterEqual(len(row["algorithms"]), 5)
            self.assertTrue(row["candidate_models"])
            self.assertTrue(row["current_evidence"])
            self.assertTrue(row["effect_gate"])
            self.assertTrue(row["last_mile_quality_gate"])
            self.assertTrue(row["business_outcome_gate"])
            self.assertRegex(row["next_action"], r"^P[0-2]:")
            self.assertFalse(row["last_mile_execution_quality_alignment_achieved"])
            self.assertFalse(row["business_outcome_observed"])
            self.assertFalse(row["effect_alignment_achieved"])

    def test_truth_boundary_forbids_parity_and_effect_overclaim(self) -> None:
        sealed = json.loads(EVIDENCE.read_text(encoding="utf-8"))
        self.assertFalse(sealed["portfolio_effect_alignment_achieved"])
        self.assertFalse(
            sealed["portfolio_last_mile_execution_quality_alignment_achieved"]
        )
        self.assertFalse(sealed["portfolio_business_outcome_observed"])
        self.assertEqual(
            sealed["effect_definition"]["primary"],
            "last_mile_generated_execution_quality",
        )
        self.assertGreaterEqual(len(sealed["last_mile_quality_blockers"]), 4)
        self.assertGreaterEqual(len(sealed["business_outcome_blockers"]), 2)
        self.assertGreaterEqual(len(sealed["portfolio_blockers"]), 5)
        boundary = sealed["truth_boundary"]
        self.assertIn("does not prove a global ranking", boundary)
        self.assertIn("4A quality", boundary)
        self.assertIn("independent axes", boundary)

    def test_content_digest_covers_all_130_references(self) -> None:
        sealed = json.loads(EVIDENCE.read_text(encoding="utf-8"))
        supplied = sealed.pop("content_sha256")
        encoded = json.dumps(sealed, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        self.assertEqual(supplied, hashlib.sha256(encoded.encode("utf-8")).hexdigest())


if __name__ == "__main__":
    unittest.main()
