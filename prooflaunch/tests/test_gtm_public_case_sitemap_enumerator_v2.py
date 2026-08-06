from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from prooflaunch_remix.gtm_public_case_sitemap_enumerator_v2 import (
    GTMPublicCaseSitemapEnumerationError,
    enumerate_public_case_sitemaps,
    verify_public_case_sitemap_enumeration,
)
from prooflaunch_remix.gtm_public_source_capture import FetchResponse


ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "data/gtm_case_funnel_v2/public-case-sitemap-source-registry-v2.json"


class GTMPublicCaseSitemapEnumeratorV2Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.sources = [{
            "source_id": "example",
            "sitemap_url": "https://cases.example/sitemap.xml",
            "allowed_hosts": ["cases.example"],
            "case_path_regex": r"^/customers/[^/]+$",
            "source_family_id": "official_vendor_public_sitemap",
            "source_independence": "vendor_attributed",
            "max_sitemap_documents": 5,
            "max_case_urls": 20,
        }]

    @staticmethod
    def _fetch(url: str) -> FetchResponse:
        if url.endswith("sitemap.xml"):
            body = b"""<?xml version='1.0'?><sitemapindex xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'>
              <sitemap><loc>https://cases.example/customers.xml</loc></sitemap>
            </sitemapindex>"""
        else:
            body = b"""<?xml version='1.0'?><urlset xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'>
              <url><loc>https://cases.example/customers/acme</loc><lastmod>2026-07-01</lastmod></url>
              <url><loc>https://cases.example/customers/blue?ref=sitemap</loc></url>
              <url><loc>https://cases.example/blog/not-a-case</loc></url>
            </urlset>"""
        return FetchResponse(200, url, "application/xml", body)

    def test_recursive_sitemap_enumeration_is_sealed_and_zero_credit(self) -> None:
        payload = enumerate_public_case_sitemaps(
            self.sources,
            captured_at="2026-08-05T00:00:00+00:00",
            fetcher=self._fetch,
            robots_checker=lambda _url: ("allowed", True),
        )
        verify_public_case_sitemap_enumeration(payload)
        self.assertEqual(payload["enumerated_unique_lead_count"], 2)
        self.assertEqual(payload["status_counts"], {"enumerated_metadata_only": 1})
        self.assertEqual(payload["source_receipts"][0]["sitemap_document_count"], 2)
        self.assertEqual(payload["formal_candidate_quota_credit"], 0)
        acme = next(row for row in payload["records"] if row["source_url"].endswith("/acme"))
        self.assertEqual(acme["source_lastmod_values"], ["2026-07-01"])
        self.assertEqual(acme["provisional_subvertical_ids"], [])

    def test_robots_denial_preserves_zero_lead_receipt(self) -> None:
        payload = enumerate_public_case_sitemaps(
            self.sources,
            fetcher=self._fetch,
            robots_checker=lambda _url: ("disallowed", False),
        )
        verify_public_case_sitemap_enumeration(payload)
        self.assertEqual(payload["enumerated_unique_lead_count"], 0)
        self.assertEqual(payload["source_receipts"][0]["documents"][0]["status"], "blocked_by_robots")

    def test_tampered_access_or_credit_fails_closed(self) -> None:
        payload = enumerate_public_case_sitemaps(
            self.sources,
            fetcher=self._fetch,
            robots_checker=lambda _url: ("allowed", True),
        )
        tampered = copy.deepcopy(payload)
        tampered["records"][0]["formal_candidate_quota_credit"] = 1
        with self.assertRaises(GTMPublicCaseSitemapEnumerationError):
            verify_public_case_sitemap_enumeration(tampered)

    def test_registry_defines_nine_primary_only_public_sitemaps(self) -> None:
        registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
        sources = registry["sources"]
        self.assertEqual(len(sources), 9)
        self.assertEqual(len({row["source_id"] for row in sources}), 9)
        self.assertTrue(all(row["sitemap_url"].startswith("https://") for row in sources))
        self.assertTrue(all(row["source_independence"] in {"vendor_attributed", "platform_attributed"} for row in sources))


if __name__ == "__main__":
    unittest.main()
