from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from prooflaunch_remix.gtm_search_answer_named_pk import GEO_SCHEMA, SEO_SCHEMA, SearchAnswerNamedPKError, compile_search_answer, verify


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = [{"role": role, "path": role, "bytes": 1, "sha256": char * 64} for role, char in (("claim", "a"), ("authority", "b"), ("measurement", "c"))]


class SearchAnswerNamedPKTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = json.loads((ROOT / "config/codex-search-answer-super-challengers-v1.json").read_text(encoding="utf-8"))

    def test_compiles_real_page_and_two_ten_product_candidates(self) -> None:
        seo, geo, document = compile_search_answer(self.config, evidence=EVIDENCE)
        verify(seo, SEO_SCHEMA)
        verify(geo, GEO_SCHEMA)
        self.assertEqual(len(seo["opponent_stress_tests"]), 10)
        self.assertEqual(len(geo["opponent_stress_tests"]), 10)
        self.assertEqual(len(geo["faqs"]), 6)
        self.assertIn("How to evaluate an AI GTM agent", document)
        self.assertIn('name="robots" content="noindex,nofollow"', document)
        self.assertIsNone(geo["measured_answer_share"])

    def test_rejects_fabricated_geo_run(self) -> None:
        mutated = copy.deepcopy(self.config)
        mutated["geo_measurement_panel"]["status"] = "passed"
        with self.assertRaises(SearchAnswerNamedPKError):
            compile_search_answer(mutated, evidence=EVIDENCE)


if __name__ == "__main__":
    unittest.main()
