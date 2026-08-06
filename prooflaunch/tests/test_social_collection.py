from __future__ import annotations

import json
import unittest
from pathlib import Path

from prooflaunch_remix.social_collection import (
    SocialCollectionError,
    connector_registry,
    plan_social_collection,
)


class OpenSourceSocialCollectionTests(unittest.TestCase):
    def test_sealed_mechanical_fixture_reproduces_from_reviewed_request(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        request = json.loads(
            (project_root / "data/fixtures/social-collection-public-measurement.json").read_text(
                encoding="utf-8"
            )
        )
        sealed = json.loads(
            (
                project_root
                / "evidence/v10/open-source-social-collection-mechanical-fixture.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(plan_social_collection(request), sealed)

    def test_pinned_registry_covers_major_media_and_conversation_surfaces(self) -> None:
        registry = connector_registry()
        self.assertEqual(len(registry), 14)
        platforms = {platform for item in registry for platform in item.platforms}
        for platform in (
            "youtube",
            "tiktok",
            "instagram",
            "facebook",
            "x",
            "reddit",
            "bluesky",
            "mastodon",
            "linkedin",
            "feed",
        ):
            self.assertIn(platform, platforms)
        for item in registry:
            self.assertRegex(item.revision, r"^[0-9a-f]{40}$")

        no_key_ids = {
            item.connector_id for item in registry if not item.external_api_key_required
        }
        for connector_id in (
            "yt-dlp",
            "rsshub",
            "trafilatura",
            "scrapy",
            "crawl4ai",
            "firecrawl-self-hosted",
        ):
            self.assertIn(connector_id, no_key_ids)
        self.assertEqual(
            {
                item.connector_id
                for item in registry
                if item.live_execution_admitted
            },
            {
                "yt-dlp",
                "gallery-dl",
                "atproto",
                "mastodon.py",
                "feedparser",
                "beautifulsoup4",
            },
        )

    def test_exact_public_protocol_routes_beat_generic_collectors(self) -> None:
        cases = (
            (
                "https://bsky.app/profile/example.com/post/3fixture",
                "bluesky",
                "atproto",
            ),
            (
                "https://social.example/@brand/123456789",
                "mastodon",
                "mastodon.py",
            ),
            (
                "https://news.example/feed.xml",
                "feed",
                "feedparser",
            ),
        )
        for url, hint, connector_id in cases:
            with self.subTest(hint=hint):
                plan = plan_social_collection(
                    {
                        "urls": [url],
                        "platform_hints": [hint],
                        "modalities": ["content", "metadata"],
                        "rights": "public_measurement",
                    }
                )
                selected = plan["plans"][0]
                self.assertEqual(selected["connector_id"], connector_id)
                self.assertEqual(selected["platform_detection"], "operator_hint")

    def test_platform_hints_are_bounded_and_one_for_one(self) -> None:
        request = {
            "urls": ["https://social.example/@brand/123"],
            "modalities": ["content"],
            "rights": "public_measurement",
        }
        with self.assertRaisesRegex(SocialCollectionError, "one-for-one"):
            plan_social_collection({**request, "platform_hints": []})
        with self.assertRaisesRegex(SocialCollectionError, "unsupported"):
            plan_social_collection({**request, "platform_hints": ["unknown"]})

    def test_owned_multimodal_source_selects_pinned_connector_and_budgets(self) -> None:
        plan = plan_social_collection(
            {
                "urls": ["https://www.youtube.com/watch?v=owned-fixture"],
                "modalities": ["video", "audio", "content", "metadata", "comments"],
                "rights": "owned",
                "maximum_items": 100,
                "maximum_bytes": 1_000_000_000,
                "timeout_seconds": 600,
                "retention_days": 30,
            }
        )
        selected = plan["plans"][0]
        self.assertEqual(selected["connector_id"], "yt-dlp")
        self.assertTrue(selected["media_download_allowed"])
        self.assertFalse(selected["raw_content_training_admitted"])
        self.assertRegex(plan["plan_sha256"], r"^[0-9a-f]{64}$")
        fallback = selected["public_no_api_fallback_graph"]
        self.assertEqual(
            [step["connector_id"] for step in fallback],
            ["rsshub", "trafilatura", "scrapy", "crawl4ai", "firecrawl-self-hosted"],
        )
        self.assertTrue(all(not step["external_api_key_required"] for step in fallback))
        self.assertTrue(
            all(
                step["on_auth_captcha_paywall_or_denial"] == "stop_and_human_handoff"
                for step in fallback
            )
        )
        self.assertTrue(
            all(step["rate_policy"] == "bounded_polite_backoff_no_evasion" for step in fallback)
        )

    def test_public_measurement_cannot_silently_download_media_or_train(self) -> None:
        plan = plan_social_collection(
            {
                "urls": ["https://www.instagram.com/p/public-example/"],
                "modalities": ["content", "metadata", "comments"],
                "rights": "public_measurement",
            }
        )
        selected = plan["plans"][0]
        self.assertFalse(selected["media_download_allowed"])
        self.assertTrue(selected["public_measurement_metadata_only"])
        self.assertFalse(selected["raw_content_training_admitted"])

    def test_private_hosts_unknown_rights_and_unbounded_requests_fail_closed(self) -> None:
        base = {
            "urls": ["https://127.0.0.1/private"],
            "modalities": ["content"],
            "rights": "owned",
        }
        with self.assertRaisesRegex(SocialCollectionError, "private"):
            plan_social_collection(base)
        with self.assertRaisesRegex(SocialCollectionError, "rights"):
            plan_social_collection({**base, "urls": ["https://example.com"], "rights": "unknown"})
        with self.assertRaisesRegex(SocialCollectionError, "maximum_items"):
            plan_social_collection({**base, "urls": ["https://example.com"], "maximum_items": 50_000})


if __name__ == "__main__":
    unittest.main()
