from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from prooflaunch_remix.social_collection_runner import (
    BoundedPublicHttpClient,
    PublicHttpResponse,
    SocialCollectionExecutionError,
    execute_social_collection,
)


def request(rights: str = "owned") -> dict[str, object]:
    return {
        "urls": ["https://www.youtube.com/watch?v=owned-fixture"],
        "modalities": ["video", "audio", "content", "metadata", "comments"],
        "rights": rights,
        "maximum_items": 10,
        "maximum_bytes": 10_000_000,
        "timeout_seconds": 30,
        "retention_days": 7,
    }


def response(url: str, payload: object, *, status: int = 200, **headers: str):
    body = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
    return PublicHttpResponse(status, body, headers, url)


class ScriptedHttp:
    def __init__(self, routes: dict[str, PublicHttpResponse]) -> None:
        self.routes = routes
        self.requested: list[str] = []

    def __call__(self, url: str, **_: object) -> PublicHttpResponse:
        self.requested.append(url)
        if url not in self.routes:
            raise AssertionError(f"unexpected request: {url}")
        return self.routes[url]


def public_client(scripted: ScriptedHttp) -> BoundedPublicHttpClient:
    return BoundedPublicHttpClient(
        request_once=scripted,
        resolver=lambda _: ("93.184.216.34",),
    )


