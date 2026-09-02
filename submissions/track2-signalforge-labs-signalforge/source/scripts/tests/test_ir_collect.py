from __future__ import annotations

import importlib.util
import errno
import io
import json
from pathlib import Path
import tempfile
import urllib.error
import unittest
from unittest import mock


MODULE_PATH = Path(__file__).resolve().parents[1] / "ir_collect.py"
SPEC = importlib.util.spec_from_file_location("ir_collect", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class IRCollectorTests(unittest.TestCase):
    def test_canonical_uri_drops_tracking_and_fragment(self) -> None:
        self.assertEqual(
            "https://ir.example.com/report.pdf?id=7",
            MODULE.canonical_uri("https://IR.EXAMPLE.COM/report.pdf?id=7&utm_source=x#page=2"),
        )

    def test_year_filter_keeps_undated_and_current_window(self) -> None:
        self.assertTrue(MODULE.eligible_year("https://example.com/history", "", 2021))
        self.assertTrue(MODULE.eligible_year("https://example.com/2025/report", "", 2021))
        self.assertFalse(MODULE.eligible_year("https://example.com/2019/report", "", 2021))

    def test_classification_is_conservative(self) -> None:
        self.assertEqual(
            ("prepared_remarks", "C", False),
            MODULE.classify("https://example.com/q1.pdf", "Prepared Remarks", ""),
        )
        self.assertEqual(
            ("corporate_profile_and_history", "E", True),
            MODULE.classify("https://example.com/company-history", "", ""),
        )
        self.assertEqual(
            ("official_strategy_or_risk_update", "C", False),
            MODULE.classify("https://example.com/investors", "", "Investor Relations"),
        )
        self.assertEqual(
            ("capital_allocation_update", "C", False),
            MODULE.classify("https://example.com/news", "Quarterly dividend", ""),
        )
        self.assertEqual(
            ("governance_document", "D", False),
            MODULE.classify("https://example.com/policy", "Partner Code of Conduct", ""),
        )

    def test_generic_investor_path_does_not_make_a_page_material(self) -> None:
        self.assertFalse(MODULE.is_material_candidate("https://example.com/investor/faq", "FAQ"))
        self.assertTrue(MODULE.is_material_candidate("https://example.com/investor/quarterly-results", "Results"))
        self.assertFalse(MODULE.is_material_candidate("https://example.com/investor/page/2", "Next"))
        self.assertTrue(MODULE.is_discovery_candidate("https://example.com/investor/page/2", "Next"))

    def test_json_and_sitemap_discovery_are_deterministic(self) -> None:
        json_links = MODULE.extract_json_links(
            "https://ir.example.com/api/feed.json",
            b'{"items":[{"report_url":"/quarterly-results/2026/q1.pdf"}]}',
        )
        self.assertEqual("https://ir.example.com/quarterly-results/2026/q1.pdf", json_links[0]["uri"])
        sitemap_links = MODULE.extract_sitemap_links(
            b'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            b"<url><loc>https://ir.example.com/investor/earnings/2026</loc></url></urlset>"
        )
        self.assertEqual("https://ir.example.com/investor/earnings/2026", sitemap_links[0]["uri"])

    def test_json_discovery_has_a_bounded_iterative_walk(self) -> None:
        value: object = "/quarterly-results/2026/q1.pdf"
        for _ in range(2_000):
            value = {"nested": value}
        links = MODULE.extract_json_links(
            "https://ir.example.com/api/feed.json",
            json.dumps(value).encode(),
        )
        self.assertEqual("https://ir.example.com/quarterly-results/2026/q1.pdf", links[0]["uri"])

    def test_temporal_metadata_keeps_publication_and_fiscal_period_distinct(self) -> None:
        metadata = MODULE.explicit_temporal_metadata(
            "Q2 2025 results",
            "Published 2025-07-31",
            b"Management discussion",
            "text/plain",
        )
        self.assertEqual("2025-07-31T00:00:00+00:00", metadata["published_at"])
        self.assertEqual("FY2025-Q2", metadata["fiscal_period"])
        body_only = MODULE.explicit_temporal_metadata(
            "Results",
            "Quarterly update",
            b"An archive table mentions 2020-01-01 before 2025-07-31.",
            "text/plain",
        )
        self.assertNotIn("published_at", body_only)

    def test_material_filter_ignores_host_and_navigation_noise(self) -> None:
        self.assertFalse(MODULE.is_material_candidate(
            "https://www.aboutamazon.com/news/company-news", "Company news"
        ))
        self.assertFalse(MODULE.is_material_candidate(
            "https://www.microsoft.com/en-us/privacy?icid=Company_Privacy", "Privacy"
        ))
        self.assertFalse(MODULE.is_material_candidate(
            "https://ir.example.com/annual-reports", "Annual Reports"
        ))
        self.assertTrue(MODULE.is_material_candidate(
            "https://ir.example.com/about/history", "Our history"
        ))
        self.assertTrue(MODULE.is_material_candidate(
            "https://ir.example.com/shareholder-letters", "Annual reports and shareholder letters"
        ))
        self.assertFalse(MODULE.is_material_candidate(
            "https://blogs.example.com/", "Official corporate blog"
        ))
        self.assertTrue(MODULE.is_material_candidate(
            "https://www.example.com/en-us/about-company/history/",
            "About Us, History, Jobs, Shopping Cart",
        ))
        self.assertTrue(MODULE.is_material_candidate(
            "https://news.example.com/2026/update", "Quarterly dividend declared"
        ))

    def test_retry_delay_is_bounded(self) -> None:
        self.assertEqual(3.0, MODULE.retry_delay("3", 1))
        self.assertEqual(1.0, MODULE.retry_delay(None, 1))
        self.assertEqual(4.0, MODULE.retry_delay(None, 9))
        self.assertEqual(30.0, MODULE.retry_delay("999", 1))

    def test_collection_budget_is_sequential_and_bounded(self) -> None:
        with mock.patch.object(MODULE.time, "monotonic", side_effect=[10.0, 10.5, 11.2, 11.4]):
            budget = MODULE.CollectionBudget(1.0, 4)
            self.assertEqual(1, budget.effective_concurrency)
            self.assertFalse(budget.exhausted())
            self.assertAlmostEqual(1.2, budget.elapsed_seconds())
            self.assertEqual(0.0, budget.remaining_seconds())

    @mock.patch.object(MODULE.time, "monotonic", side_effect=[10.0, 10.0, 10.0])
    def test_fetch_stops_before_network_when_global_deadline_is_exhausted(self, _monotonic: mock.Mock) -> None:
        with mock.patch.object(MODULE.urllib.request, "urlopen") as urlopen:
            result, payload = MODULE.fetch(
                "https://ir.example.com/report",
                "SignalForge test",
                30,
                1024,
                {"text/html"},
                ["example.com"],
                {"allowed_hosts": ["example.com"]},
                mock.Mock(),
                deadline_monotonic=10.0,
            )
        self.assertEqual("global_wall_time_exhausted", result["failure_class"])
        self.assertEqual(b"", payload)
        urlopen.assert_not_called()

    @mock.patch.object(MODULE, "store_payload")
    def test_storage_full_is_typed_for_safe_recovery(self, store_payload: mock.Mock) -> None:
        store_payload.side_effect = OSError(errno.ENOSPC, "disk full")
        path, failure = MODULE.try_store_payload(Path("/tmp/raw"), "abc", b"payload")
        self.assertIsNone(path)
        self.assertEqual("storage_full", failure)

    def test_content_addressed_store_is_atomic_and_verifies_existing_bytes(self) -> None:
        payload = b"immutable investor relations artifact"
        digest = MODULE.hashlib.sha256(payload).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            raw_store = Path(directory)
            path = MODULE.store_payload(raw_store, digest, payload)
            self.assertEqual(payload, path.read_bytes())
            self.assertFalse(list(path.parent.glob("*.tmp")))
            path.write_bytes(b"corrupt")
            stored, failure = MODULE.try_store_payload(raw_store, digest, payload)
            self.assertIsNone(stored)
            self.assertEqual("storage_write_error", failure)

    @mock.patch.object(MODULE.urllib.request, "urlopen")
    def test_fetch_types_403_without_retry(self, urlopen: mock.Mock) -> None:
        response_error = urllib.error.HTTPError(
            "https://ir.example.com/report",
            403,
            "forbidden",
            {},
            io.BytesIO(),
        )
        self.addCleanup(response_error.close)
        urlopen.side_effect = response_error
        result, payload = MODULE.fetch(
            "https://ir.example.com/report",
            "SignalForge test",
            1,
            1024,
            {"text/html"},
            ["example.com"],
            {"allowed_hosts": ["example.com"]},
            mock.Mock(),
        )
        self.assertEqual("blocked", result["disposition"])
        self.assertEqual(403, result["status_code"])
        self.assertEqual(b"", payload)
        self.assertEqual(1, urlopen.call_count)

    @mock.patch.object(MODULE.time, "sleep")
    @mock.patch.object(MODULE.urllib.request, "urlopen")
    def test_fetch_retries_429_then_records_failure(self, urlopen: mock.Mock, sleep: mock.Mock) -> None:
        response_error = urllib.error.HTTPError(
            "https://ir.example.com/report",
            429,
            "rate limited",
            {"Retry-After": "0"},
            io.BytesIO(),
        )
        self.addCleanup(response_error.close)
        urlopen.side_effect = response_error
        result, payload = MODULE.fetch(
            "https://ir.example.com/report",
            "SignalForge test",
            1,
            1024,
            {"text/html"},
            ["example.com"],
            {"allowed_hosts": ["example.com"]},
            mock.Mock(),
        )
        self.assertEqual("failed", result["disposition"])
        self.assertEqual(429, result["status_code"])
        self.assertEqual(3, result["attempt"])
        self.assertEqual(b"", payload)
        self.assertEqual(3, urlopen.call_count)
        self.assertEqual(2, sleep.call_count)

    @mock.patch.object(MODULE.urllib.request, "urlopen")
    def test_fetch_types_404_without_retry(self, urlopen: mock.Mock) -> None:
        urlopen.side_effect = urllib.error.HTTPError(
            "https://ir.example.com/missing",
            404,
            "not found",
            {},
            io.BytesIO(),
        )
        result, _ = MODULE.fetch(
            "https://ir.example.com/missing",
            "SignalForge test",
            1,
            1024,
            {"text/html"},
            ["example.com"],
            {"allowed_hosts": ["example.com"]},
            mock.Mock(),
        )
        self.assertEqual(("failed", 404, 1), (result["disposition"], result["status_code"], result["attempt"]))

    @mock.patch.object(MODULE.time, "sleep")
    @mock.patch.object(MODULE.urllib.request, "urlopen")
    def test_fetch_retries_5xx_with_bounded_attempts(self, urlopen: mock.Mock, sleep: mock.Mock) -> None:
        urlopen.side_effect = urllib.error.HTTPError(
            "https://ir.example.com/unavailable",
            503,
            "unavailable",
            {},
            io.BytesIO(),
        )
        result, _ = MODULE.fetch(
            "https://ir.example.com/unavailable",
            "SignalForge test",
            1,
            1024,
            {"text/html"},
            ["example.com"],
            {"allowed_hosts": ["example.com"]},
            mock.Mock(),
        )
        self.assertEqual(("failed", 503, 3), (result["disposition"], result["status_code"], result["attempt"]))
        self.assertEqual(2, sleep.call_count)

    @mock.patch.object(MODULE.ir_discover, "fetch")
    def test_robots_guard_fails_closed_on_external_redirect(self, fetch: mock.Mock) -> None:
        fetch.return_value = {
            "status_code": 200,
            "final_uri": "https://attacker.test/robots.txt",
            "payload": b"User-agent: *\nAllow: /\n",
            "elapsed_ms": 1,
        }
        guard = MODULE.RobotsGuard("SignalForge test", 1, MODULE.HostBudget(1000))
        allowed, observation = guard.check("https://ir.example.com/report", "sec-cik:0000000001", ["example.com"])
        self.assertFalse(allowed)
        self.assertEqual("disallowed", observation["disposition"])

    @mock.patch.object(MODULE.ir_discover, "fetch")
    def test_robots_guard_caches_policy_not_first_path_decision(self, fetch: mock.Mock) -> None:
        fetch.return_value = {
            "status_code": 200,
            "final_uri": "https://ir.example.com/robots.txt",
            "payload": b"User-agent: *\nDisallow: /private/\nAllow: /public/\n",
            "elapsed_ms": 1,
        }
        guard = MODULE.RobotsGuard("SignalForge test", 1, MODULE.HostBudget(1000))
        private_allowed, observation = guard.check(
            "https://ir.example.com/private/report",
            "sec-cik:0000000001",
            ["example.com"],
        )
        public_allowed, cached_observation = guard.check(
            "https://ir.example.com/public/report",
            "sec-cik:0000000001",
            ["example.com"],
        )
        self.assertFalse(private_allowed)
        self.assertTrue(public_allowed)
        self.assertIsNotNone(observation)
        self.assertIsNone(cached_observation)
        self.assertEqual(1, fetch.call_count)


if __name__ == "__main__":
    unittest.main()
