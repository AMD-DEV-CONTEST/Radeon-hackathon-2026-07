from __future__ import annotations

import base64
import json
from pathlib import Path

import httpx
import pytest

from openalpha_sentinel.sources import (
    GitHubSource,
    RSSSource,
    SnapshotSource,
    SourceHTTPError,
    SourceParseError,
    canonicalize_url,
)


def _json_response(request: httpx.Request, payload: object, status: int = 200):
    return httpx.Response(status, json=payload, request=request)


def _encoded(value: str) -> str:
    return base64.b64encode(value.encode()).decode()


def test_canonicalize_url_removes_tracking_fragment_and_default_port():
    assert canonicalize_url(
        "HTTPS://Example.COM:443//strategies/?b=2&utm_source=test&a=1#results"
    ) == "https://example.com/strategies?a=1&b=2"


def test_canonicalize_url_preserves_resource_query_parameters():
    assert canonicalize_url(
        "https://example.com/feed?source=primary&ref=weekly"
    ) == "https://example.com/feed?ref=weekly&source=primary"


def test_snapshot_file_supports_yaml_front_matter(tmp_path: Path):
    snapshot = tmp_path / "mean-reversion.md"
    snapshot.write_text(
        """---
title: Daily Mean Reversion
author: Ada
source_url: https://Example.com/strategies/mean-reversion/?utm_source=test
license_spdx: MIT
tags: [equity, daily]
published: 2026-07-17
---
# Strategy Notes

Buy after a large down day.
""",
        encoding="utf-8",
    )

    artifact = SnapshotSource().load_file(snapshot)

    assert artifact.kind == "snapshot"
    assert artifact.canonical_url == "https://example.com/strategies/mean-reversion"
    assert artifact.title == "Daily Mean Reversion"
    assert artifact.author == "Ada"
    assert artifact.license_spdx == "MIT"
    assert len(artifact.revision_key) == 64
    assert artifact.immutable_url.endswith(
        f"openalpha_revision=sha256-{artifact.revision_key}"
    )
    assert artifact.documents[0].path == "mean-reversion.md"
    assert artifact.documents[0].text.startswith("# Strategy Notes")
    assert artifact.documents[0].line_offset == 8
    assert "source_url:" not in artifact.documents[0].text
    assert artifact.metadata["front_matter"]["tags"] == ["equity", "daily"]
    assert artifact.metadata["front_matter"]["published"] == "2026-07-17"
    json.dumps(artifact.metadata)


def test_snapshot_commit_pinned_github_blob_is_already_immutable(tmp_path: Path):
    commit = "3aba9fc095ab77157ef225a6c5f77dfa5562ffa9"
    source_url = f"https://github.com/openalpha/example/blob/{commit}/strategy.md"
    snapshot = tmp_path / "strategy.md"
    snapshot.write_text(
        f"---\ntitle: Pinned strategy\nsource_url: {source_url}\n---\n# Strategy\n",
        encoding="utf-8",
    )

    artifact = SnapshotSource().load_file(snapshot)

    assert artifact.canonical_url == source_url
    assert artifact.immutable_url == source_url
    assert artifact.documents[0].source_url == source_url
    assert artifact.documents[0].line_offset == 4


def test_snapshot_directory_is_sorted_filtered_and_limited(tmp_path: Path):
    (tmp_path / "b.md").write_text("# B\n", encoding="utf-8")
    (tmp_path / "a.txt").write_text("A\n", encoding="utf-8")
    (tmp_path / "ignored.bin").write_bytes(b"\x00\x01")
    hidden = tmp_path / ".cache"
    hidden.mkdir()
    (hidden / "hidden.md").write_text("# Hidden\n", encoding="utf-8")

    artifacts = SnapshotSource(max_files=2).load_directory(tmp_path)

    assert [item.documents[0].path for item in artifacts] == ["a.txt", "b.md"]
    with pytest.raises(ValueError, match="must not exceed 2"):
        SnapshotSource(max_files=2).load_directory(tmp_path, limit=3)


def test_snapshot_reports_invalid_front_matter(tmp_path: Path):
    snapshot = tmp_path / "broken.md"
    snapshot.write_text("---\ntitle: [broken\n---\nbody", encoding="utf-8")

    with pytest.raises(SourceParseError, match="Invalid YAML front matter"):
        SnapshotSource().load_file(snapshot)


