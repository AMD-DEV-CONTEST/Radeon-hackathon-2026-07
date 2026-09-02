#!/usr/bin/env python3
"""Validate official IR roots and discover bounded material-link candidates."""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import socket
import time
from typing import Any
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser


SCHEMA = "signalforge.ir-source-discovery/v1"
MATERIAL_PATTERN = re.compile(
    r"annual|quarter|earning|result|financial|presentation|investor.day|conference|"
    r"governance|committee|board|proxy|shareholder|letter|transcript|prepared.remarks|"
    r"history|company|business|segment|strategy|risk|outlook|guidance",
    re.IGNORECASE,
)
TERMS_PATTERN = re.compile(r"terms|legal|privacy|conditions", re.IGNORECASE)
ARCHIVE_PATTERN = re.compile(r"archive|past|previous|historical|year|quarter", re.IGNORECASE)


class PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self.title_parts: list[str] = []
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "title":
            self._in_title = True
        if tag.lower() != "a":
            return
        values = dict(attrs)
        href = values.get("href")
        if href:
            self.links.append((href, values.get("title") or values.get("aria-label") or ""))

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title and data.strip():
            self.title_parts.append(data.strip())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=45.0)
    parser.add_argument("--max-html-bytes", type=int, default=2 * 1024 * 1024)
    return parser.parse_args()


def host_allowed(host: str, allowed_hosts: list[str]) -> bool:
    normalized = host.lower().rstrip(".")
    return any(
        normalized == allowed.lower().rstrip(".")
        or normalized.endswith("." + allowed.lower().rstrip("."))
        for allowed in allowed_hosts
    )


def source_uri_allowed(uri: str, source: dict[str, Any]) -> bool:
    parsed = urllib.parse.urlparse(uri)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not host_allowed(host, source.get("allowed_hosts", [])):
        return False
    restricted = source.get("restricted_host_prefixes", {}).get(host)
    return not restricted or any(uri.startswith(prefix) for prefix in restricted)


def validate_registry(registry: dict[str, Any]) -> list[dict[str, Any]]:
    if registry.get("schema_version") != "signalforge/investor-relations-source-registry/v2":
        raise ValueError("unsupported source registry schema")
    sources = registry.get("sources")
    if not isinstance(sources, list) or len(sources) != 20:
        raise ValueError("source registry must contain exactly 20 issuers")
    seen_ids: set[str] = set()
    seen_ciks: set[str] = set()
    seen_tickers: set[str] = set()
    for source in sources:
        cik = source.get("cik", "")
        company_id = source.get("company_id", "")
        ticker = source.get("primary_ticker", "")
        if not re.fullmatch(r"\d{10}", cik) or company_id != f"sec-cik:{cik}":
            raise ValueError(f"invalid issuer identity for {ticker!r}")
        if company_id in seen_ids or cik in seen_ciks or ticker in seen_tickers:
            raise ValueError(f"duplicate issuer identity for {ticker!r}")
        seen_ids.add(company_id)
        seen_ciks.add(cik)
        seen_tickers.add(ticker)
        for key in ("discovery_uri", "robots_uri"):
            parsed = urllib.parse.urlparse(source.get(key, ""))
            if parsed.scheme != "https" or not parsed.hostname:
                raise ValueError(f"{key} must be an absolute HTTPS URI for {ticker}")
        if not host_allowed(
            urllib.parse.urlparse(source["discovery_uri"]).hostname or "",
            source.get("allowed_hosts", []),
        ):
            raise ValueError(f"discovery host is outside the allowlist for {ticker}")
        for host, prefixes in source.get("restricted_host_prefixes", {}).items():
            if host not in source.get("allowed_hosts", []) or not prefixes:
                raise ValueError(f"invalid restricted host policy for {ticker}")
            if any(not prefix.startswith(f"https://{host}/") for prefix in prefixes):
                raise ValueError(f"restricted URI prefix does not match its host for {ticker}")
    return sources


def bounded_read(response: Any, limit: int) -> bytes:
    payload = response.read(limit + 1)
    if len(payload) > limit:
        raise ValueError("response exceeds discovery byte limit")
    return payload


