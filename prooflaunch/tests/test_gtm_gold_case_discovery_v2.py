from __future__ import annotations

import copy
import hashlib
import unittest

from prooflaunch_remix.gtm_gold_case_discovery_v2 import (
    GTMGoldCaseDiscoveryError,
    build_query_matrix,
    compile_gold_case_discovery,
    extract_athena_manufacturing_case_cards,
    extract_hubspot_directory_cards,
    extract_industrial_case_directory_cards,
    extract_tiktok_directory_cards,
    extend_gold_case_discovery,
    verify_gold_case_discovery,
)


HTML = """
<ul>
  <li class="csl-directory-cards__card directory-card-shown" data-industry="Manufacturing"
      data-size="25-200 employees" data-products="[Marketing Hub]" data-usecases="[Build Pipeline]"
      data-sort="[Newest]">
    <img alt="Acme Machinery">
    <h3 class="csl-card-title cl-h5">Acme makes industrial equipment visible</h3>
    <ul><li class="csl-card-tag">Manufacturing</li><li class="csl-card-tag">Build Pipeline</li></ul>
    <a href="https://www.hubspot.com/case-studies/acme?ref=directory">Read more</a>
  </li>
  <li class="csl-directory-cards__card" data-industry="Consumer Goods" data-size="1-25 employees"
      data-products="[Marketing Hub]" data-usecases="[Increase Leads]" data-sort="[Featured]">
    <img alt="Glow Co">
    <h3 class="csl-card-title">Glow launches a skincare routine</h3>
    <ul><li class="csl-card-tag">Consumer Goods</li></ul>
    <a href="https://www.hubspot.com/case-studies/glow/">Read more</a>
  </li>
</ul>
"""

TIKTOK_HTML = """
<div class="tt4b-aggregator-card-container"><div data-click_for="case_study"
 data-url="/business/en-US/inspiration/glow-case" class="card-content">
 <span class="razz">Makeup &amp; beauty</span><h3 title="Glow" class="card-title"><a>Glow</a></h3>
 <p class="card-excerpt">Creator-led skincare launch improves qualified conversion</p>
 <div class="card-time-text">July 22, 2026</div></div></div>
"""