def test_github_search_fetches_commit_pinned_readme_and_license():
    calls: list[httpx.Request] = []
    sha = "a" * 40

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        path = request.url.path
        if path == "/search/repositories":
            assert request.url.params["q"] == "mean reversion"
            assert request.url.params["per_page"] == "1"
            assert request.headers["authorization"] == "Bearer test-token"
            assert request.headers["user-agent"] == "source-test/1.0"
            return _json_response(
                request,
                {
                    "items": [
                        {
                            "id": 42,
                            "name": "alpha-lab",
                            "full_name": "octo/alpha-lab",
                            "html_url": "https://GitHub.com/octo/alpha-lab.git",
                            "default_branch": "main",
                            "description": "Strategy research",
                            "language": "Python",
                            "topics": ["quant"],
                            "stargazers_count": 10,
                            "owner": {"login": "octo"},
                        }
                    ]
                },
            )
        if path == "/repos/octo/alpha-lab/commits/main":
            return httpx.Response(
                200,
                json={
                    "sha": sha,
                    "commit": {"author": {"date": "2026-07-17T00:00:00Z"}},
                },
                headers={"etag": '"commit-etag"', "last-modified": "Fri"},
                request=request,
            )
        if path == "/repos/octo/alpha-lab/readme":
            assert request.url.params["ref"] == sha
            return _json_response(
                request,
                {
                    "path": "docs/README.md",
                    "encoding": "base64",
                    "content": _encoded("# Alpha Lab\n"),
                },
            )
        if path == "/repos/octo/alpha-lab/license":
            assert request.url.params["ref"] == sha
            return _json_response(
                request,
                {
                    "path": "LICENSE",
                    "encoding": "base64",
                    "content": _encoded("MIT License\n"),
                    "license": {"spdx_id": "MIT"},
                },
            )
        raise AssertionError(f"Unexpected request: {request.url}")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    artifact = GitHubSource(
        client=client, token="test-token", user_agent="source-test/1.0"
    ).search(
        "mean reversion", limit=1
    )[0]

    assert artifact.kind == "github_repository"
    assert artifact.canonical_url == "https://github.com/octo/alpha-lab"
    assert artifact.external_id == "github:42"
    assert artifact.revision_key == sha
    assert artifact.immutable_url == f"https://github.com/octo/alpha-lab/tree/{sha}"
    assert artifact.license_spdx == "MIT"
    assert [document.path for document in artifact.documents] == [
        "docs/README.md",
        "LICENSE",
    ]
    assert artifact.documents[0].source_url == (
        f"https://github.com/octo/alpha-lab/blob/{sha}/docs/README.md"
    )
    assert artifact.documents[0].text == "# Alpha Lab\n"
    assert artifact.etag == '"commit-etag"'
    assert artifact.last_modified == "Fri"
    assert len(calls) == 4


def test_github_missing_readme_and_license_are_recorded():
    sha = "b" * 40

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/search/repositories":
            return _json_response(
                request,
                {
                    "items": [
                        {
                            "id": 7,
                            "name": "empty",
                            "full_name": "octo/empty",
                            "html_url": "https://github.com/octo/empty",
                            "default_branch": "main",
                            "owner": {"login": "octo"},
                        }
                    ]
                },
            )
        if request.url.path.endswith("/commits/main"):
            return _json_response(request, {"sha": sha, "commit": {}})
        if request.url.path.endswith(("/readme", "/license")):
            return _json_response(request, {"message": "Not Found"}, status=404)
        raise AssertionError(str(request.url))

    client = httpx.Client(transport=httpx.MockTransport(handler))
    artifact = GitHubSource(client=client).search("empty", limit=1)[0]

    assert artifact.documents == []
    assert artifact.license_spdx == "NOASSERTION"
    assert artifact.metadata["missing_documents"] == ["README", "LICENSE"]


def test_github_http_error_contains_status_url_and_message():
    def handler(request: httpx.Request) -> httpx.Response:
        return _json_response(
            request, {"message": "rate limit"}, status=403
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    source = GitHubSource(client=client)

    with pytest.raises(SourceHTTPError) as captured:
        source.search("alpha")

    message = str(captured.value)
    assert "HTTP 403" in message
    assert "search/repositories" in message
    assert "rate limit" in message


def test_github_rejects_unbounded_limit_without_http_request():
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"HTTP should not be called: {request.url}")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(ValueError, match="must not exceed 100"):
        GitHubSource(client=client).search("alpha", limit=101)


