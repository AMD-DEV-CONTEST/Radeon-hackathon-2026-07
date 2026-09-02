from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import unittest
from unittest import mock


MODULE_PATH = Path(__file__).resolve().parents[1] / "ir_discover.py"
SPEC = importlib.util.spec_from_file_location("ir_discover", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class IRDiscoveryTests(unittest.TestCase):
    def test_host_allowlist_is_suffix_bounded(self) -> None:
        self.assertTrue(MODULE.host_allowed("www.example.com", ["example.com"]))
        self.assertTrue(MODULE.host_allowed("example.com", ["example.com"]))
        self.assertFalse(MODULE.host_allowed("example.com.attacker.test", ["example.com"]))

    def test_parser_discovers_only_https_links_after_normalization(self) -> None:
        parser = MODULE.PageParser()
        parser.feed(
            '<title>Investor Relations</title><a href="/earnings/2026">Results</a>'
            '<a href="javascript:alert(1)">Bad</a><a href="https://cdn.example.com/deck.pdf">Deck</a>'
        )
        links = MODULE.normalize_links("https://ir.example.com/", parser)
        self.assertEqual([item["uri"] for item in links], [
            "https://cdn.example.com/deck.pdf",
            "https://ir.example.com/earnings/2026",
        ])
        self.assertEqual(" ".join(parser.title_parts), "Investor Relations")

    def test_shared_host_requires_issuer_bound_prefix(self) -> None:
        source = {
            "allowed_hosts": ["cdn.example.com"],
            "restricted_host_prefixes": {"cdn.example.com": ["https://cdn.example.com/company-a/"]},
        }
        self.assertTrue(MODULE.source_uri_allowed("https://cdn.example.com/company-a/report.pdf", source))
        self.assertFalse(MODULE.source_uri_allowed("https://cdn.example.com/company-b/report.pdf", source))

    def test_microsoft_policy_excludes_non_investor_product_paths(self) -> None:
        registry = json.loads((MODULE_PATH.parents[1] / "configs" / "sources" / "investor-relations-20.json").read_text())
        source = next(item for item in registry["sources"] if item["primary_ticker"] == "MSFT")
        self.assertTrue(MODULE.source_uri_allowed(
            "https://www.microsoft.com/en-us/Investor/earnings/FY-2026-Q3/metrics", source
        ))
        self.assertFalse(MODULE.source_uri_allowed(
            "https://www.microsoft.com/en-us/education/devices/overview", source
        ))

    def test_registry_requires_exactly_twenty_unique_issuers(self) -> None:
        registry = {
            "schema_version": "signalforge/investor-relations-source-registry/v2",
            "sources": [],
        }
        with self.assertRaisesRegex(ValueError, "exactly 20"):
            MODULE.validate_registry(registry)

    @mock.patch.object(MODULE, "fetch")
    def test_timeout_uses_head_without_approving_external_redirect(self, fetch: mock.Mock) -> None:
        fetch.side_effect = [
            {"method": "GET", "failure_class": "timeout", "elapsed_ms": 1000},
            {"method": "HEAD", "status_code": 200, "final_uri": "https://attacker.test/", "elapsed_ms": 2},
            {"method": "GET", "status_code": 200, "final_uri": "https://ir.example.com/robots.txt", "payload": b"", "elapsed_ms": 2},
        ]
        source = {
            "company_id": "sec-cik:0000000001",
            "cik": "0000000001",
            "issuer": "Example",
            "primary_ticker": "EX",
            "discovery_uri": "https://ir.example.com/",
            "robots_uri": "https://ir.example.com/robots.txt",
            "allowed_hosts": ["example.com"],
        }
        result = MODULE.discover_source(source, "SignalForge test", 1, 1024)
        self.assertEqual("needs_review", result["disposition"])
        self.assertFalse(result["root_final_host_allowed"])

    @mock.patch.object(MODULE, "fetch")
    def test_timeout_with_allowed_head_is_not_treated_as_body_verified(self, fetch: mock.Mock) -> None:
        fetch.side_effect = [
            {"method": "GET", "failure_class": "timeout", "elapsed_ms": 1000},
            {"method": "HEAD", "status_code": 200, "final_uri": "https://ir.example.com/", "elapsed_ms": 2},
            {"method": "GET", "status_code": 200, "final_uri": "https://ir.example.com/robots.txt", "payload": b"", "elapsed_ms": 2},
        ]
        source = {
            "company_id": "sec-cik:0000000001",
            "cik": "0000000001",
            "issuer": "Example",
            "primary_ticker": "EX",
            "discovery_uri": "https://ir.example.com/",
            "robots_uri": "https://ir.example.com/robots.txt",
            "allowed_hosts": ["example.com"],
        }
        result = MODULE.discover_source(source, "SignalForge test", 1, 1024)
        self.assertEqual("head_verified_needs_body", result["disposition"])


if __name__ == "__main__":
    unittest.main()
