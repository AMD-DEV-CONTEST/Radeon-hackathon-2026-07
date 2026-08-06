from __future__ import annotations

from collections import Counter
from html.parser import HTMLParser
import hashlib
import json
import re
from typing import Any, Callable, Iterable, Mapping
from urllib.parse import urljoin, urlsplit, urlunsplit

from .gtm_public_source_capture import FetchResponse, default_fetch, robots_permission


SCHEMA = "ProofLaunchGTMPublicCaseIndexEnumerationV2"
MAX_INDEXES = 64
MAX_LINKS_PER_SOURCE = 5_000


class GTMPublicCaseIndexEnumerationError(ValueError):
    """A public case-index enumeration escaped its bounded evidence contract."""


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _canonical_url(value: str, *, keep_query: bool = False) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise GTMPublicCaseIndexEnumerationError("only credential-free public HTTPS URLs are allowed")
    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/")
    return urlunsplit(("https", parsed.netloc.casefold(), path, parsed.query if keep_query else "", ""))


class _AnchorParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._parts: list[str] = []
        self._depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() == "a" and self._href is None:
            row = {str(key).casefold(): str(value or "") for key, value in attrs}
            self._href = row.get("href") or None
            self._parts = []
            self._depth = 1
        elif self._href is not None:
            self._depth += 1

    def handle_endtag(self, tag: str) -> None:
        if self._href is None:
            return
        self._depth -= 1
        if tag.casefold() == "a" or self._depth <= 0:
            text = re.sub(r"\s+", " ", " ".join(self._parts)).strip()
            self.links.append((self._href, text))
            self._href = None
            self._parts = []
            self._depth = 0

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            text = re.sub(r"\s+", " ", data).strip()
            if text:
                self._parts.append(text)


def _fallback_title(url: str) -> str:
    slug = urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1]
    title = re.sub(r"[-_]+", " ", slug).strip().title()
    return title if len(title) >= 4 else f"Customer story: {title}"


def _usable_title(anchor_text: str, url: str) -> str:
    cleaned = re.sub(r"\s+", " ", anchor_text).strip()
    if cleaned.casefold() in {"read", "read more", "read story", "view story", "learn more", "case study"}:
        cleaned = ""
    title = cleaned or _fallback_title(url)
    if len(title) < 4:
        title = f"Customer story: {title}"
    return title[:500]


