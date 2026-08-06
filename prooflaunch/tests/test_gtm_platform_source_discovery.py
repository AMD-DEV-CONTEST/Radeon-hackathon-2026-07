import unittest

from prooflaunch_remix.gtm_platform_source_discovery import (
    OrganizationSeed,
    PlatformSourceDiscoveryError,
    discover_organization_sources,
    discover_platform_source_registry,
)
from prooflaunch_remix.social_collection_runner import PublicHttpResponse


SEED = OrganizationSeed(
    organization_id="north-america-b2b-1",
    name="Example",
    homepage_url="https://example.com/",
    business_model="b2b",
    market="north_america",
    vertical="b2b_saas",
    company_scale="mid_market",
    lifecycle="growth",
)


class FakeClient:
    def get(self, url, *, timeout_seconds, maximum_bytes):
        body = b'''<html><a href="https://www.linkedin.com/company/example/?trk=x">L</a>
        <a href="https://x.com/example#bio">X</a><a href="mailto:test@example.com">mail</a>
        <link rel="me" href="https://social.example/@example">
        <script type="application/ld+json">{"sameAs":["https://instagram.com/example/?ref=home"]}</script>
        </html>'''
        return PublicHttpResponse(200, body, {"content-type": "text/html"}, url)


class FailingClient:
    def get(self, url, *, timeout_seconds, maximum_bytes):
        raise RuntimeError("unexpected test failure")


class PlatformSourceDiscoveryTests(unittest.TestCase):
    def test_discovers_and_normalizes_homepage_owned_social_links(self):
        result = discover_organization_sources(SEED, http_client=FakeClient())
        self.assertEqual(result["status"], "completed")
        self.assertEqual(
            result["discovered_sources"]["linkedin"],
            ["https://www.linkedin.com/company/example"],
        )
        self.assertEqual(result["discovered_sources"]["x"], ["https://x.com/example"])
        self.assertEqual(
            result["discovered_sources"]["instagram"],
            ["https://instagram.com/example"],
        )
        self.assertEqual(
            result["discovered_sources"]["mastodon"],
            ["https://social.example/@example"],
        )
        self.assertEqual(result["discovered_source_count"], 4)

    def test_registry_is_deterministic_despite_concurrent_completion(self):
        second = OrganizationSeed(**{**SEED.__dict__, "organization_id": "north-america-b2b-2"})
        result = discover_platform_source_registry(
            [second, SEED], http_client_factory=FakeClient, maximum_workers=2
        )
        self.assertEqual(
            [row["organization_id"] for row in result["organizations"]],
            ["north-america-b2b-1", "north-america-b2b-2"],
        )
        self.assertEqual(result["discovered_source_count"], 8)
        self.assertEqual(result["automatic_learning_memory_write_count"], 0)

    def test_duplicate_ids_fail_closed(self):
        with self.assertRaises(PlatformSourceDiscoveryError):
            discover_platform_source_registry([SEED, SEED], http_client_factory=FakeClient)


if __name__ == "__main__":
    unittest.main()
