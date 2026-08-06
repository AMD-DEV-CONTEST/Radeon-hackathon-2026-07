from __future__ import annotations

from collections import Counter, deque
from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any, Callable, Iterable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

from .gtm_public_source_capture import FetchResponse, USER_AGENT, robots_permission


SCHEMA = "ProofLaunchGTMPublicCaseSitemapEnumerationV2"
MAX_SOURCE_COUNT = 32
MAX_SITEMAP_DOCUMENTS_PER_SOURCE = 160
MAX_CASE_URLS_PER_SOURCE = 20_000
MAX_SITEMAP_BYTES = 12_000_000


class GTMPublicCaseSitemapEnumerationError(ValueError):
    """A public sitemap enumeration escaped its bounded discovery contract."""


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _canonical_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise GTMPublicCaseSitemapEnumerationError("only credential-free public HTTPS URLs are allowed")
    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/")
    return urlunsplit(("https", parsed.netloc.casefold(), path, parsed.query, ""))


def default_sitemap_fetch(url: str, *, timeout: float = 30.0) -> FetchResponse:
    canonical = _canonical_url(url)
    request = Request(
        canonical,
        headers={"User-Agent": USER_AGENT, "Accept": "application/xml,text/xml,text/plain;q=0.9,*/*;q=0.1"},
    )
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - HTTPS URL validated above.
            body = response.read(MAX_SITEMAP_BYTES + 1)
            if len(body) > MAX_SITEMAP_BYTES:
                raise GTMPublicCaseSitemapEnumerationError("sitemap exceeds bounded byte limit")
            return FetchResponse(
                status=int(response.status),
                final_url=str(response.geturl()),
                content_type=str(response.headers.get("Content-Type", "")),
                body=body,
            )
    except (HTTPError, URLError, TimeoutError, OSError):
        raise


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].casefold()


def _slug_title(path: str) -> str:
    title = re.sub(r"[-_]+", " ", path.rstrip("/").rsplit("/", 1)[-1]).title()[:500]
    return title if len(title) >= 4 else f"Customer story: {title}"


def _parse_sitemap(body: bytes) -> tuple[str, list[tuple[str, str]]]:
    try:
        root = ET.fromstring(body)
    except ET.ParseError as error:
        raise GTMPublicCaseSitemapEnumerationError("invalid sitemap XML") from error
    kind = _local_name(root.tag)
    if kind not in {"sitemapindex", "urlset"}:
        raise GTMPublicCaseSitemapEnumerationError(f"unsupported sitemap root: {kind}")
    rows: list[tuple[str, str]] = []
    child_name = "sitemap" if kind == "sitemapindex" else "url"
    for child in root:
        if _local_name(child.tag) != child_name:
            continue
        loc = ""
        lastmod = ""
        for field in child:
            name = _local_name(field.tag)
            if name == "loc":
                loc = (field.text or "").strip()
            elif name == "lastmod":
                lastmod = (field.text or "").strip()
        if loc:
            rows.append((loc, lastmod))
    return kind, rows