def enumerate_public_case_indexes(
    source_rows: Iterable[Mapping[str, Any]],
    *,
    fetcher: Callable[[str], FetchResponse] = default_fetch,
    robots_checker: Callable[[str], tuple[str, bool]] = robots_permission,
) -> dict[str, Any]:
    sources = [dict(row) for row in source_rows]
    if not 1 <= len(sources) <= MAX_INDEXES:
        raise GTMPublicCaseIndexEnumerationError(f"source count must be in [1, {MAX_INDEXES}]")

    seen_source_ids: set[str] = set()
    source_receipts: list[dict[str, Any]] = []
    by_url: dict[str, dict[str, Any]] = {}

    for source in sources:
        source_id = str(source.get("source_id") or "").strip()
        index_url = _canonical_url(str(source.get("index_url") or ""), keep_query=True)
        if not source_id or source_id in seen_source_ids:
            raise GTMPublicCaseIndexEnumerationError("source IDs must be non-empty and unique")
        seen_source_ids.add(source_id)
        path_pattern = str(source.get("case_path_regex") or "")
        try:
            matcher = re.compile(path_pattern)
        except re.error as error:
            raise GTMPublicCaseIndexEnumerationError(f"invalid case URL regex for {source_id}") from error
        allowed_hosts = {str(value).casefold() for value in source.get("allowed_hosts", []) if value}
        if not allowed_hosts:
            allowed_hosts = {urlsplit(index_url).hostname or ""}
        max_links = int(source.get("max_case_links") or MAX_LINKS_PER_SOURCE)
        if not 1 <= max_links <= MAX_LINKS_PER_SOURCE:
            raise GTMPublicCaseIndexEnumerationError("max_case_links escaped the bounded limit")

        receipt: dict[str, Any] = {
            "source_id": source_id,
            "index_url": index_url,
            "source_family_id": str(source.get("source_family_id") or "official_vendor_case_index"),
            "evidence_role": str(source.get("evidence_role") or "primary_episode_discovery_only"),
            "source_independence": str(source.get("source_independence") or "vendor_attributed"),
            "access_method": str(source.get("access_method") or "ordinary_public_index"),
            "client_side_rendered": bool(source.get("client_side_rendered", False)),
            "authentication_used": False,
            "captcha_bypass_used": False,
            "paywall_bypass_used": False,
            "raw_page_retained": False,
            "candidate_quota_credit": 0,
        }
        try:
            robots_status, allowed = robots_checker(index_url)
            receipt["robots_status"] = robots_status
            if not allowed:
                receipt.update({"status": "blocked_by_robots", "matched_link_count": 0})
                source_receipts.append(receipt)
                continue
            response = fetcher(index_url)
            if response.status != 200:
                raise GTMPublicCaseIndexEnumerationError(f"HTTP {response.status}")
            if "html" not in response.content_type.casefold():
                raise GTMPublicCaseIndexEnumerationError(f"unsupported index content type: {response.content_type}")
            parser = _AnchorParser()
            parser.feed(response.body.decode("utf-8", errors="replace"))
            matched = 0
            matched_urls: set[str] = set()
            canonical_index_target = _canonical_url(index_url)
            for href, anchor_text in parser.links:
                if matched >= max_links:
                    break
                try:
                    target = _canonical_url(urljoin(response.final_url, href))
                except GTMPublicCaseIndexEnumerationError:
                    continue
                parsed = urlsplit(target)
                if (
                    target == canonical_index_target
                    or target in matched_urls
                    or (parsed.hostname or "").casefold() not in allowed_hosts
                    or not matcher.search(parsed.path)
                ):
                    continue
                matched_urls.add(target)
                matched += 1
                record = by_url.setdefault(
                    target,
                    {
                        "lead_id": "index-lead-" + _digest(target)[:16],
                        "source_url": target,
                        "source_family_ids": [],
                        "source_index_ids": [],
                        "discovery_method": "model_assisted_public_search_result",
                        "company": "",
                        "title": _usable_title(anchor_text, target),
                        "directory_industry": str(source.get("directory_industry") or "public_case_index_unclassified"),
                        "source_excerpt": "",
                        "provisional_subvertical_ids": [],
                        "status": "discovery_lead_only",
                        "human_classification_required": True,
                        "formal_candidate_quota_credit": 0,
                        "automatic_promotion_allowed": False,
                    },
                )
                record["source_family_ids"] = sorted(
                    set(record["source_family_ids"]) | {receipt["source_family_id"]}
                )
                record["source_index_ids"] = sorted(set(record["source_index_ids"]) | {source_id})
                candidate_title = _usable_title(anchor_text, target)
                if len(candidate_title) > len(record["title"]):
                    record["title"] = candidate_title
            receipt.update({
                "status": "enumerated_metadata_only",
                "http_status": response.status,
                "content_type": response.content_type,
                "response_byte_count": len(response.body),
                "index_content_sha256": hashlib.sha256(response.body).hexdigest(),
                "matched_link_count": matched,
            })
        except Exception as error:
            receipt.update({
                "status": "enumeration_failed",
                "matched_link_count": 0,
                "error_type": type(error).__name__,
                "error_summary": str(error)[:300],
            })
        source_receipts.append(receipt)

    records = sorted(by_url.values(), key=lambda row: row["lead_id"])
    status_counts = Counter(str(row["status"]) for row in source_receipts)
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "source_count": len(source_receipts),
        "enumerated_unique_lead_count": len(records),
        "status_counts": dict(sorted(status_counts.items())),
        "source_receipts": source_receipts,
        "records": records,
        "formal_candidate_quota_credit": 0,
        "automatic_promotion_allowed": False,
        "truth_boundary": (
            "This ledger retains only public index receipts and matched case URLs, never raw pages. Vendor and platform "
            "stories are episode-discovery leads, not independent outcome evidence. Every record remains zero-credit until "
            "named human identity, budget, outcome, independence, recency and deduplication review passes CaseCandidateV2."
        ),
    }
    payload["content_sha256"] = _digest(payload)
    return payload


def verify_public_case_index_enumeration(payload: Mapping[str, Any]) -> None:
    unsigned = dict(payload)
    supplied = unsigned.pop("content_sha256", None)
    if payload.get("schema") != SCHEMA or supplied != _digest(unsigned):
        raise GTMPublicCaseIndexEnumerationError("public case-index enumeration seal is invalid")
    sources, records = payload.get("source_receipts"), payload.get("records")
    if not isinstance(sources, list) or not isinstance(records, list):
        raise GTMPublicCaseIndexEnumerationError("source or record collection is malformed")
    if payload.get("source_count") != len(sources) or payload.get("enumerated_unique_lead_count") != len(records):
        raise GTMPublicCaseIndexEnumerationError("enumeration aggregate drifted")
    urls = [row.get("source_url") for row in records]
    if len(urls) != len(set(urls)):
        raise GTMPublicCaseIndexEnumerationError("duplicate case URLs escaped canonical deduplication")
    if payload.get("formal_candidate_quota_credit") != 0 or payload.get("automatic_promotion_allowed") is not False:
        raise GTMPublicCaseIndexEnumerationError("enumeration escaped zero-credit mode")
    for source in sources:
        if (
            source.get("authentication_used") is not False
            or source.get("captcha_bypass_used") is not False
            or source.get("paywall_bypass_used") is not False
            or source.get("raw_page_retained") is not False
            or source.get("candidate_quota_credit") != 0
        ):
            raise GTMPublicCaseIndexEnumerationError("a source receipt escaped access or retention boundaries")
    for row in records:
        if (
            row.get("human_classification_required") is not True
            or row.get("formal_candidate_quota_credit") != 0
            or row.get("automatic_promotion_allowed") is not False
            or row.get("provisional_subvertical_ids") != []
            or not row.get("source_index_ids")
        ):
            raise GTMPublicCaseIndexEnumerationError("an enumerated lead escaped the provisional review boundary")


__all__ = [
    "GTMPublicCaseIndexEnumerationError",
    "enumerate_public_case_indexes",
    "verify_public_case_index_enumeration",
]