class GTMGoldCaseDiscoveryV2Tests(unittest.TestCase):
    def _snapshot(self, html: str = HTML, url: str = "https://www.hubspot.com/case-studies/directory") -> dict:
        return {
            "source_family_id": "hubspot_case_directory",
            "source_url": url,
            "captured_at": "2026-08-05T12:00:00+00:00",
            "content_sha256": hashlib.sha256(html.encode()).hexdigest(),
            "html_text": html,
        }

    def test_extracts_and_canonicalizes_directory_cards(self) -> None:
        cards = extract_hubspot_directory_cards(HTML)
        self.assertEqual(len(cards), 2)
        self.assertEqual(cards[0]["source_url"], "https://www.hubspot.com/case-studies/acme")
        self.assertEqual(cards[0]["company"], "Acme Machinery")

    def test_builds_1200_query_matrix_and_zero_credit_leads(self) -> None:
        payload = compile_gold_case_discovery([self._snapshot()], research_cutoff="2026-08-05")
        verify_gold_case_discovery(payload)
        self.assertEqual(len(build_query_matrix()), 1200)
        self.assertEqual(payload["query_matrix_count"], 1200)
        self.assertEqual(payload["unique_discovery_lead_count"], 2)
        self.assertTrue(all(row["quota_credit"] == 0 for row in payload["records"]))
        acme = next(row for row in payload["records"] if row["company"] == "Acme Machinery")
        self.assertIn("b2b.industrial_climate.manufacturing", acme["provisional_subvertical_ids"])
        self.assertIn("b2b.industrial_climate.industrial_equipment", acme["provisional_subvertical_ids"])

    def test_extracts_tiktok_card_and_routes_exact_platform_category(self) -> None:
        cards = extract_tiktok_directory_cards(TIKTOK_HTML, "https://ads.tiktok.com/business/en-US/inspiration")
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["source_url"], "https://ads.tiktok.com/business/en-US/inspiration/glow-case")
        payload = compile_gold_case_discovery([{
            "source_family_id": "tiktok_business_success_stories",
            "source_url": "https://ads.tiktok.com/business/en-US/inspiration",
            "captured_at": "2026-08-05T12:00:00+00:00",
            "content_sha256": hashlib.sha256(TIKTOK_HTML.encode()).hexdigest(),
            "html_text": TIKTOK_HTML,
        }], research_cutoff="2026-08-05")
        self.assertEqual(payload["unique_discovery_lead_count"], 1)
        self.assertIn("b2c.beauty_fashion.beauty", payload["records"][0]["provisional_subvertical_ids"])

    def test_duplicate_snapshot_links_collapse_without_double_credit(self) -> None:
        payload = compile_gold_case_discovery([
            self._snapshot(),
            self._snapshot(url="https://www.hubspot.com/case-studies/directory/manufacturing"),
        ], research_cutoff="2026-08-05")
        self.assertEqual(payload["snapshot_count"], 2)
        self.assertEqual(payload["unique_discovery_lead_count"], 2)
        self.assertEqual(len(payload["records"][0]["source_snapshot_sha256s"]), 1)

    def test_hash_mismatch_and_tampered_credit_fail_closed(self) -> None:
        bad_snapshot = self._snapshot()
        bad_snapshot["content_sha256"] = "0" * 64
        with self.assertRaisesRegex(GTMGoldCaseDiscoveryError, "hash"):
            compile_gold_case_discovery([bad_snapshot], research_cutoff="2026-08-05")
        payload = compile_gold_case_discovery([self._snapshot()], research_cutoff="2026-08-05")
        tampered = copy.deepcopy(payload)
        tampered["records"][0]["quota_credit"] = 1
        with self.assertRaisesRegex(GTMGoldCaseDiscoveryError, "seal"):
            verify_gold_case_discovery(tampered)

    def test_targeted_public_case_page_closes_source_gap_without_credit(self) -> None:
        payload = compile_gold_case_discovery(
            [],
            research_cutoff="2026-08-05",
            targeted_leads=[{
                "source_family_id": "targeted_public_case_pages",
                "source_url": "https://example.com/industrial-equipment-case",
                "company": "Example Equipment",
                "title": "Industrial equipment growth case",
                "directory_industry": "Industrial equipment",
                "provisional_subvertical_ids": ["b2b.industrial_climate.industrial_equipment"],
            }],
        )
        verify_gold_case_discovery(payload)
        self.assertEqual(payload["targeted_lead_count"], 1)
        self.assertEqual(payload["routing_counts"]["b2b.industrial_climate.industrial_equipment"], 1)
        self.assertEqual(payload["records"][0]["quota_credit"], 0)
        self.assertFalse(payload["records"][0]["automatic_promotion_allowed"])

    def test_extracts_industrial_directory_cards_with_conservative_routes(self) -> None:
        html = """
        <div class="case-study__entry">
          <h2><a class="case-study__entry-title-link" href="/industrial-oven-case/">Industrial oven manufacturer pipeline</a></h2>
          <p class="case-study__entry-description">CapEx equipment manufacturer demand program.</p>
        </div>
        <div class="case-study__entry">
          <h2><a class="case-study__entry-title-link" href="/construction-case/">National construction company growth</a></h2>
          <p class="case-study__entry-description">A design-builder lead nurturing program.</p>
        </div>
        """
        cards = extract_industrial_case_directory_cards(html, "https://example.com/cases/")
        self.assertEqual(len(cards), 2)
        self.assertIn("b2b.industrial_climate.industrial_equipment", cards[0]["provisional_subvertical_ids"])
        self.assertIn("b2b.industrial_climate.manufacturing", cards[0]["provisional_subvertical_ids"])
        self.assertIn("b2b.industrial_climate.engineering_construction", cards[1]["provisional_subvertical_ids"])

    def test_extracts_athena_case_links_and_leaves_nonindustrial_rows_unrouted(self) -> None:
        html = """
        <a href="/case-studies/equipment-manufacturer/">Industrial Marketing Case Study</a>
        <a href="https://www.example.com/case-studies/training-provider/">Training provider</a>
        <a href="/case-studies/equipment-manufacturer/"><img alt="duplicate"></a>
        """
        cards = extract_athena_manufacturing_case_cards(html, "https://www.athenaswc.com/case-studies/")
        self.assertEqual(len(cards), 2)
        equipment = next(row for row in cards if "equipment-manufacturer" in row["source_url"])
        training = next(row for row in cards if "training-provider" in row["source_url"])
        self.assertIn("b2b.industrial_climate.manufacturing", equipment["provisional_subvertical_ids"])
        self.assertIn("b2b.industrial_climate.industrial_equipment", equipment["provisional_subvertical_ids"])
        self.assertEqual(training["provisional_subvertical_ids"], [])

    def test_extends_sealed_lineage_with_model_assisted_zero_credit_lead(self) -> None:
        base = compile_gold_case_discovery([self._snapshot()], research_cutoff="2026-08-05")
        extended = extend_gold_case_discovery(base, [{
            "source_family_id": "targeted_public_case_pages",
            "source_url": "https://example.com/public-fitness-case",
            "company": "Example Fitness",
            "title": "Public fitness case page",
            "directory_industry": "Fitness",
            "provisional_subvertical_ids": ["b2c.health_wellness.fitness"],
        }])
        verify_gold_case_discovery(extended)
        self.assertEqual(extended["snapshot_receipts"], base["snapshot_receipts"])
        self.assertEqual(extended["unique_discovery_lead_count"], base["unique_discovery_lead_count"] + 1)
        self.assertEqual(extended["routing_counts"]["b2c.health_wellness.fitness"], 1)
        receipt = next(row for row in extended["targeted_lead_receipts"] if "fitness" in row["source_url"])
        self.assertEqual(receipt["discovery_method"], "model_assisted_public_search_result")
        self.assertEqual(receipt["quota_credit"], 0)

    def test_extension_deduplicates_url_and_merges_routes(self) -> None:
        base = compile_gold_case_discovery([], research_cutoff="2026-08-05", targeted_leads=[{
            "source_family_id": "targeted_public_case_pages",
            "source_url": "https://example.com/shared-case",
            "company": "Shared Brand",
            "title": "Shared case page",
            "provisional_subvertical_ids": ["b2c.beauty_fashion.beauty"],
        }])
        extended = extend_gold_case_discovery(base, [{
            "source_family_id": "targeted_public_case_pages",
            "source_url": "https://example.com/shared-case?tracking=1",
            "company": "Shared Brand",
            "title": "Shared case page",
            "provisional_subvertical_ids": ["b2c.food_beverage.consumer_packaged_goods"],
        }])
        self.assertEqual(extended["unique_discovery_lead_count"], 1)
        self.assertEqual(set(extended["records"][0]["provisional_subvertical_ids"]), {
            "b2c.beauty_fashion.beauty",
            "b2c.food_beverage.consumer_packaged_goods",
        })

    def test_extension_rejects_invalid_method_and_verifier_rejects_aggregate_tamper(self) -> None:
        base = compile_gold_case_discovery([self._snapshot()], research_cutoff="2026-08-05")
        with self.assertRaisesRegex(GTMGoldCaseDiscoveryError, "method"):
            extend_gold_case_discovery(base, [{
                "source_family_id": "targeted_public_case_pages",
                "source_url": "https://example.com/case",
                "company": "Example",
                "title": "Example case",
                "discovery_method": "unbounded_scrape",
                "provisional_subvertical_ids": ["b2c.health_wellness.fitness"],
            }])
        tampered = copy.deepcopy(base)
        tampered["routing_counts"]["b2b.industrial_climate.manufacturing"] += 1
        unsigned = dict(tampered)
        unsigned.pop("content_sha256", None)
        tampered["content_sha256"] = hashlib.sha256(
            __import__("json").dumps(
                unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
            ).encode("utf-8")
        ).hexdigest()
        with self.assertRaisesRegex(GTMGoldCaseDiscoveryError, "routing aggregate"):
            verify_gold_case_discovery(tampered)


if __name__ == "__main__":
    unittest.main()
