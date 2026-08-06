from __future__ import annotations

import copy
import unittest

from prooflaunch_remix.gtm_market_neighborhood import (
    MarketNeighborhoodError,
    compile_market_neighborhood,
    verify_market_neighborhood,
)


class MarketNeighborhoodTests(unittest.TestCase):
    def test_b2b_industry_and_region_resolve_without_inventing_neighbors(self) -> None:
        receipt = compile_market_neighborhood(
            {
                "business_model": "b2b",
                "industry": "industrial manufacturing",
                "product_category": "quality operations software",
                "market": "United States",
                "company_scale": "startup",
                "budget": "zero",
                "brand_reach": "emerging",
            }
        )

        self.assertEqual(
            receipt["taxonomy_resolution"]["node_id"], "b2b-manufacturing"
        )
        self.assertEqual(
            receipt["regional_language_resolution"]["language_tag"], "en-US"
        )
        self.assertEqual(receipt["taxonomy_root_count"], 8)
        self.assertEqual(receipt["supported_region_count"], 7)
        self.assertEqual(receipt["admitted_neighbor_count"], 0)
        self.assertIn("price_band", receipt["unresolved_query_dimensions"])
        self.assertIn("sales_cycle", receipt["unresolved_query_dimensions"])
        verify_market_neighborhood(receipt)

    def test_b2c_mobile_category_and_hong_kong_localization_resolve(self) -> None:
        receipt = compile_market_neighborhood(
            {
                "business_model": "b2c",
                "industry": "consumer technology",
                "product_category": "iOS productivity app",
                "market": "Hong Kong",
                "company_scale": "startup",
                "budget": "small",
                "brand_reach": "none",
            }
        )

        self.assertEqual(receipt["taxonomy_resolution"]["node_id"], "b2c-mobile-apps")
        self.assertEqual(receipt["regional_language_resolution"]["language_tag"], "en-HK")
        self.assertTrue(
            receipt["regional_language_resolution"]["human_localization_review_required"]
        )

    def test_evidence_bound_candidates_are_ranked_and_raw_expression_is_absent(self) -> None:
        base = {
            "business_model": "b2b",
            "taxonomy_node_id": "b2b-saas",
            "market_region_id": "us",
            "price_band": "mid",
            "sales_cycle": "30_90_days",
            "company_scale": "startup",
            "budget": "small",
            "brand_reach": "emerging",
            "source_uri": "https://example.com/public-case",
            "source_sha256": "a" * 64,
            "observed_at": "2026-08-01T12:00:00Z",
            "rights_status": "public_measurement",
        }
        exact = {**base, "candidate_id": "exact"}
        distant = {
            **base,
            "candidate_id": "distant",
            "market_region_id": "gb",
            "company_scale": "enterprise",
            "budget": "scaled",
            "brand_reach": "strong",
        }
        rejected = {
            **base,
            "candidate_id": "restricted",
            "rights_status": "restricted",
        }
        receipt = compile_market_neighborhood(
            {
                "business_model": "b2b",
                "industry": "SaaS",
                "product_category": "workflow software",
                "market": "US",
                "price_band": "mid",
                "sales_cycle": "30_90_days",
                "company_scale": "startup",
                "budget": "small",
                "brand_reach": "emerging",
            },
            candidates=(distant, rejected, exact),
        )

        self.assertEqual([row["candidate_id"] for row in receipt["neighbors"]], ["exact", "distant"])
        self.assertEqual(receipt["neighbors"][0]["similarity_score"], 1.0)
        self.assertEqual(receipt["rejected_candidate_counts"], {"rights_status_not_admissible": 1})
        self.assertNotIn("creative_text", str(receipt))
        self.assertFalse(receipt["automatic_strategy_mutation_executed"])
        verify_market_neighborhood(receipt)

    def test_tampering_and_invalid_business_model_fail_closed(self) -> None:
        with self.assertRaises(MarketNeighborhoodError):
            compile_market_neighborhood(
                {"business_model": "marketplace", "industry": "SaaS", "market": "US"}
            )

        receipt = compile_market_neighborhood(
            {
                "business_model": "b2b",
                "industry": "SaaS",
                "market": "US",
            }
        )
        tampered = copy.deepcopy(receipt)
        tampered["taxonomy_resolution"]["node_id"] = "b2b-ai"
        with self.assertRaises(MarketNeighborhoodError):
            verify_market_neighborhood(tampered)


if __name__ == "__main__":
    unittest.main()