def test_rss_fetch_uses_embedded_content_and_never_follows_entry_link():
    requests: list[str] = []
    feed = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">
  <channel>
    <title>Strategies</title>
    <item>
      <guid>strategy-1</guid>
      <title>Carry Strategy</title>
      <link>https://example.com/posts/carry?utm_source=feed</link>
      <description><![CDATA[Short summary]]></description>
      <content:encoded><![CDATA[Full feed content]]></content:encoded>
      <author>Ada</author>
      <pubDate>Fri, 17 Jul 2026 00:00:00 GMT</pubDate>
    </item>
    <item><guid>strategy-2</guid><title>Second</title></item>
  </channel>
</rss>"""

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        assert request.url.host == "feeds.example.com"
        assert request.headers["user-agent"] == "source-test/1.0"
        return httpx.Response(
            200,
            content=feed,
            headers={"etag": '"feed-etag"', "last-modified": "Fri"},
            request=request,
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    artifacts = RSSSource(
        client=client, max_entries=2, user_agent="source-test/1.0"
    ).fetch(
        "HTTPS://feeds.example.com/strategies.xml#latest", limit=1
    )

    assert len(requests) == 1
    assert len(artifacts) == 1
    artifact = artifacts[0]
    assert artifact.kind == "rss_entry"
    assert artifact.canonical_url == "https://example.com/posts/carry"
    assert artifact.title == "Carry Strategy"
    assert artifact.author == "Ada"
    assert len(artifact.revision_key) == 64
    assert "Short summary" in artifact.documents[0].text
    assert "Full feed content" in artifact.documents[0].text
    assert artifact.metadata["feed_url"] == "https://feeds.example.com/strategies.xml"
    assert artifact.etag == '"feed-etag"'


def test_atom_feed_is_supported_without_article_fetch():
    feed = b"""<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>tag:example.com,2026:1</id>
    <title>Momentum</title>
    <link rel="alternate" href="/momentum" />
    <summary>Summary in Atom</summary>
    <content>Content in Atom</content>
    <author><name>Grace</name></author>
    <updated>2026-07-17T00:00:00Z</updated>
  </entry>
</feed>"""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == httpx.URL("https://example.com/feed.xml")
        return httpx.Response(200, content=feed, request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    artifact = RSSSource(client=client).fetch("https://example.com/feed.xml")[0]

    assert artifact.canonical_url == "https://example.com/momentum"
    assert artifact.author == "Grace"
    assert artifact.metadata["updated"] == "2026-07-17T00:00:00Z"


def test_rss_reports_malformed_xml():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<rss><broken>", request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(SourceParseError, match="Invalid RSS/Atom XML"):
        RSSSource(client=client).fetch("https://example.com/feed")


def test_rss_checks_each_redirect_before_following_it():
    requests: list[str] = []
    validated: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        if request.url.host == "feeds.example.com":
            return httpx.Response(
                302,
                headers={"location": "https://internal.example/feed.xml"},
                request=request,
            )
        raise AssertionError(f"Unsafe redirect should not be requested: {request.url}")

    def validate(url: str) -> None:
        validated.append(url)
        if httpx.URL(url).host == "internal.example":
            raise PermissionError("blocked redirect destination")

    source = RSSSource(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        url_validator=validate,
    )

    with pytest.raises(PermissionError, match="blocked redirect"):
        source.fetch("https://feeds.example.com/feed.xml")
    assert requests == ["https://feeds.example.com/feed.xml"]
    assert [httpx.URL(url).host for url in validated] == [
        "feeds.example.com",
        "internal.example",
    ]


def test_rss_rejects_https_downgrade_redirect():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            302,
            headers={"location": "http://feeds.example.com/plain.xml"},
            request=request,
        )

    source = RSSSource(client=httpx.Client(transport=httpx.MockTransport(handler)))

    with pytest.raises(SourceHTTPError, match="HTTPS-to-HTTP"):
        source.fetch("https://feeds.example.com/feed.xml")


@pytest.mark.parametrize("with_content_length", [False, True])
def test_rss_stops_at_feed_size_limit(with_content_length: bool):
    content = b"<rss>" + (b"x" * 64) + b"</rss>"

    def handler(request: httpx.Request) -> httpx.Response:
        headers = {"content-length": str(len(content))} if with_content_length else {}
        return httpx.Response(200, content=content, headers=headers, request=request)

    source = RSSSource(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        max_feed_bytes=32,
    )

    with pytest.raises(SourceParseError, match="exceeds 32 byte limit"):
        source.fetch("https://feeds.example.com/feed.xml")
