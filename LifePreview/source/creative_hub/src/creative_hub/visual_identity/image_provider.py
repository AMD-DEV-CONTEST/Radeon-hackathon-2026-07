"""Bounded Wikimedia Commons image discovery for visual identity research.

This module intentionally does not share the text Research/Reader fallback path.
A successful empty result is a terminal search receipt; provider or schema failures
raise a retryable failure and can never authorize synthetic-image fallback.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import html
import json
import re
from typing import Any, Literal
from urllib.parse import urlsplit

import httpx


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_HTML_TAG_RE = re.compile(r"<[^>]*>")
_SPACE_RE = re.compile(r"\s+")
_URI_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
_TOOL_RE = re.compile(
    r"(^|\s)(?:curl|wget|powershell|pwsh|cmd|bash|sh|ssh|scp|ftp)(?:\s|$)",
    re.IGNORECASE,
)
_ALLOWED_SEARCH_HOST = "commons.wikimedia.org"
_ALLOWED_IMAGE_HOST = "upload.wikimedia.org"


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _bytes_sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _require_sha256(value: str, field_name: str) -> str:
    if type(value) is not str or not _SHA256_RE.fullmatch(value):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")
    return value


def _require_identifier(value: str, field_name: str) -> str:
    if type(value) is not str or not _IDENTIFIER_RE.fullmatch(value):
        raise ValueError(f"{field_name} must be a safe identifier")
    return value


def _plain_text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    unescaped = html.unescape(_HTML_TAG_RE.sub(" ", value))
    return _SPACE_RE.sub(" ", unescaped).strip()


def _metadata_value(metadata: dict[str, object], key: str) -> str:
    entry = metadata.get(key)
    if not isinstance(entry, dict):
        return ""
    return _plain_text(entry.get("value"))


def _canonical_https_url(
    value: object,
    *,
    expected_host: str,
    field_name: str,
) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field_name} must be an HTTPS URL")
    if "\\" in value:
        raise ValueError(f"{field_name} contains a forbidden path separator")
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.hostname is None
        or parsed.hostname.lower() != expected_host
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in (None, 443)
        or parsed.query
        or parsed.fragment
        or not parsed.path.startswith("/")
        or "/../" in f"{parsed.path}/"
    ):
        raise ValueError(f"{field_name} is not an approved canonical HTTPS URL")
    return value


@dataclass(frozen=True, slots=True)
class ControlledImageQuery:
    """One query from a previously frozen controlled-query plan."""

    plan_id: str
    plan_sha256: str
    query_ordinal: int
    query_text: str

    def __post_init__(self) -> None:
        _require_identifier(self.plan_id, "plan_id")
        _require_sha256(self.plan_sha256, "plan_sha256")
        if type(self.query_ordinal) is not int or not 1 <= self.query_ordinal <= 4:
            raise ValueError("query_ordinal must be an integer from 1 through 4")
        if type(self.query_text) is not str:
            raise ValueError("query_text must be a controlled string")
        query = self.query_text.strip()
        if (
            not query
            or len(query) > 240
            or _URI_RE.match(query)
            or query.startswith(("/", "\\", "../", "..\\"))
            or "../" in query
            or "..\\" in query
            or _TOOL_RE.search(query)
        ):
            raise ValueError("query_text is not a controlled image query")
        object.__setattr__(self, "query_text", query)


@dataclass(frozen=True, slots=True)
class SearchExecutionReceipt:
    plan_id: str
    plan_sha256: str
    query_ordinal: int
    query_text: str
    search_service: str
    search_tool: str
    search_schema_revision: str
    status: Literal["terminal_succeeded"]
    result_count: int
    request_sha256: str
    response_sha256: str
    completed_at: str
    receipt_sha256: str


@dataclass(frozen=True, slots=True)
class WikimediaImageCandidate:
    candidate_id: str
    search_rank: int
    plan_id: str
    plan_sha256: str
    query_ordinal: int
    query_text: str
    search_service: str
    search_tool: str
    search_schema_revision: str
    search_receipt_sha256: str
    search_request_sha256: str
    search_response_sha256: str
    source_page_url: str
    image_url: str
    source_domain: str
    creator: str
    publication_date: str | None
    license_status: Literal[
        "public_domain", "licensed_reuse", "unknown", "restricted"
    ]
    license_reference: str
    attribution: str
    locator_sha256: str
    candidate_sha256: str


@dataclass(frozen=True, slots=True)
class WikimediaSearchResult:
    receipt: SearchExecutionReceipt
    candidates: tuple[WikimediaImageCandidate, ...]


class ImageSearchRetryableError(RuntimeError):
    """A search infrastructure failure that must not be treated as zero results."""

    failed_stage = "search"

    def __init__(self, safe_error_code: str) -> None:
        self.safe_error_code = safe_error_code
        super().__init__(f"image search failed: {safe_error_code}")


class WikimediaCommonsImageProvider:
    """Dedicated Wikimedia Commons image search provider."""

    endpoint = "https://commons.wikimedia.org/w/api.php"
    search_service = "wikimedia_commons"
    search_tool = "mediawiki_generator_search"
    search_schema_revision = "wikimedia-image-search.v1"

    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        max_results: int = 10,
    ) -> None:
        if type(max_results) is not int or not 1 <= max_results <= 25:
            raise ValueError("max_results must be an integer from 1 through 25")
        self._client = client or httpx.Client(
            timeout=httpx.Timeout(20.0),
            trust_env=False,
            follow_redirects=False,
        )
        self._max_results = max_results

    def search(self, query: ControlledImageQuery) -> WikimediaSearchResult:
        if not isinstance(query, ControlledImageQuery):
            raise TypeError("query must be ControlledImageQuery")
        # Revalidate even frozen instances so an unsafe query never reaches transport.
        query = ControlledImageQuery(
            query.plan_id,
            query.plan_sha256,
            query.query_ordinal,
            query.query_text,
        )
        params: dict[str, str] = {
            "action": "query",
            "generator": "search",
            "gsrsearch": query.query_text,
            "gsrnamespace": "6",
            "gsrlimit": str(self._max_results),
            "prop": "imageinfo",
            "iiprop": "url|extmetadata",
            "format": "json",
            "formatversion": "2",
        }
        request_sha256 = _canonical_sha256(
            {
                "method": "GET",
                "endpoint": self.endpoint,
                "params": params,
                "plan_sha256": query.plan_sha256,
                "query_ordinal": query.query_ordinal,
            }
        )
        try:
            response = self._client.get(
                self.endpoint,
                params=params,
                follow_redirects=False,
            )
        except httpx.HTTPError as exc:
            raise ImageSearchRetryableError("transport_failure") from exc
        if response.status_code == 429 or response.status_code >= 500:
            raise ImageSearchRetryableError("provider_unavailable")
        if response.status_code != 200 or response.history:
            raise ImageSearchRetryableError("provider_response_invalid")

        response_sha256 = _bytes_sha256(response.content)
        try:
            payload = response.json()
            if not isinstance(payload, dict):
                raise TypeError("root")
            query_payload = payload.get("query")
            if query_payload is None and payload.get("batchcomplete") is True:
                pages = []
            elif isinstance(query_payload, dict):
                pages = query_payload.get("pages", [])
                if not isinstance(pages, list):
                    raise TypeError("pages")
            else:
                raise TypeError("query")
            parsed_pages = [self._parse_page(page) for page in pages]
        except (TypeError, ValueError, KeyError, IndexError, json.JSONDecodeError) as exc:
            raise ImageSearchRetryableError("provider_schema_invalid") from exc

        completed_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        receipt_payload = {
            "plan_id": query.plan_id,
            "plan_sha256": query.plan_sha256,
            "query_ordinal": query.query_ordinal,
            "query_text": query.query_text,
            "search_service": self.search_service,
            "search_tool": self.search_tool,
            "search_schema_revision": self.search_schema_revision,
            "status": "terminal_succeeded",
            "result_count": len(parsed_pages),
            "request_sha256": request_sha256,
            "response_sha256": response_sha256,
            "completed_at": completed_at,
        }
        receipt = SearchExecutionReceipt(
            **receipt_payload,
            receipt_sha256=_canonical_sha256(receipt_payload),
        )
        candidates = tuple(
            self._candidate_from_page(
                page,
                rank=rank,
                query=query,
                receipt=receipt,
            )
            for rank, page in enumerate(parsed_pages, start=1)
        )
        return WikimediaSearchResult(receipt=receipt, candidates=candidates)

    @staticmethod
    def _parse_page(page: object) -> dict[str, object]:
        if not isinstance(page, dict):
            raise TypeError("page")
        page_id = page.get("pageid")
        title = page.get("title")
        image_info = page.get("imageinfo")
        if type(page_id) is not int or not isinstance(title, str):
            raise TypeError("page identity")
        if not isinstance(image_info, list) or len(image_info) != 1:
            raise TypeError("imageinfo")
        info = image_info[0]
        if not isinstance(info, dict):
            raise TypeError("imageinfo item")
        image_url = _canonical_https_url(
            info.get("url"),
            expected_host=_ALLOWED_IMAGE_HOST,
            field_name="image_url",
        )
        source_page_url = _canonical_https_url(
            info.get("descriptionurl"),
            expected_host=_ALLOWED_SEARCH_HOST,
            field_name="source_page_url",
        )
        metadata = info.get("extmetadata")
        if not isinstance(metadata, dict):
            raise TypeError("extmetadata")
        return {
            "page_id": page_id,
            "title": title.strip(),
            "image_url": image_url,
            "source_page_url": source_page_url,
            "metadata": metadata,
        }

    def _candidate_from_page(
        self,
        page: dict[str, object],
        *,
        rank: int,
        query: ControlledImageQuery,
        receipt: SearchExecutionReceipt,
    ) -> WikimediaImageCandidate:
        metadata = page["metadata"]
        if not isinstance(metadata, dict):  # defensive after _parse_page
            raise ImageSearchRetryableError("provider_schema_invalid")
        license_name = _metadata_value(metadata, "LicenseShortName")
        license_reference = _metadata_value(metadata, "LicenseUrl")
        creator = _metadata_value(metadata, "Artist")
        credit = _metadata_value(metadata, "Credit")
        attribution = " — ".join(part for part in (creator, credit) if part)
        license_status = self._license_status(license_name)
        if license_status in {"public_domain", "licensed_reuse"} and (
            not license_reference or not attribution
        ):
            # A provider label alone cannot establish reusable-license authority.
            license_status = "unknown"
        publication = _metadata_value(metadata, "DateTimeOriginal") or _metadata_value(
            metadata, "DateTime"
        )
        publication_date = publication[:10] if re.match(r"^\d{4}-\d{2}-\d{2}", publication) else None
        page_id = page["page_id"]
        image_url = str(page["image_url"])
        source_page_url = str(page["source_page_url"])
        locator_payload = {
            "source_page_url": source_page_url,
            "image_url": image_url,
            "page_id": page_id,
            "search_receipt_sha256": receipt.receipt_sha256,
        }
        candidate_payload = {
            "candidate_id": f"wikimedia.{page_id}",
            "search_rank": rank,
            "plan_id": query.plan_id,
            "plan_sha256": query.plan_sha256,
            "query_ordinal": query.query_ordinal,
            "query_text": query.query_text,
            "search_service": self.search_service,
            "search_tool": self.search_tool,
            "search_schema_revision": self.search_schema_revision,
            "search_receipt_sha256": receipt.receipt_sha256,
            "search_request_sha256": receipt.request_sha256,
            "search_response_sha256": receipt.response_sha256,
            "source_page_url": source_page_url,
            "image_url": image_url,
            "source_domain": _ALLOWED_SEARCH_HOST,
            "creator": creator,
            "publication_date": publication_date,
            "license_status": license_status,
            "license_reference": license_reference,
            "attribution": attribution,
            "locator_sha256": _canonical_sha256(locator_payload),
        }
        return WikimediaImageCandidate(
            **candidate_payload,
            candidate_sha256=_canonical_sha256(candidate_payload),
        )

    @staticmethod
    def _license_status(
        license_name: str,
    ) -> Literal["public_domain", "licensed_reuse", "unknown", "restricted"]:
        normalized = license_name.casefold()
        if any(mark in normalized for mark in ("public domain", "public-domain", "cc0")):
            return "public_domain"
        if any(mark in normalized for mark in ("cc by", "cc-by", "gfdl")):
            return "licensed_reuse"
        if any(mark in normalized for mark in ("fair use", "copyrighted", "restricted")):
            return "restricted"
        return "unknown"


__all__ = [
    "ControlledImageQuery",
    "ImageSearchRetryableError",
    "SearchExecutionReceipt",
    "WikimediaCommonsImageProvider",
    "WikimediaImageCandidate",
    "WikimediaSearchResult",
]

