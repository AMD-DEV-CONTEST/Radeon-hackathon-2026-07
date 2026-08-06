from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
import hashlib
import json
import re
import threading
from typing import Any, Callable, Iterable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen
import urllib.robotparser


SCHEMA = "ProofLaunchGTMPublicSourceCaptureLedgerV1"
USER_AGENT = "ProofLaunchEvidenceBot/1.0 (+public-read-only; no-auth; contact=operator)"
MAX_RESPONSE_BYTES = 2_000_000


class GTMPublicSourceCaptureError(ValueError):
    pass


@dataclass(frozen=True)
class FetchResponse:
    status: int
    final_url: str
    content_type: str
    body: bytes


class _EvidenceHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.title_parts: list[str] = []
        self.description = ""
        self.visible_parts: list[str] = []
        self._in_title = False
        self._suppressed = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lowered = tag.casefold()
        if lowered == "title":
            self._in_title = True
        if lowered in {"script", "style", "noscript", "svg"}:
            self._suppressed += 1
        if lowered == "meta":
            row = {str(key).casefold(): str(value or "") for key, value in attrs}
            if row.get("name", "").casefold() == "description" or row.get("property", "").casefold() == "og:description":
                if not self.description:
                    self.description = row.get("content", "")

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.casefold()
        if lowered == "title":
            self._in_title = False
        if lowered in {"script", "style", "noscript", "svg"} and self._suppressed:
            self._suppressed -= 1

    def handle_data(self, data: str) -> None:
        if self._suppressed:
            return
        text = " ".join(data.split())
        if not text:
            return
        if self._in_title:
            self.title_parts.append(text)
        self.visible_parts.append(text)


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def _validate_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise GTMPublicSourceCaptureError("only credential-free public HTTPS URLs are allowed")
    if parsed.hostname in {"localhost", "127.0.0.1", "::1"}:
        raise GTMPublicSourceCaptureError("local targets are forbidden")


def default_fetch(url: str, *, timeout: float = 20.0) -> FetchResponse:
    _validate_url(url)
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.1"})
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - URL is validated above.
        body = response.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            raise GTMPublicSourceCaptureError("response exceeds the bounded evidence capture limit")
        return FetchResponse(
            status=int(response.status),
            final_url=str(response.geturl()),
            content_type=str(response.headers.get("Content-Type", "")),
            body=body,
        )


def robots_permission(url: str, *, timeout: float = 10.0) -> tuple[str, bool]:
    _validate_url(url)
    parsed = urlparse(url)
    robots_url = urljoin(f"{parsed.scheme}://{parsed.netloc}", "/robots.txt")
    parser = urllib.robotparser.RobotFileParser()
    parser.set_url(robots_url)
    try:
        request = Request(robots_url, headers={"User-Agent": USER_AGENT})
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - robots URL derives from validated origin.
            parser.parse(response.read(512_000).decode("utf-8", errors="replace").splitlines())
        allowed = parser.can_fetch(USER_AGENT, url)
        return ("allowed" if allowed else "disallowed", allowed)
    except (HTTPError, URLError, TimeoutError, OSError):
        return "unavailable", True


def _load_robots_policy(origin: str, *, timeout: float = 10.0) -> tuple[str, urllib.robotparser.RobotFileParser | None]:
    robots_url = urljoin(origin, "/robots.txt")
    parser = urllib.robotparser.RobotFileParser()
    parser.set_url(robots_url)
    try:
        request = Request(robots_url, headers={"User-Agent": USER_AGENT})
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - origin derives from a validated URL.
            parser.parse(response.read(512_000).decode("utf-8", errors="replace").splitlines())
        return "loaded", parser
    except (HTTPError, URLError, TimeoutError, OSError):
        return "unavailable", None


class RobotsPermissionCache:
    """Fetch robots.txt once per origin while still evaluating every target path.

    A large official case directory can contain thousands of URLs on one origin. Re-fetching
    the same robots document for every URL creates avoidable load and timeout risk. The parsed
    policy is cached, but ``can_fetch`` is still called for every exact URL.
    """

    def __init__(
        self,
        loader: Callable[[str], tuple[str, urllib.robotparser.RobotFileParser | None]] = _load_robots_policy,
    ) -> None:
        self._loader = loader
        self._policies: dict[str, tuple[str, urllib.robotparser.RobotFileParser | None]] = {}
        self._lock = threading.Lock()

    def check(self, url: str) -> tuple[str, bool]:
        _validate_url(url)
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        with self._lock:
            if origin not in self._policies:
                self._policies[origin] = self._loader(origin)
            status, parser = self._policies[origin]
        if parser is None:
            return status, True
        allowed = parser.can_fetch(USER_AGENT, url)
        return ("allowed" if allowed else "disallowed"), allowed

    @property
    def cached_origin_count(self) -> int:
        return len(self._policies)


def _summarize_html(body: bytes) -> dict[str, Any]:
    text = body.decode("utf-8", errors="replace")
    parser = _EvidenceHTMLParser()
    parser.feed(text)
    visible = re.sub(r"\s+", " ", " ".join(parser.visible_parts)).strip()
    description = re.sub(r"\s+", " ", parser.description).strip()
    return {
        "title": " ".join(parser.title_parts).strip()[:300],
        "description": description[:500],
        "bounded_visible_excerpt": visible[:280],
        "normalized_visible_text_sha256": hashlib.sha256(visible.encode("utf-8")).hexdigest(),
        "visible_character_count": len(visible),
    }