def fetch(
    url: str,
    user_agent: str,
    timeout: float,
    limit: int,
    method: str = "GET",
) -> dict[str, Any]:
    started = time.monotonic()
    request = urllib.request.Request(
        url,
        method=method,
        headers={
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml,text/plain;q=0.8,*/*;q=0.1",
            "Accept-Encoding": "identity",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = b"" if method == "HEAD" else bounded_read(response, limit)
            return {
                "method": method,
                "status_code": response.status,
                "final_uri": response.geturl(),
                "media_type": response.headers.get_content_type(),
                "content_bytes": len(payload),
                "content_sha256": hashlib.sha256(payload).hexdigest(),
                "etag": response.headers.get("ETag"),
                "last_modified": response.headers.get("Last-Modified"),
                "elapsed_ms": round((time.monotonic() - started) * 1000),
                "payload": payload,
            }
    except urllib.error.HTTPError as error:
        return {
            "method": method,
            "status_code": error.code,
            "final_uri": error.geturl(),
            "elapsed_ms": round((time.monotonic() - started) * 1000),
            "failure_class": "http_error",
        }
    except (TimeoutError, socket.timeout):
        return {
            "method": method,
            "elapsed_ms": round((time.monotonic() - started) * 1000),
            "failure_class": "timeout",
        }
    except (urllib.error.URLError, ValueError) as error:
        return {
            "method": method,
            "elapsed_ms": round((time.monotonic() - started) * 1000),
            "failure_class": type(error).__name__,
        }


def normalize_links(base_uri: str, parser: PageParser) -> list[dict[str, str]]:
    by_uri: dict[str, dict[str, str]] = {}
    for href, label in parser.links:
        uri = urllib.parse.urljoin(base_uri, href).split("#", 1)[0]
        parsed = urllib.parse.urlparse(uri)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            continue
        if uri not in by_uri:
            by_uri[uri] = {"uri": uri, "label": " ".join(label.split())}
    return sorted(by_uri.values(), key=lambda item: item["uri"])


def discover_source(source: dict[str, Any], user_agent: str, timeout: float, limit: int) -> dict[str, Any]:
    root = fetch(source["discovery_uri"], user_agent, timeout, limit)
    root_probe = None
    if root.get("failure_class") == "timeout":
        root_probe = fetch(
            source["discovery_uri"],
            user_agent,
            min(timeout, 15.0),
            0,
            method="HEAD",
        )
    robots = fetch(source["robots_uri"], user_agent, timeout, min(limit, 512 * 1024))
    effective_root = root_probe if root_probe and root_probe.get("status_code") else root
    final_uri = effective_root.get("final_uri", source["discovery_uri"])
    final_host = urllib.parse.urlparse(final_uri).hostname or ""
    final_host_allowed = host_allowed(final_host, source["allowed_hosts"])

    result: dict[str, Any] = {
        "company_id": source["company_id"],
        "cik": source["cik"],
        "issuer": source["issuer"],
        "primary_ticker": source["primary_ticker"],
        "requested_uri": source["discovery_uri"],
        "allowed_hosts": source["allowed_hosts"],
        "root": {key: value for key, value in root.items() if key != "payload"},
        "root_probe": (
            {key: value for key, value in root_probe.items() if key != "payload"}
            if root_probe is not None
            else None
        ),
        "root_final_host_allowed": final_host_allowed,
        "robots": {key: value for key, value in robots.items() if key != "payload"},
        "robots_allows_root": None,
        "title": "",
        "material_link_count": 0,
        "material_link_samples": [],
        "archive_link_samples": [],
        "terms_link_samples": [],
        "external_host_candidates": [],
    }

    robots_payload = robots.get("payload")
    if robots.get("status_code") == 200 and isinstance(robots_payload, bytes):
        robot = urllib.robotparser.RobotFileParser()
        robot.set_url(source["robots_uri"])
        robot.parse(robots_payload.decode("utf-8", errors="replace").splitlines())
        result["robots_allows_root"] = robot.can_fetch(user_agent, final_uri)

    payload = root.get("payload")
    if root.get("status_code") == 200 and root.get("media_type") == "text/html" and isinstance(payload, bytes):
        page = PageParser()
        page.feed(payload.decode("utf-8", errors="replace"))
        links = normalize_links(final_uri, page)
        result["title"] = " ".join(page.title_parts)
        material = [item for item in links if MATERIAL_PATTERN.search(item["uri"] + " " + item["label"])]
        archive = [item for item in material if ARCHIVE_PATTERN.search(item["uri"] + " " + item["label"])]
        terms = [item for item in links if TERMS_PATTERN.search(item["uri"] + " " + item["label"])]
        external = sorted(
            {
                urllib.parse.urlparse(item["uri"]).hostname or ""
                for item in material
                if not host_allowed(urllib.parse.urlparse(item["uri"]).hostname or "", source["allowed_hosts"])
            }
        )
        result.update(
            {
                "material_link_count": len(material),
                "material_link_samples": material[:30],
                "archive_link_samples": archive[:20],
                "terms_link_samples": terms[:10],
                "external_host_candidates": external,
            }
        )

    status = effective_root.get("status_code")
    if status in {401, 403}:
        disposition = "blocked"
    elif root.get("failure_class") == "timeout" and status in range(200, 400) and final_host_allowed:
        disposition = "head_verified_needs_body"
    elif root.get("failure_class") == "timeout" and status is not None:
        disposition = "needs_review"
    elif root.get("failure_class") == "timeout":
        disposition = "timeout"
    elif status != 200 or not final_host_allowed:
        disposition = "needs_review"
    elif result["robots_allows_root"] is False:
        disposition = "robots_disallowed"
    else:
        disposition = "root_verified"
    result["disposition"] = disposition
    return result


def main() -> int:
    args = parse_args()
    registry_bytes = args.registry.read_bytes()
    registry = json.loads(registry_bytes)
    sources = validate_registry(registry)
    user_agent_var = registry["collection_policy"]["user_agent_environment_variable"]
    user_agent = os.environ.get(user_agent_var, "").strip()
    if not user_agent:
        raise SystemExit(f"{user_agent_var} is required")
    workers = min(registry["collection_policy"]["max_concurrency"], len(sources))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [
            executor.submit(discover_source, source, user_agent, args.timeout, args.max_html_bytes)
            for source in sources
        ]
        results = [future.result() for future in futures]
    results.sort(key=lambda result: result["primary_ticker"])
    counts: dict[str, int] = {}
    for result in results:
        counts[result["disposition"]] = counts.get(result["disposition"], 0) + 1
    report = {
        "schema_version": SCHEMA,
        "universe_id": registry["universe_id"],
        "checked_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "registry_sha256": hashlib.sha256(registry_bytes).hexdigest(),
        "user_agent_supplied": True,
        "source_count": len(results),
        "disposition_counts": dict(sorted(counts.items())),
        "sources": results,
        "claim_boundary": "Root availability and discovered links do not establish rights approval, complete archives, parser quality, or product readiness.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"source_count": len(results), "disposition_counts": report["disposition_counts"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