def enumerate_public_case_sitemaps(
    source_rows: Iterable[Mapping[str, Any]],
    *,
    captured_at: str | None = None,
    fetcher: Callable[[str], FetchResponse] = default_sitemap_fetch,
    robots_checker: Callable[[str], tuple[str, bool]] = robots_permission,
) -> dict[str, Any]:
    sources = [dict(row) for row in source_rows]
    if not 1 <= len(sources) <= MAX_SOURCE_COUNT:
        raise GTMPublicCaseSitemapEnumerationError("source count escaped the bounded limit")
    captured_at = captured_at or datetime.now(timezone.utc).isoformat()
    source_ids: set[str] = set()
    receipts: list[dict[str, Any]] = []
    by_url: dict[str, dict[str, Any]] = {}

    for source in sources:
        source_id = str(source.get("source_id") or "").strip()
        if not source_id or source_id in source_ids:
            raise GTMPublicCaseSitemapEnumerationError("source IDs must be non-empty and unique")
        source_ids.add(source_id)
        root_url = _canonical_url(str(source.get("sitemap_url") or ""))
        allowed_hosts = {str(host).casefold() for host in source.get("allowed_hosts", []) if host}
        if not allowed_hosts:
            allowed_hosts = {(urlsplit(root_url).hostname or "").casefold()}
        try:
            matcher = re.compile(str(source.get("case_path_regex") or ""))
        except re.error as error:
            raise GTMPublicCaseSitemapEnumerationError(f"invalid case path regex for {source_id}") from error
        max_docs = int(source.get("max_sitemap_documents") or MAX_SITEMAP_DOCUMENTS_PER_SOURCE)
        max_urls = int(source.get("max_case_urls") or MAX_CASE_URLS_PER_SOURCE)
        if not 1 <= max_docs <= MAX_SITEMAP_DOCUMENTS_PER_SOURCE or not 1 <= max_urls <= MAX_CASE_URLS_PER_SOURCE:
            raise GTMPublicCaseSitemapEnumerationError("source-specific sitemap bounds are invalid")

        base_receipt: dict[str, Any] = {
            "source_id": source_id,
            "root_sitemap_url": root_url,
            "source_family_id": str(source.get("source_family_id") or "official_public_sitemap"),
            "evidence_role": "primary_episode_discovery_only",
            "source_independence": str(source.get("source_independence") or "vendor_attributed"),
            "captured_at": captured_at,
            "access_method": "robots_declared_or_public_xml_sitemap",
            "authentication_used": False,
            "captcha_bypass_used": False,
            "paywall_bypass_used": False,
            "raw_sitemap_retained": False,
            "candidate_quota_credit": 0,
        }
        queue = deque([root_url])
        visited: set[str] = set()
        documents: list[dict[str, Any]] = []
        matched_urls: set[str] = set()
        source_status = "enumerated_metadata_only"
        try:
            while queue and len(visited) < max_docs and len(matched_urls) < max_urls:
                sitemap_url = queue.popleft()
                if sitemap_url in visited:
                    continue
                parsed_sitemap = urlsplit(sitemap_url)
                if (parsed_sitemap.hostname or "").casefold() not in allowed_hosts:
                    continue
                robots_status, allowed = robots_checker(sitemap_url)
                if not allowed:
                    documents.append({
                        "sitemap_url": sitemap_url,
                        "status": "blocked_by_robots",
                        "robots_status": robots_status,
                        "entry_count": 0,
                    })
                    visited.add(sitemap_url)
                    continue
                response = fetcher(sitemap_url)
                if response.status != 200:
                    raise GTMPublicCaseSitemapEnumerationError(f"HTTP {response.status}")
                kind, rows = _parse_sitemap(response.body)
                documents.append({
                    "sitemap_url": sitemap_url,
                    "status": "captured_metadata_only",
                    "robots_status": robots_status,
                    "sitemap_kind": kind,
                    "entry_count": len(rows),
                    "response_byte_count": len(response.body),
                    "content_sha256": hashlib.sha256(response.body).hexdigest(),
                })
                visited.add(sitemap_url)
                if kind == "sitemapindex":
                    for child_url, _lastmod in rows:
                        try:
                            child = _canonical_url(child_url)
                        except GTMPublicCaseSitemapEnumerationError:
                            continue
                        if (urlsplit(child).hostname or "").casefold() in allowed_hosts and child not in visited:
                            queue.append(child)
                    continue
                for case_url, lastmod in rows:
                    if len(matched_urls) >= max_urls:
                        break
                    try:
                        target = _canonical_url(case_url)
                    except GTMPublicCaseSitemapEnumerationError:
                        continue
                    parsed = urlsplit(target)
                    if (parsed.hostname or "").casefold() not in allowed_hosts or not matcher.search(parsed.path):
                        continue
                    matched_urls.add(target)
                    record = by_url.setdefault(target, {
                        "lead_id": "sitemap-lead-" + _digest(target)[:16],
                        "source_url": target,
                        "source_family_ids": [],
                        "source_sitemap_ids": [],
                        "discovery_method": "model_assisted_public_search_result",
                        "company": "",
                        "title": _slug_title(parsed.path),
                        "directory_industry": "public_case_sitemap_unclassified",
                        "source_excerpt": "",
                        "source_lastmod_values": [],
                        "provisional_subvertical_ids": [],
                        "status": "discovery_lead_only",
                        "human_classification_required": True,
                        "formal_candidate_quota_credit": 0,
                        "automatic_promotion_allowed": False,
                    })
                    record["source_family_ids"] = sorted(
                        set(record["source_family_ids"]) | {base_receipt["source_family_id"]}
                    )
                    record["source_sitemap_ids"] = sorted(set(record["source_sitemap_ids"]) | {source_id})
                    if lastmod:
                        record["source_lastmod_values"] = sorted(set(record["source_lastmod_values"]) | {lastmod})
            if queue:
                source_status = "bounded_limit_reached"
        except Exception as error:
            source_status = "enumeration_failed"
            base_receipt["error_type"] = type(error).__name__
            base_receipt["error_summary"] = str(error)[:300]
        receipts.append({
            **base_receipt,
            "status": source_status,
            "sitemap_document_count": len(documents),
            "matched_case_url_count": len(matched_urls),
            "documents": documents,
        })

    records = sorted(by_url.values(), key=lambda row: row["lead_id"])
    status_counts = Counter(str(row["status"]) for row in receipts)
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "captured_at": captured_at,
        "source_count": len(receipts),
        "enumerated_unique_lead_count": len(records),
        "status_counts": dict(sorted(status_counts.items())),
        "source_receipts": receipts,
        "records": records,
        "formal_candidate_quota_credit": 0,
        "automatic_promotion_allowed": False,
        "truth_boundary": (
            "This ledger proves bounded enumeration of credential-free public XML sitemaps and retains only document hashes, "
            "case URLs and optional last-modified metadata. It does not prove company identity, campaign identity, budget, "
            "outcome, causality, independence or CaseCandidateV2 eligibility."
        ),
    }
    payload["content_sha256"] = _digest(payload)
    return payload