def capture_public_sources(
    source_rows: Iterable[Mapping[str, Any]],
    *,
    captured_at: str | None = None,
    fetcher: Callable[[str], FetchResponse] = default_fetch,
    robots_checker: Callable[[str], tuple[str, bool]] = robots_permission,
    max_workers: int = 8,
) -> dict[str, Any]:
    captured_at = captured_at or datetime.now(timezone.utc).isoformat()
    seen_urls: set[str] = set()
    source_by_url: dict[str, dict[str, Any]] = {}
    for source in source_rows:
        url = str(source.get("url") or source.get("source_url") or "")
        if not url:
            continue
        seen_urls.add(url)
        merged = source_by_url.setdefault(url, {"url": url, "context_ids": []})
        merged["context_ids"] = sorted(
            set(merged["context_ids"]) | {str(value) for value in source.get("context_ids", []) if value}
        )
    unique_sources: list[Mapping[str, Any]] = list(source_by_url.values())

    if not 1 <= max_workers <= 16:
        raise GTMPublicSourceCaptureError("max_workers must be in [1, 16]")
    effective_robots_checker = RobotsPermissionCache().check if robots_checker is robots_permission else robots_checker

    def capture_one(source: Mapping[str, Any]) -> dict[str, Any]:
        url = str(source.get("url") or source.get("source_url") or "")
        base = {
            "source_url": url,
            "source_context_ids": sorted(set(str(value) for value in source.get("context_ids", []) if value)),
            "captured_at": captured_at,
            "access_method": "ordinary_public_page",
            "authentication_used": False,
            "captcha_bypass_used": False,
            "paywall_bypass_used": False,
            "raw_page_retained": False,
        }
        try:
            _validate_url(url)
            robots_status, allowed = effective_robots_checker(url)
            base["robots_status"] = robots_status
            if not allowed:
                return {**base, "capture_status": "blocked_by_robots", "quota_credit": 0}
            response = fetcher(url)
            final_url = response.final_url
            _validate_url(final_url)
            content_type = response.content_type.casefold()
            if response.status != 200:
                raise GTMPublicSourceCaptureError(f"HTTP {response.status}")
            if not any(token in content_type for token in ("text/html", "application/xhtml+xml", "text/plain")):
                raise GTMPublicSourceCaptureError(f"unsupported content type: {response.content_type}")
            summary = _summarize_html(response.body) if "html" in content_type else {
                "title": "",
                "description": "",
                "bounded_visible_excerpt": response.body.decode("utf-8", errors="replace")[:280],
                "normalized_visible_text_sha256": hashlib.sha256(response.body).hexdigest(),
                "visible_character_count": len(response.body),
            }
            return {
                **base,
                "capture_status": "captured_metadata_only",
                "final_url": final_url,
                "http_status": response.status,
                "content_type": response.content_type,
                "response_byte_count": len(response.body),
                "content_sha256": hashlib.sha256(response.body).hexdigest(),
                **summary,
                "quota_credit": 0,
            }
        except Exception as error:  # Network failures are evidence, not a reason to abort the bounded batch.
            return {
                **base,
                "capture_status": "capture_failed",
                "error_type": type(error).__name__,
                "error_summary": str(error)[:300],
                "quota_credit": 0,
            }

    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="gtm-public-capture") as executor:
        records = list(executor.map(capture_one, unique_sources))
    status_counts: dict[str, int] = {}
    for record in records:
        status = str(record["capture_status"])
        status_counts[status] = status_counts.get(status, 0) + 1
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "captured_at": captured_at,
        "requested_unique_source_count": len(seen_urls),
        "record_count": len(records),
        "status_counts": dict(sorted(status_counts.items())),
        "records": records,
        "promotion_policy": {
            "metadata_capture_alone_grants_candidate_quota_credit": False,
            "case_level_classification_and_evidence_review_required": True,
            "automatic_memory_write_allowed": False,
        },
        "truth_boundary": (
            "This ledger proves a bounded public metadata capture attempt and exact page hashes where successful. It does not "
            "prove case claims, causality, budget scope, performance, or V2 candidate eligibility."
        ),
    }
    payload["content_sha256"] = _digest(payload)
    return payload


def verify_public_source_capture(payload: Mapping[str, Any]) -> None:
    unsigned = dict(payload)
    supplied = unsigned.pop("content_sha256", None)
    if payload.get("schema") != SCHEMA or supplied != _digest(unsigned):
        raise GTMPublicSourceCaptureError("public source capture seal is invalid")
    records = payload.get("records")
    if not isinstance(records, list) or payload.get("record_count") != len(records):
        raise GTMPublicSourceCaptureError("public source capture count drifted")
    if any(
        record.get("authentication_used") is not False
        or record.get("captcha_bypass_used") is not False
        or record.get("paywall_bypass_used") is not False
        or record.get("quota_credit") != 0
        for record in records
    ):
        raise GTMPublicSourceCaptureError("capture escaped access or promotion boundary")


__all__ = [
    "FetchResponse",
    "GTMPublicSourceCaptureError",
    "RobotsPermissionCache",
    "capture_public_sources",
    "default_fetch",
    "robots_permission",
    "verify_public_source_capture",
]
