from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

from scripts.compile_gtm_distribution_advantage_research import (
    build_research_evidence,
)


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = (
    ROOT / "evidence/v10/gtm-distribution-advantage-research-2026-08-02.json"
)


class DistributionAdvantageResearchTests(unittest.TestCase):
    def test_sealed_research_matches_current_compiler(self) -> None:
        self.assertTrue(EVIDENCE.is_file())
        sealed = json.loads(EVIDENCE.read_text(encoding="utf-8"))
        self.assertEqual(sealed, build_research_evidence())

    def test_sources_cover_product_data_agent_and_geo_patterns(self) -> None:
        sealed = json.loads(EVIDENCE.read_text(encoding="utf-8"))
        self.assertEqual(sealed["source_count"], 8)
        self.assertEqual(len(sealed["sources"]), 8)
        self.assertEqual(
            {row["publisher"] for row in sealed["sources"]},
            {"Salesforce", "Hootsuite", "PostHog", "Ahrefs", "arXiv"},
        )
        self.assertTrue(
            all(row["url"].startswith("https://") for row in sealed["sources"])
        )
        self.assertTrue(
            all(row["derived_requirement"] for row in sealed["sources"])
        )
        self.assertEqual(len(sealed["implemented_contracts"]), 4)

    def test_truth_boundary_forbids_market_and_effect_overclaim(self) -> None:
        sealed = json.loads(EVIDENCE.read_text(encoding="utf-8"))
        non_goals = " ".join(sealed["explicit_non_goals"])
        self.assertIn("no unsupported global_top_10 ranking", non_goals)
        self.assertIn("no automatic channel activation", non_goals)
        self.assertIn("no claim that a score predicts", non_goals)
        self.assertIn("not an exhaustive market ranking", sealed["truth_boundary"])
        self.assertIn("proof of 4A/Top-1 performance", sealed["truth_boundary"])

    def test_content_digest_covers_every_source_and_contract(self) -> None:
        sealed = json.loads(EVIDENCE.read_text(encoding="utf-8"))
        supplied = sealed.pop("content_sha256")
        encoded = json.dumps(
            sealed,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        self.assertEqual(
            supplied,
            hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
        )


if __name__ == "__main__":
    unittest.main()