def verify_public_case_sitemap_enumeration(payload: Mapping[str, Any]) -> None:
    unsigned = dict(payload)
    supplied = unsigned.pop("content_sha256", None)
    if payload.get("schema") != SCHEMA or supplied != _digest(unsigned):
        raise GTMPublicCaseSitemapEnumerationError("public sitemap enumeration seal is invalid")
    sources, records = payload.get("source_receipts"), payload.get("records")
    if not isinstance(sources, list) or not isinstance(records, list):
        raise GTMPublicCaseSitemapEnumerationError("sitemap source or lead collection is malformed")
    if payload.get("source_count") != len(sources) or payload.get("enumerated_unique_lead_count") != len(records):
        raise GTMPublicCaseSitemapEnumerationError("sitemap enumeration aggregate drifted")
    urls = [row.get("source_url") for row in records]
    if len(urls) != len(set(urls)):
        raise GTMPublicCaseSitemapEnumerationError("duplicate sitemap case URLs escaped canonical deduplication")
    if payload.get("formal_candidate_quota_credit") != 0 or payload.get("automatic_promotion_allowed") is not False:
        raise GTMPublicCaseSitemapEnumerationError("sitemap enumeration escaped zero-credit mode")
    for source in sources:
        if (
            source.get("authentication_used") is not False
            or source.get("captcha_bypass_used") is not False
            or source.get("paywall_bypass_used") is not False
            or source.get("raw_sitemap_retained") is not False
            or source.get("candidate_quota_credit") != 0
        ):
            raise GTMPublicCaseSitemapEnumerationError("a sitemap receipt escaped access or retention boundaries")
    for row in records:
        if (
            row.get("provisional_subvertical_ids") != []
            or row.get("human_classification_required") is not True
            or row.get("formal_candidate_quota_credit") != 0
            or row.get("automatic_promotion_allowed") is not False
            or not row.get("source_sitemap_ids")
        ):
            raise GTMPublicCaseSitemapEnumerationError("a sitemap lead escaped provisional zero-credit review")


__all__ = [
    "GTMPublicCaseSitemapEnumerationError",
    "enumerate_public_case_sitemaps",
    "verify_public_case_sitemap_enumeration",
]
