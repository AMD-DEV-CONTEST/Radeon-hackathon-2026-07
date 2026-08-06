from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from prooflaunch_remix.gtm_public_case_index_enumerator_v2 import (
    GTMPublicCaseIndexEnumerationError,
    enumerate_public_case_indexes,
    verify_public_case_index_enumeration,
)
from prooflaunch_remix.gtm_public_source_capture import FetchResponse


ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "data/gtm_case_funnel_v2/public-case-index-source-registry-v2.json"


class GTMPublicCaseIndexEnumeratorV2Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.sources = [
            {
                "source_id": "alpha",
                "index_url": "https://cases.example/index?all=true",
                "allowed_hosts": ["cases.example"],
                "case_path_regex": r"^/stories/[^/]+$",
                "source_family_id": "official_vendor_case_index",
                "evidence_role": "primary_episode_discovery_only",
                "source_independence": "vendor_attributed",
                "max_case_links": 20,
            },
            {
                "source_id": "beta",
                "index_url": "https://cases.example/archive",
                "allowed_hosts": ["cases.example"],
                "case_path_regex": r"^/stories/[^/]+$",
                "source_family_id": "official_platform_case_index",
                "evidence_role": "primary_episode_discovery_only",
                "source_independence": "platform_attributed",
                "max_case_links": 20,
            },
        ]

    @staticmethod
    def _fetch(url: str) -> FetchResponse:
        body = b"""
        <html><body>
          <a href='/stories/acme'><strong>Acme</strong> doubles qualified pipeline</a>
          <a href='https://cases.example/stories/blue'>Read story</a>
          <a href='/stories/acme?tracking=1'>Duplicate tracked Acme</a>
          <a href='/stories/nested/path'>Too deep</a>
          <a href='https://other.example/stories/outside'>Outside host</a>
        </body></html>
        """
        return FetchResponse(200, url, "text/html; charset=utf-8", body)

    def test_enumeration_is_deduplicated_bounded_and_zero_credit(self) -> None:
        payload = enumerate_public_case_indexes(
            self.sources,
            fetcher=self._fetch,
            robots_checker=lambda _url: ("allowed", True),
        )
        verify_public_case_index_enumeration(payload)
        self.assertEqual(payload["source_count"], 2)
        self.assertEqual(payload["enumerated_unique_lead_count"], 2)
        self.assertEqual(payload["status_counts"], {"enumerated_metadata_only": 2})
        self.assertEqual(payload["formal_candidate_quota_credit"], 0)
        acme = next(row for row in payload["records"] if row["source_url"].endswith("/acme"))
        self.assertEqual(acme["source_index_ids"], ["alpha", "beta"])
        self.assertEqual(acme["provisional_subvertical_ids"], [])
        self.assertTrue(acme["human_classification_required"])
        blue = next(row for row in payload["records"] if row["source_url"].endswith("/blue"))
        self.assertEqual(blue["title"], "Blue")

    def test_robots_denial_is_preserved_as_a_receipt(self) -> None:
        payload = enumerate_public_case_indexes(
            self.sources[:1],
            fetcher=self._fetch,
            robots_checker=lambda _url: ("disallowed", False),
        )
        verify_public_case_index_enumeration(payload)
        self.assertEqual(payload["enumerated_unique_lead_count"], 0)
        self.assertEqual(payload["status_counts"], {"blocked_by_robots": 1})
        self.assertEqual(payload["source_receipts"][0]["matched_link_count"], 0)

    def test_tampered_credit_or_access_flag_fails_closed(self) -> None:
        payload = enumerate_public_case_indexes(
            self.sources[:1],
            fetcher=self._fetch,
            robots_checker=lambda _url: ("allowed", True),
        )
        tampered = copy.deepcopy(payload)
        tampered["source_receipts"][0]["captcha_bypass_used"] = True
        with self.assertRaises(GTMPublicCaseIndexEnumerationError):
            verify_public_case_index_enumeration(tampered)

    def test_registry_has_twelve_public_primary_only_sources(self) -> None:
        registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
        sources = registry["sources"]
        self.assertEqual(len(sources), 12)
        self.assertEqual(len({row["source_id"] for row in sources}), 12)
        self.assertTrue(all(row["index_url"].startswith("https://") for row in sources))
        self.assertTrue(all(row["evidence_role"] == "primary_episode_discovery_only" for row in sources))
        self.assertTrue(all(row["source_independence"] in {"vendor_attributed", "platform_attributed"} for row in sources))


if __name__ == "__main__":
    unittest.main()