class SocialCollectionRunnerTests(unittest.TestCase):
    def test_owned_source_runs_pinned_tool_without_shell_or_bypass_flags(self) -> None:
        observed = {}

        def fake_run(command, **kwargs):
            observed["command"] = command
            observed["kwargs"] = kwargs
            kwargs["stdout"].write(b'{"id":"fixture","comments":[]}\n')
            return subprocess.CompletedProcess(command, 0, b"", b"")

        with tempfile.TemporaryDirectory() as temporary:
            receipt = execute_social_collection(
                request(),
                output_dir=temporary,
                executable_resolver=lambda _: "/opt/pinned/yt-dlp",
                version_resolver=lambda _: "2026.7.4",
                command_runner=fake_run,
            )
            self.assertEqual(receipt["status"], "completed")
            self.assertFalse(receipt["training_admitted"])
            self.assertFalse(observed["kwargs"]["shell"])
            command = observed["command"]
            self.assertIn("--write-comments", command)
            self.assertIn("--write-subs", command)
            self.assertNotIn("--skip-download", command)
            for forbidden in (
                "--no-check-certificates",
                "--impersonate",
                "--proxy",
            ):
                self.assertNotIn(forbidden, command)
            self.assertTrue((Path(temporary) / "collection-receipt.json").is_file())

    def test_public_measurement_is_metadata_only(self) -> None:
        observed = {}

        def fake_run(command, **kwargs):
            observed["command"] = command
            return subprocess.CompletedProcess(command, 0, b"", b"")

        with tempfile.TemporaryDirectory() as temporary:
            execute_social_collection(
                request("public_measurement"),
                output_dir=temporary,
                executable_resolver=lambda _: "/opt/pinned/yt-dlp",
                version_resolver=lambda _: "2026.7.4",
                command_runner=fake_run,
            )
        self.assertIn("--skip-download", observed["command"])
        self.assertIn("--dump-json", observed["command"])
        self.assertIn("--ignore-errors", observed["command"])
        self.assertNotIn("--dump-single-json", observed["command"])
        self.assertNotIn("--write-comments", observed["command"])
        self.assertNotIn("--write-subs", observed["command"])
        self.assertNotIn("--write-thumbnail", observed["command"])

    def test_gallery_public_profile_resolves_queues_without_downloading_media(self) -> None:
        observed = {}

        def fake_run(command, **kwargs):
            observed["command"] = command
            kwargs["stdout"].write(json.dumps([
                [3, "https://cdn.example/public.jpg", {
                    "id": "public-1",
                    "date": "2026-08-01T12:00:00Z",
                    "likes": 20,
                    "comments": 3,
                    "description": "Why one public pattern matters?",
                }]
            ]).encode("utf-8"))
            return subprocess.CompletedProcess(command, 0, b"", b"")

        collection_request = {
            "urls": ["https://www.instagram.com/public-fixture/"],
            "platform_hints": ["instagram"],
            "modalities": ["content", "metadata"],
            "rights": "public_measurement",
            "maximum_items": 10,
            "maximum_bytes": 100_000,
            "timeout_seconds": 30,
            "retention_days": 7,
        }
        with tempfile.TemporaryDirectory() as temporary:
            receipt = execute_social_collection(
                collection_request,
                output_dir=temporary,
                executable_resolver=lambda _: "/opt/pinned/gallery-dl",
                version_resolver=lambda _: "1.32.9",
                command_runner=fake_run,
            )
        command = observed["command"]
        self.assertIn("--resolve-json", command)
        self.assertIn("output.jsonl=true", command)
        self.assertIn("--post-range", command)
        self.assertIn("--no-download", command)
        self.assertNotIn("--cookies-from-browser", command)
        self.assertNotIn("--proxy", command)
        self.assertEqual(receipt["status"], "completed")
        self.assertGreater(receipt["normalized_signal_count"], 0)

    def test_youtube_collection_computes_recent_same_source_organic_baseline(self) -> None:
        def fake_run(command, **kwargs):
            for row in (
                {"id": "a", "title": "Why 3 launch mistakes matter", "upload_date": "20260701", "view_count": 100, "like_count": 5, "comment_count": 1},
                {"id": "b", "title": "A plain update", "upload_date": "20260715", "view_count": 200, "like_count": 10, "comment_count": 2},
                {"id": "c", "title": "Stop copying this launch", "upload_date": "20260730", "view_count": 900, "like_count": 90, "comment_count": 9},
            ):
                kwargs["stdout"].write((json.dumps(row) + "\n").encode())
            return subprocess.CompletedProcess(command, 0, b"", b"")

        with tempfile.TemporaryDirectory() as temporary:
            receipt = execute_social_collection(
                request("public_measurement"),
                output_dir=temporary,
                executable_resolver=lambda _: "/opt/pinned/yt-dlp",
                version_resolver=lambda _: "2026.7.4",
                command_runner=fake_run,
                clock=lambda: __import__("datetime").datetime(2026, 8, 4, tzinfo=__import__("datetime").timezone.utc),
            )
        summary = receipt["runs"][0]["organic_signal_summary"]
        self.assertEqual(summary["normalized_item_count"], 3)
        self.assertEqual(summary["relative_attention_index_ge_2_count"], 1)
        self.assertEqual(summary["median_view_count"], 200.0)
        self.assertEqual(summary["recent_item_count_90d"], 3)
        self.assertFalse(summary["raw_expression_retained"])
        self.assertFalse(summary["public_item_identifiers_retained"])
        self.assertIn("contrarian_correction", summary["top_relative_attention_pattern_counts"])

    def test_cookie_session_requires_explicit_account_authorization(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            cookie = Path(temporary) / "cookies.txt"
            cookie.write_text("fixture", encoding="utf-8")
            with self.assertRaisesRegex(
                SocialCollectionExecutionError, "account_authorized"
            ):
                execute_social_collection(
                    request("owned"),
                    output_dir=Path(temporary) / "out",
                    cookie_file=cookie,
                )

    def test_collector_failure_becomes_human_handoff_not_bypass_retry(self) -> None:
        def fake_run(command, **kwargs):
            kwargs["stdout"].write(b"")
            return subprocess.CompletedProcess(command, 1, b"", b"captcha required")

        with tempfile.TemporaryDirectory() as temporary:
            receipt = execute_social_collection(
                request(),
                output_dir=temporary,
                executable_resolver=lambda _: "/opt/pinned/yt-dlp",
                version_resolver=lambda _: "2026.7.4",
                command_runner=fake_run,
            )
        self.assertEqual(receipt["status"], "human_handoff_required")
        self.assertFalse(receipt["runs"][0]["captcha_or_auth_bypass_attempted"])

    def test_public_playlist_retains_valid_rows_when_one_item_is_unavailable(self) -> None:
        def fake_run(command, **kwargs):
            kwargs["stdout"].write(
                json.dumps({
                    "id": "valid-row", "title": "Why one valid row matters",
                    "upload_date": "20260730", "view_count": 100,
                    "like_count": 4, "comment_count": 1,
                }).encode() + b"\n"
            )
            return subprocess.CompletedProcess(command, 1, b"", b"one item unavailable")

        with tempfile.TemporaryDirectory() as temporary:
            receipt = execute_social_collection(
                request("public_measurement"),
                output_dir=temporary,
                executable_resolver=lambda _: "/opt/pinned/yt-dlp",
                version_resolver=lambda _: "2026.7.4",
                command_runner=fake_run,
                clock=lambda: __import__("datetime").datetime(2026, 8, 4, tzinfo=__import__("datetime").timezone.utc),
            )
        self.assertEqual(receipt["status"], "completed")
        self.assertEqual(receipt["runs"][0]["status"], "completed_with_item_handoffs")
        self.assertEqual(receipt["normalized_signal_count"], 3)
        self.assertEqual(receipt["runs"][0]["public_freshness"]["recent_item_count_90d"], 1)

    def test_bluesky_and_feed_emit_redacted_cross_platform_signal_intelligence(self) -> None:
        bsky = "https://bsky.app/profile/brand.example/post/3fixture"
        resolve_url = (
            "https://public.api.bsky.app/xrpc/com.atproto.identity.resolveHandle?"
            "handle=brand.example"
        )
        thread_url = (
            "https://public.api.bsky.app/xrpc/app.bsky.feed.getPostThread?"
            "uri=at%3A%2F%2Fdid%3Aplc%3Afixture%2Fapp.bsky.feed.post%2F3fixture"
            "&depth=2&parentHeight=1"
        )
        feed = "https://news.example/feed.xml"
        feed_body = b"""<?xml version='1.0'?><rss version='2.0'><channel>
        <title>Fixture</title><item><title>One</title><pubDate>Sun, 02 Aug 2026 12:00:00 GMT</pubDate>
        <enclosure url='https://cdn.example/one.mp3' type='audio/mpeg'/></item></channel></rss>"""
        scripted = ScriptedHttp(
            {
                resolve_url: response(resolve_url, {"did": "did:plc:fixture"}),
                thread_url: response(
                    thread_url,
                    {
                        "thread": {
                            "post": {
                                "likeCount": 11,
                                "repostCount": 4,
                                "replyCount": 2,
                                "quoteCount": 1,
                                "record": {"text": "must remain isolated"},
                                "embed": {"$type": "app.bsky.embed.images#view"},
                            },
                            "replies": [{"post": {}}],
                        }
                    },
                ),
                feed: response(feed, feed_body, **{"content-type": "application/rss+xml"}),
            }
        )
        collection_request = {
            "urls": [bsky, feed],
            "platform_hints": ["bluesky", "feed"],
            "modalities": ["content", "metadata"],
            "rights": "public_measurement",
            "maximum_items": 10,
            "maximum_bytes": 100_000,
            "timeout_seconds": 30,
            "retention_days": 7,
        }
        with tempfile.TemporaryDirectory() as temporary:
            receipt = execute_social_collection(
                collection_request,
                output_dir=temporary,
                http_client=public_client(scripted),
                version_resolver=lambda name: "6.0.12" if name == "feedparser" else "",
            )
            root = Path(temporary)
            snapshot = json.loads((root / "creative-signal-snapshot.json").read_text())
            intelligence = json.loads(
                (root / "creative-signal-intelligence.json").read_text()
            )
            raw_files = list(root.glob("source-*/raw-*.bin"))
        self.assertEqual(receipt["status"], "completed")
        self.assertEqual(receipt["normalized_signal_count"], 7)
        self.assertEqual(len(raw_files), 3)
        self.assertTrue(intelligence["evidence_sufficient_for_hypothesis_generation"])
        self.assertEqual(len(intelligence["hypotheses"]), 3)
        encoded = json.dumps(snapshot)
        self.assertNotIn("brand.example", encoded)
        self.assertNotIn("3fixture", encoded)
        self.assertNotIn("must remain isolated", encoded)
        self.assertTrue(
            all("/source/" in item["source_uri"] for item in snapshot["signals"])
        )

    def test_reddit_profile_is_read_through_its_public_atom_endpoint(self) -> None:
        source = "https://www.reddit.com/r/hubspot"
        feed = "https://www.reddit.com/r/hubspot/new/.rss"
        feed_body = b"""<?xml version='1.0'?><feed xmlns='http://www.w3.org/2005/Atom'>
        <title>HubSpot</title><entry><title>Recent public post</title>
        <updated>2026-08-03T12:00:00Z</updated></entry></feed>"""
        scripted = ScriptedHttp(
            {feed: response(feed, feed_body, **{"content-type": "application/atom+xml"})}
        )
        collection_request = {
            "urls": [source],
            "platform_hints": ["reddit"],
            "modalities": ["content", "metadata"],
            "rights": "public_measurement",
            "maximum_items": 10,
            "maximum_bytes": 100_000,
            "timeout_seconds": 30,
            "retention_days": 7,
        }
        with tempfile.TemporaryDirectory() as temporary:
            receipt = execute_social_collection(
                collection_request,
                output_dir=temporary,
                http_client=public_client(scripted),
                version_resolver=lambda name: "6.0.12" if name == "feedparser" else "",
                clock=lambda: __import__("datetime").datetime(
                    2026, 8, 4, tzinfo=__import__("datetime").timezone.utc
                ),
            )
        self.assertEqual(scripted.requested, [feed])
        self.assertEqual(receipt["status"], "completed")
        self.assertEqual(receipt["runs"][0]["public_freshness"]["recent_item_count_90d"], 1)
        self.assertNotIn("hubspot", json.dumps(receipt).casefold())

    def test_mastodon_reads_public_status_and_context_on_same_origin(self) -> None:
        source = "https://social.example/@brand/123456"
        status_url = "https://social.example/api/v1/statuses/123456"
        context_url = status_url + "/context"
        scripted = ScriptedHttp(
            {
                status_url: response(
                    status_url,
                    {
                        "visibility": "public",
                        "favourites_count": 12,
                        "reblogs_count": 3,
                        "replies_count": 2,
                        "content": "must remain isolated",
                        "media_attachments": [{"type": "video"}],
                    },
                ),
                context_url: response(
                    context_url, {"ancestors": [], "descendants": [{"id": "9"}]}
                ),
            }
        )
        collection_request = {
            "urls": [source],
            "platform_hints": ["mastodon"],
            "modalities": ["content", "metadata", "comments"],
            "rights": "public_measurement",
            "maximum_items": 10,
            "maximum_bytes": 100_000,
            "timeout_seconds": 30,
            "retention_days": 7,
        }
        with tempfile.TemporaryDirectory() as temporary:
            receipt = execute_social_collection(
                collection_request,
                output_dir=temporary,
                http_client=public_client(scripted),
            )
            snapshot = json.loads(
                (Path(temporary) / "creative-signal-snapshot.json").read_text()
            )
        self.assertEqual(receipt["status"], "completed")
        self.assertEqual(scripted.requested, [status_url, context_url])
        self.assertEqual(receipt["normalized_signal_count"], 3)
        self.assertNotIn("123456", json.dumps(snapshot))
        self.assertIn("video", snapshot["signals"][0]["format_features"])

    def test_public_http_client_rejects_private_dns_and_redirect_targets(self) -> None:
        private_dns = BoundedPublicHttpClient(
            request_once=lambda url, **_: response(url, b"ok"),
            resolver=lambda _: ("127.0.0.1",),
        )
        with self.assertRaisesRegex(SocialCollectionExecutionError, "non-public"):
            private_dns.get(
                "https://public.example/data", timeout_seconds=1, maximum_bytes=100
            )

        scripted = ScriptedHttp(
            {
                "https://public.example/data": response(
                    "https://public.example/data",
                    b"",
                    status=302,
                    location="https://127.0.0.1/private",
                )
            }
        )
        client = public_client(scripted)
        with self.assertRaisesRegex(SocialCollectionExecutionError, "non-public"):
            client.get(
                "https://public.example/data", timeout_seconds=1, maximum_bytes=100
            )
        self.assertEqual(scripted.requested, ["https://public.example/data"])

    def test_public_http_limits_and_auth_walls_fail_to_human_handoff(self) -> None:
        source = "https://bsky.app/profile/brand.example/post/3fixture"
        resolve_url = (
            "https://public.api.bsky.app/xrpc/com.atproto.identity.resolveHandle?"
            "handle=brand.example"
        )
        scripted = ScriptedHttp(
            {resolve_url: response(resolve_url, {"error": "auth"}, status=401)}
        )
        collection_request = {
            "urls": [source],
            "modalities": ["content", "metadata"],
            "rights": "public_measurement",
            "maximum_items": 10,
            "maximum_bytes": 100,
            "timeout_seconds": 30,
            "retention_days": 7,
        }
        with tempfile.TemporaryDirectory() as temporary:
            receipt = execute_social_collection(
                collection_request,
                output_dir=temporary,
                http_client=public_client(scripted),
            )
        self.assertEqual(receipt["status"], "human_handoff_required")
        self.assertIn("HTTP 401", receipt["runs"][0]["error"])
        self.assertFalse(receipt["runs"][0]["captcha_or_auth_bypass_attempted"])

        oversized = BoundedPublicHttpClient(
            request_once=lambda url, **_: response(url, b"x" * 101),
            resolver=lambda _: ("93.184.216.34",),
        )
        with self.assertRaisesRegex(SocialCollectionExecutionError, "byte limit"):
            oversized.get(
                "https://public.example/data", timeout_seconds=1, maximum_bytes=100
            )


if __name__ == "__main__":
    unittest.main()
