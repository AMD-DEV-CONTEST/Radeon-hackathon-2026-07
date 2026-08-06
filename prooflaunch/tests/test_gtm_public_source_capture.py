from __future__ import annotations

import copy
import unittest
import urllib.robotparser

from prooflaunch_remix.gtm_public_source_capture import (
    FetchResponse,
    GTMPublicSourceCaptureError,
    RobotsPermissionCache,
    capture_public_sources,
    verify_public_source_capture,
)


class GTMPublicSourceCaptureTests(unittest.TestCase):
    def test_robots_policy_is_loaded_once_per_origin_but_each_path_is_checked(self) -> None:
        loaded_origins: list[str] = []

        def loader(origin: str):
            loaded_origins.append(origin)
            parser = urllib.robotparser.RobotFileParser()
            parser.parse(["User-agent: *", "Disallow: /private"])
            return "loaded", parser

        cache = RobotsPermissionCache(loader)
        self.assertEqual(cache.check("https://example.com/public"), ("allowed", True))
        self.assertEqual(cache.check("https://example.com/private/one"), ("disallowed", False))
        self.assertEqual(cache.check("https://example.com/public/two"), ("allowed", True))
        self.assertEqual(loaded_origins, ["https://example.com"])
        self.assertEqual(cache.cached_origin_count, 1)

    def test_capture_is_bounded_hashes_content_and_grants_zero_quota_credit(self) -> None:
        body = b"<html><head><title>Public Case</title><meta name='description' content='Bounded evidence'></head><body>Visible proof</body></html>"
        ledger = capture_public_sources(
            [{"url": "https://example.com/case", "context_ids": ["team:one"]}],
            captured_at="2026-08-04T12:00:00+00:00",
            fetcher=lambda url: FetchResponse(200, url, "text/html", body),
            robots_checker=lambda url: ("allowed", True),
        )
        verify_public_source_capture(ledger)
        self.assertEqual(ledger["status_counts"], {"captured_metadata_only": 1})
        record = ledger["records"][0]
        self.assertEqual(record["title"], "Public Case")
        self.assertEqual(record["quota_credit"], 0)
        self.assertFalse(record["raw_page_retained"])

    def test_duplicate_url_merges_all_case_contexts(self) -> None:
        body = b"<html><title>Shared source</title><body>Evidence</body></html>"
        ledger = capture_public_sources(
            [
                {"url": "https://example.com/shared", "context_ids": ["case:one"]},
                {"url": "https://example.com/shared", "context_ids": ["case:two"]},
            ],
            captured_at="2026-08-04T12:00:00+00:00",
            fetcher=lambda url: FetchResponse(200, url, "text/html", body),
            robots_checker=lambda url: ("allowed", True),
        )
        self.assertEqual(ledger["record_count"], 1)
        self.assertEqual(ledger["records"][0]["source_context_ids"], ["case:one", "case:two"])

    def test_robots_disallow_and_network_failure_are_receipted_not_bypassed(self) -> None:
        disallowed = capture_public_sources(
            [{"url": "https://example.com/no"}],
            captured_at="2026-08-04T12:00:00+00:00",
            fetcher=lambda url: (_ for _ in ()).throw(AssertionError("must not fetch")),
            robots_checker=lambda url: ("disallowed", False),
        )
        self.assertEqual(disallowed["records"][0]["capture_status"], "blocked_by_robots")
        self.assertFalse(disallowed["records"][0]["captcha_bypass_used"])

    def test_credentials_and_tamper_fail_closed(self) -> None:
        ledger = capture_public_sources(
            [{"url": "https://user:secret@example.com/private"}],
            captured_at="2026-08-04T12:00:00+00:00",
            robots_checker=lambda url: ("allowed", True),
        )
        self.assertEqual(ledger["records"][0]["capture_status"], "capture_failed")
        tampered = copy.deepcopy(ledger)
        tampered["records"][0]["captcha_bypass_used"] = True
        with self.assertRaisesRegex(GTMPublicSourceCaptureError, "seal"):
            verify_public_source_capture(tampered)


if __name__ == "__main__":
    unittest.main()
