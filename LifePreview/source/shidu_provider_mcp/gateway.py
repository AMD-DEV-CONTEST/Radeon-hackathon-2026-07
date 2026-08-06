from __future__ import annotations

import argparse
import hashlib
import http.client
import ipaddress
import json
import os
import re
import socket
import ssl
import stat
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Protocol
from urllib.parse import quote, urlsplit, urlunsplit

import httpx
from bs4 import BeautifulSoup
from mcp.server.fastmcp import FastMCP
from pydantic import Field
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from shidu_provider_mcp.book_sources import (
    CompositeBookSearch,
    CrossrefClient,
    OpenLibraryClient,
    extract_book_title,
)


SEARCH_TOOL_NAME = "coding_plan.search"
SEARCH_SCHEMA_DIGEST = (
    "6f5b772b2612821f6290ec65f784bc6b8fd9ce6fd3e6c80164cbb5eca2c54c8f"
)
READER_TOOL_NAME = "coding_plan.read_page"
READER_SCHEMA_DIGEST = (
    "e498bbc04216f04c3c991ed99dbd14eb16a161d4f33c3d97ff34cf943f313e13"
)
SEARCH_SERVICE_VERSION = "shidu-search-mcp.v4"
READER_SERVICE_VERSION = "shidu-reader-mcp.v2"
LEGACY_KEYED_V1_PROFILE = "legacy-keyed-v1"
PUBLIC_KEYLESS_V1_PROFILE = "public-keyless-v1"
_PROVIDER_PROFILES = (LEGACY_KEYED_V1_PROFILE, PUBLIC_KEYLESS_V1_PROFILE)
SEARCH_PORT = 18110
READER_PORT = 18111
_HOST = os.getenv("SHIDU_PROVIDER_MCP_HOST", "127.0.0.1").strip() or "127.0.0.1"
_ZHIPU_CODING_PLAN_SEARCH_MCP_URL = (
    "https://open.bigmodel.cn/api/mcp/web_search_prime/mcp"
)
_ZHIPU_CODING_PLAN_SEARCH_TOOL = "web_search_prime"
_MCP_PROTOCOL_VERSION = "2024-11-05"
_MCP_SERVER_NAME = "mcp-web-search-prime"
_MEDIAWIKI_SEARCH_URL = "https://zh.wikipedia.org/w/api.php"
_MEDIAWIKI_USER_AGENT = (
    "ShiduSearchMCP/2.0 "
    "(book discovery; contact: local-operator@example.invalid)"
)
_MAX_SECRET_BYTES = 16_384
_MAX_SEARCH_RESPONSE_BYTES = 1_000_000
_MAX_MEDIAWIKI_RESPONSE_BYTES = 500_000
_MAX_MEDIAWIKI_RESULTS = 5
_MAX_READER_BYTES = 1_000_000
_SEARCH_TIMEOUT_SECONDS = 10.0
_READER_TIMEOUT_SECONDS = 10.0

SearchQuery = Annotated[str, Field(min_length=1, max_length=70)]
SearchLimit = Annotated[int, Field(ge=1, le=20)]
ReaderURL = Annotated[str, Field(min_length=1, max_length=2_048)]
ApprovedAddresses = Annotated[list[str], Field(min_length=1, max_length=16)]


class ProviderGatewayError(RuntimeError):
    """可安全返回给调用方的低细节网关错误。"""


class ProviderRequestError(ProviderGatewayError):
    """调用方提供的工具参数或安全策略无效。"""


class ProviderUpstreamError(ProviderGatewayError):
    """上游响应、网络或安全证明无效。"""


class SearchProvider(Protocol):
    def search(self, query: str, *, max_results: int) -> dict[str, Any]: ...


class BookAwareSearch:
    """Route discovery-shaped queries to catalogues and research elsewhere."""

    def __init__(
        self,
        *,
        catalogues: SearchProvider,
        generic_search: SearchProvider,
    ) -> None:
        self._catalogues = catalogues
        self._generic_search = generic_search

    def search(self, query: str, *, max_results: int) -> dict[str, Any]:
        query, max_results = _validated_search_arguments(query, max_results)
        if extract_book_title(query) is not None:
            try:
                result = self._catalogues.search(query, max_results=max_results)
            except Exception:
                result = {"hits": []}
            if (
                isinstance(result, Mapping)
                and isinstance(result.get("hits"), list)
                and result["hits"]
            ):
                return dict(result)
        return self._generic_search.search(query, max_results=max_results)


def _read_secret(path: Path) -> str:
    try:
        info = path.lstat()
        if (
            path.is_symlink()
            or not stat.S_ISREG(info.st_mode)
            or info.st_size < 1
            or info.st_size > _MAX_SECRET_BYTES
        ):
            raise OSError
        value = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        raise ProviderGatewayError("search secret file is unavailable") from None
    if not value or any(character.isspace() for character in value):
        raise ProviderGatewayError("search secret file is invalid")
    return value


def _safe_result_url(value: object) -> str | None:
    if not isinstance(value, str) or not value or len(value) > 2_048:
        return None
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError:
        return None
    if (
        parts.scheme not in {"http", "https"}
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or port not in {None, 80, 443}
    ):
        return None
    return value


def _validated_search_arguments(query: object, max_results: object) -> tuple[str, int]:
    if not isinstance(query, str) or not query.strip() or len(query.strip()) > 70:
        raise ProviderRequestError("search query is invalid")
    if (
        isinstance(max_results, bool)
        or not isinstance(max_results, int)
        or not 1 <= max_results <= 20
    ):
        raise ProviderRequestError("search result limit is invalid")
    return query.strip(), max_results


def _bounded_json_response(
    response: httpx.Response, *, max_response_bytes: int
) -> object:
    length = response.headers.get("content-length")
    if length is not None:
        try:
            declared_length = int(length)
        except ValueError:
            raise ProviderUpstreamError("search provider response is invalid") from None
        if declared_length < 0 or declared_length > max_response_bytes:
            raise ProviderUpstreamError("search provider response is too large")
    body = bytearray()
    for chunk in response.iter_bytes(chunk_size=65_536):
        if len(body) + len(chunk) > max_response_bytes:
            raise ProviderUpstreamError("search provider response is too large")
        body.extend(chunk)
    try:
        return json.loads(bytes(body))
    except (UnicodeError, ValueError):
        raise ProviderUpstreamError("search provider response is invalid") from None


def _book_title_rank(query: str, title: str) -> int:
    def normalise(value: str) -> str:
        return "".join(character.casefold() for character in value if character.isalnum())

    normalised_query = normalise(query)
    normalised_title = normalise(title)
    if normalised_query == normalised_title:
        return 0
    if normalised_query and normalised_query in normalised_title:
        return 1
    return 2


def _mediawiki_book_query(query: str) -> str:
    """Remove only the fixed bibliographic hints used by book discovery."""

    simplified = re.sub(
        r"(?:\s+(?:书籍|图书|作者|版本|版次|译者|出版社)){2,}\s*$",
        "",
        query,
    ).strip()
    return simplified or query


class MediaWikiSearch:
    """无需密钥的中文维基百科书名搜索后备。"""

    def __init__(self, *, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(
            timeout=_SEARCH_TIMEOUT_SECONDS,
            follow_redirects=False,
            trust_env=False,
        )
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def search(self, query: str, *, max_results: int) -> dict[str, Any]:
        query, max_results = _validated_search_arguments(query, max_results)
        search_query = _mediawiki_book_query(query)
        fallback_limit = min(max_results, _MAX_MEDIAWIKI_RESULTS)
        try:
            with self._client.stream(
                "GET",
                _MEDIAWIKI_SEARCH_URL,
                params={
                    "action": "query",
                    "list": "search",
                    "srsearch": search_query,
                    "srnamespace": "0",
                    "srlimit": str(fallback_limit),
                    "srprop": "snippet",
                    "format": "json",
                    "formatversion": "2",
                },
                headers={"User-Agent": _MEDIAWIKI_USER_AGENT},
                timeout=_SEARCH_TIMEOUT_SECONDS,
                follow_redirects=False,
            ) as response:
                response.raise_for_status()
                raw = _bounded_json_response(
                    response, max_response_bytes=_MAX_MEDIAWIKI_RESPONSE_BYTES
                )
        except ProviderGatewayError:
            raise
        except httpx.HTTPError:
            raise ProviderUpstreamError("search fallback is unavailable") from None
        if not isinstance(raw, Mapping):
            raise ProviderUpstreamError("search fallback response is invalid")
        query_payload = raw.get("query")
        if not isinstance(query_payload, Mapping) or not isinstance(
            query_payload.get("search"), list
        ):
            raise ProviderUpstreamError("search fallback response is invalid")
        ranked_hits: list[tuple[int, int, dict[str, str]]] = []
        for index, item in enumerate(query_payload["search"]):
            if not isinstance(item, Mapping):
                continue
            page_id = item.get("pageid")
            title = item.get("title")
            if (
                isinstance(page_id, bool)
                or not isinstance(page_id, int)
                or page_id <= 0
                or not isinstance(title, str)
                or not title.strip()
                or len(title.strip()) > 500
                or any(ord(character) < 32 for character in title)
            ):
                continue
            title = title.strip()
            result_url = _safe_result_url(
                "https://zh.wikipedia.org/wiki/"
                + quote(title.replace(" ", "_"), safe="")
            )
            if result_url is None:
                continue
            snippet = item.get("snippet", "")
            if not isinstance(snippet, str):
                snippet = ""
            snippet = BeautifulSoup(snippet, "html.parser").get_text("", strip=True)
            ranked_hits.append(
                (
                    _book_title_rank(search_query, title),
                    index,
                    {
                        "title": title,
                        "url": result_url,
                        "snippet": snippet[:5_000],
                    },
                )
            )
        ranked_hits.sort(key=lambda item: (item[0], item[1]))
        return {"hits": [item[2] for item in ranked_hits[:fallback_limit]]}


class _RetryableSearchError(RuntimeError):
    """专属搜索 MCP 可安全转入后备数据源的短暂故障。"""


def _bounded_response_body(
    response: httpx.Response, *, max_response_bytes: int
) -> bytes:
    length = response.headers.get("content-length")
    if length is not None:
        try:
            declared_length = int(length)
        except ValueError:
            raise ProviderUpstreamError("search provider response is invalid") from None
        if declared_length < 0 or declared_length > max_response_bytes:
            raise ProviderUpstreamError("search provider response is too large")
    body = bytearray()
    for chunk in response.iter_bytes(chunk_size=65_536):
        if len(body) + len(chunk) > max_response_bytes:
            raise ProviderUpstreamError("search provider response is too large")
        body.extend(chunk)
    return bytes(body)


def _mcp_json_response(
    response: httpx.Response, *, expected_id: int, secret: str
) -> Mapping[str, Any]:
    body = _bounded_response_body(
        response, max_response_bytes=_MAX_SEARCH_RESPONSE_BYTES
    )
    try:
        text = body.decode("utf-8")
    except UnicodeError:
        raise ProviderUpstreamError("search provider response is invalid") from None
    if secret in text:
        raise ProviderUpstreamError("search provider response is invalid")
    content_type = response.headers.get("content-type", "").lower()
    json_values: list[object] = []
    try:
        if content_type.startswith("text/event-stream"):
            for event in re.split(r"\r?\n\r?\n", text):
                data = "\n".join(
                    line[5:].lstrip()
                    for line in event.splitlines()
                    if line.startswith("data:")
                )
                if data:
                    json_values.append(json.loads(data))
        elif content_type.startswith("application/json") or not content_type:
            json_values.append(json.loads(text))
        else:
            raise ValueError
    except (TypeError, ValueError):
        raise ProviderUpstreamError("search provider response is invalid") from None
    for value in json_values:
        if (
            isinstance(value, Mapping)
            and value.get("jsonrpc") == "2.0"
            and value.get("id") == expected_id
        ):
            if "error" in value or not isinstance(value.get("result"), Mapping):
                raise ProviderUpstreamError("search provider response is invalid")
            return value["result"]
    raise ProviderUpstreamError("search provider response is invalid")


def _valid_mcp_session_id(value: object) -> str:
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= 512
        or any(ord(character) < 0x21 or ord(character) > 0x7E for character in value)
    ):
        raise ProviderUpstreamError("search provider response is invalid")
    return value


class CodingPlanWebSearchMCP:
    """通过智谱 Coding Plan 专属 Web Search MCP 执行研究检索。"""

    def __init__(
        self,
        *,
        key_file: Path | str,
        client: httpx.Client | None = None,
        fallback: SearchProvider | None = None,
    ) -> None:
        self._key_file = Path(key_file)
        self._api_key = _read_secret(self._key_file)
        self._client = client or httpx.Client(
            timeout=_SEARCH_TIMEOUT_SECONDS,
            follow_redirects=False,
            trust_env=False,
        )
        self._owns_client = client is None
        self._fallback = fallback

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def search(self, query: str, *, max_results: int) -> dict[str, Any]:
        query, max_results = _validated_search_arguments(query, max_results)
        try:
            initialize = self._request(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": _MCP_PROTOCOL_VERSION,
                        "capabilities": {},
                        "clientInfo": {"name": "shidu-search-mcp", "version": "4"},
                    },
                },
                expected_id=1,
            )
            result, response = initialize
            session_id = _valid_mcp_session_id(
                response.headers.get("mcp-session-id")
            )
            server_info = result.get("serverInfo")
            if (
                result.get("protocolVersion") != _MCP_PROTOCOL_VERSION
                or not isinstance(server_info, Mapping)
                or server_info.get("name") != _MCP_SERVER_NAME
            ):
                raise ProviderUpstreamError("search provider response is invalid")
            self._notify_initialized(session_id)
            tool_result, _ = self._request(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {
                        "name": _ZHIPU_CODING_PLAN_SEARCH_TOOL,
                        "arguments": {
                            "search_query": query,
                            "search_recency_filter": "noLimit",
                            "content_size": "medium",
                            "location": "cn" if _contains_cjk(query) else "us",
                        },
                    },
                },
                session_id=session_id,
                expected_id=2,
            )
            return self._project_tool_result(tool_result, max_results=max_results)
        except _RetryableSearchError:
            return self._fallback_search(query, max_results=max_results)
        except ProviderGatewayError:
            raise
        except httpx.TransportError:
            return self._fallback_search(query, max_results=max_results)
        except httpx.HTTPError:
            raise ProviderUpstreamError("search provider is unavailable") from None

    def _headers(self, session_id: str | None = None) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }
        if session_id is not None:
            headers["Mcp-Session-Id"] = session_id
            headers["MCP-Protocol-Version"] = _MCP_PROTOCOL_VERSION
        return headers

    def _request(
        self,
        payload: Mapping[str, Any],
        *,
        expected_id: int,
        session_id: str | None = None,
    ) -> tuple[Mapping[str, Any], httpx.Response]:
        with self._client.stream(
            "POST",
            _ZHIPU_CODING_PLAN_SEARCH_MCP_URL,
            headers=self._headers(session_id),
            json=payload,
            timeout=_SEARCH_TIMEOUT_SECONDS,
            follow_redirects=False,
        ) as response:
            if response.status_code == 429 or response.status_code >= 500:
                raise _RetryableSearchError
            response.raise_for_status()
            return (
                _mcp_json_response(
                    response, expected_id=expected_id, secret=self._api_key
                ),
                response,
            )

    def _notify_initialized(self, session_id: str) -> None:
        with self._client.stream(
            "POST",
            _ZHIPU_CODING_PLAN_SEARCH_MCP_URL,
            headers=self._headers(session_id),
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
            timeout=_SEARCH_TIMEOUT_SECONDS,
            follow_redirects=False,
        ) as response:
            if response.status_code == 429 or response.status_code >= 500:
                raise _RetryableSearchError
            response.raise_for_status()
            _bounded_response_body(
                response, max_response_bytes=_MAX_SEARCH_RESPONSE_BYTES
            )

    def _project_tool_result(
        self, result: Mapping[str, Any], *, max_results: int
    ) -> dict[str, Any]:
        if result.get("isError") is True:
            raise _RetryableSearchError
        if result.get("isError") is not False:
            raise ProviderUpstreamError("search provider response is invalid")
        content = result.get("content")
        if not isinstance(content, list) or len(content) != 1:
            raise ProviderUpstreamError("search provider response is invalid")
        item = content[0]
        if (
            not isinstance(item, Mapping)
            or item.get("type") != "text"
            or not isinstance(item.get("text"), str)
        ):
            raise ProviderUpstreamError("search provider response is invalid")
        raw_results: object = item["text"]
        if self._api_key in raw_results:
            raise ProviderUpstreamError("search provider response is invalid")
        for _ in range(3):
            if not isinstance(raw_results, str):
                break
            try:
                raw_results = json.loads(raw_results)
            except ValueError:
                raise ProviderUpstreamError(
                    "search provider response is invalid"
                ) from None
        if not isinstance(raw_results, list) or _contains_secret(
            raw_results, self._api_key
        ):
            raise ProviderUpstreamError("search provider response is invalid")
        hits: list[dict[str, str]] = []
        for candidate in raw_results:
            if not isinstance(candidate, Mapping):
                continue
            url = _safe_result_url(candidate.get("link"))
            title = candidate.get("title")
            if url is None or not isinstance(title, str) or not title.strip():
                continue
            snippet = candidate.get("content", "")
            if not isinstance(snippet, str):
                snippet = ""
            hits.append(
                {
                    "title": title.strip()[:500],
                    "url": url,
                    "snippet": snippet.strip()[:5_000],
                }
            )
            if len(hits) >= max_results:
                break
        return {"hits": hits}

    def _fallback_search(self, query: str, *, max_results: int) -> dict[str, Any]:
        if self._fallback is None:
            raise ProviderUpstreamError("search provider is unavailable")
        try:
            return self._fallback.search(query, max_results=max_results)
        except ProviderGatewayError:
            raise
        except Exception:
            raise ProviderUpstreamError("search fallback is unavailable") from None


def _contains_cjk(value: str) -> bool:
    return any(
        "\u3400" <= character <= "\u4dbf"
        or "\u4e00" <= character <= "\u9fff"
        or "\uf900" <= character <= "\ufaff"
        for character in value
    )


def _contains_secret(value: object, secret: str) -> bool:
    if isinstance(value, str):
        return secret in value
    if isinstance(value, Mapping):
        return any(
            _contains_secret(key, secret) or _contains_secret(item, secret)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(_contains_secret(item, secret) for item in value)
    return False


@dataclass(frozen=True, slots=True)
class FetchResponse:
    status_code: int
    headers: Mapping[str, str]
    body: bytes
    resolved_address: str


Fetcher = Callable[..., FetchResponse]


def _public_addresses(values: Sequence[str]) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)) or not 1 <= len(values) <= 16:
        raise ProviderRequestError("approved public addresses are invalid")
    output: list[str] = []
    for value in values:
        if not isinstance(value, str) or "%" in value:
            raise ProviderRequestError("approved public addresses are invalid")
        try:
            address = ipaddress.ip_address(value)
        except ValueError:
            raise ProviderRequestError("approved public addresses are invalid") from None
        if (
            not address.is_global
            or address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_multicast
            or address.is_reserved
            or address.is_unspecified
        ):
            raise ProviderRequestError("approved address must be public")
        compressed = address.compressed
        if compressed in output:
            raise ProviderRequestError("approved public addresses are invalid")
        output.append(compressed)
    return tuple(output)


def _validated_https_url(url: str) -> tuple[str, str, int, str]:
    if (
        not isinstance(url, str)
        or not 1 <= len(url) <= 2_048
        or any(character.isspace() or ord(character) < 32 for character in url)
        or "\\" in url
    ):
        raise ProviderRequestError("reader URL is invalid")
    try:
        parts = urlsplit(url)
        port = parts.port or 443
    except ValueError:
        raise ProviderRequestError("reader URL is invalid") from None
    if (
        parts.scheme != "https"
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or port != 443
        or parts.fragment
    ):
        raise ProviderRequestError("reader URL is invalid")
    host = parts.hostname.encode("idna").decode("ascii").lower().rstrip(".")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise ProviderRequestError("reader URL is invalid")
    target = urlunsplit(("", "", parts.path or "/", parts.query, ""))
    return host, parts.hostname, port, target


def _assert_approved_peer(
    connection: socket.socket | ssl.SSLSocket, approved_address: str
) -> None:
    peer = connection.getpeername()
    try:
        peer_address = ipaddress.ip_address(peer[0])
    except (IndexError, TypeError, ValueError):
        raise ProviderUpstreamError(
            "reader resolved address was not approved"
        ) from None
    if peer_address != ipaddress.ip_address(approved_address):
        raise ProviderUpstreamError("reader resolved address was not approved")


def _fetch_pinned_https(
    *,
    url: str,
    approved_addresses: tuple[str, ...],
    timeout_seconds: float,
    max_response_bytes: int,
    request_headers: Mapping[str, str] | None = None,
) -> FetchResponse:
    host, _original_host, port, target = _validated_https_url(url)
    context = ssl.create_default_context()
    last_error: Exception | None = None
    for address in approved_addresses:
        raw_socket: socket.socket | None = None
        tls_socket: ssl.SSLSocket | None = None
        try:
            raw_socket = socket.create_connection(
                (address, port), timeout=timeout_seconds
            )
            _assert_approved_peer(raw_socket, address)
            tls_socket = context.wrap_socket(raw_socket, server_hostname=host)
            raw_socket = None
            _assert_approved_peer(tls_socket, address)
            additional_headers = "".join(
                f"{name}: {value}\r\n"
                for name, value in (request_headers or {}).items()
            )
            request = (
                f"GET {target} HTTP/1.1\r\n"
                f"Host: {host}\r\n"
                "User-Agent: ShiduReaderMCP/1.0\r\n"
                "Accept: text/html,application/xhtml+xml,application/json,"
                "application/ld+json,text/plain,text/markdown\r\n"
                "Accept-Encoding: identity\r\n"
                f"{additional_headers}"
                "Connection: close\r\n\r\n"
            ).encode("ascii")
            tls_socket.sendall(request)
            response = http.client.HTTPResponse(tls_socket)
            response.begin()
            headers = {key.casefold(): value for key, value in response.getheaders()}
            length = headers.get("content-length")
            if length is not None and int(length) > max_response_bytes:
                raise ProviderUpstreamError("reader response is too large")
            body = response.read(max_response_bytes + 1)
            if len(body) > max_response_bytes:
                raise ProviderUpstreamError("reader response is too large")
            return FetchResponse(
                status_code=response.status,
                headers=headers,
                body=body,
                resolved_address=address,
            )
        except ProviderGatewayError:
            raise
        except (OSError, ssl.SSLError, http.client.HTTPException, ValueError) as error:
            last_error = error
        finally:
            if tls_socket is not None:
                tls_socket.close()
            if raw_socket is not None:
                raw_socket.close()
    raise ProviderUpstreamError("reader provider is unavailable") from last_error


def _decoded_body(response: FetchResponse) -> tuple[str, str]:
    content_type = response.headers.get("content-type", "").casefold()
    media_type = content_type.split(";", 1)[0].strip()
    if media_type not in {
        "text/html",
        "application/xhtml+xml",
        "text/plain",
        "text/markdown",
        "application/json",
        "application/ld+json",
    }:
        raise ProviderUpstreamError("reader content type is unsupported")
    charset = "utf-8"
    for part in content_type.split(";")[1:]:
        key, separator, value = part.partition("=")
        if separator and key.strip() == "charset":
            charset = value.strip().strip('"') or "utf-8"
            break
    try:
        text = response.body.decode(charset, errors="replace")
    except LookupError:
        text = response.body.decode("utf-8", errors="replace")
    return media_type, text


def _first_text(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        for item in value:
            text = _first_text(item)
            if text:
                return text
    return ""


def _language_value(value: object) -> str:
    text = _first_text(value)
    if text.startswith("/languages/"):
        text = text.rsplit("/", 1)[-1]
    return {
        "chi": "zh-CN",
        "zho": "zh-CN",
        "zh": "zh-CN",
        "zh-cn": "zh-CN",
        "zh-hans": "zh-CN",
        "zh-tw": "zh-TW",
        "zh-hant": "zh-TW",
        "eng": "en",
    }.get(text.casefold(), text)


def _crossref_author(value: object) -> str:
    if not isinstance(value, list):
        return ""
    names: list[str] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        literal = _first_text(item.get("name"))
        if not literal:
            literal = " ".join(
                part
                for part in (
                    _first_text(item.get("given")),
                    _first_text(item.get("family")),
                )
                if part
            )
        if literal and literal not in names:
            names.append(literal)
    return "、".join(names)


def _json_book_fields(url: str, value: object) -> tuple[str, dict[str, str], str]:
    host = (urlsplit(url).hostname or "").casefold()
    fields: dict[str, str] = {}
    description = ""
    source_title = host or "结构化书目"

    if host == "openlibrary.org" and isinstance(value, Mapping):
        raw = value
        docs = raw.get("docs")
        if isinstance(docs, list) and docs and isinstance(docs[0], Mapping):
            raw = docs[0]
        fields = {
            "书名": _first_text(raw.get("title")),
            "作者": "、".join(
                item.strip()
                for item in raw.get("author_name", [])
                if isinstance(item, str) and item.strip()
            ) if isinstance(raw.get("author_name"), list) else "",
            "语言": _language_value(raw.get("language")),
            "版本": _first_text(raw.get("publish_date"))
            or _first_text(raw.get("first_publish_year")),
        }
        source_title = fields["书名"] or source_title
    elif host == "api.crossref.org" and isinstance(value, Mapping):
        raw = value.get("message")
        if isinstance(raw, Mapping):
            fields = {
                "书名": _first_text(raw.get("title")),
                "作者": _crossref_author(raw.get("author")),
                "语言": _language_value(raw.get("language")),
                "版本": _first_text(raw.get("published-print"))
                or _first_text(raw.get("published")),
            }
            description = _first_text(raw.get("abstract"))
            source_title = fields["书名"] or source_title
    elif host == "www.googleapis.com" and isinstance(value, Mapping):
        raw = value.get("volumeInfo")
        if isinstance(raw, Mapping):
            authors = raw.get("authors")
            fields = {
                "书名": _first_text(raw.get("title")),
                "作者": "、".join(
                    item.strip()
                    for item in authors
                    if isinstance(item, str) and item.strip()
                ) if isinstance(authors, list) else "",
                "语言": _language_value(raw.get("language")),
                "版本": _first_text(raw.get("publishedDate")),
            }
            description = _first_text(raw.get("description"))
            source_title = fields["书名"] or source_title
    return source_title[:500], {
        key: item for key, item in fields.items() if item
    }, description


def _json_ld_book_fields(soup: BeautifulSoup) -> dict[str, str]:
    for node in soup.select('script[type="application/ld+json"]'):
        try:
            raw = json.loads(node.string or node.get_text("", strip=True))
        except (TypeError, ValueError):
            continue
        candidates = raw if isinstance(raw, list) else [raw]
        for item in candidates:
            if not isinstance(item, Mapping):
                continue
            if item.get("@type") not in {"Book", "Audiobook"}:
                graph = item.get("@graph")
                if isinstance(graph, list):
                    candidates.extend(graph)
                continue
            author = item.get("author")
            if isinstance(author, Mapping):
                author = author.get("name")
            elif isinstance(author, list):
                author = "、".join(
                    _first_text(value.get("name") if isinstance(value, Mapping) else value)
                    for value in author
                )
            return {
                "书名": _first_text(item.get("name")),
                "作者": _first_text(author),
                "语言": _language_value(item.get("inLanguage")),
                "版本": _first_text(item.get("datePublished")),
            }
    return {}


def _html_meta_book_fields(soup: BeautifulSoup) -> dict[str, str]:
    fields = _json_ld_book_fields(soup)
    selectors = {
        "书名": (
            'meta[name="DC.title"]',
            'meta[name="citation_title"]',
            'meta[property="og:title"]',
        ),
        "作者": (
            'meta[name="DC.creator"]',
            'meta[name="citation_author"]',
            'meta[name="author"]',
        ),
        "语言": ('meta[name="DC.language"]', 'meta[http-equiv="content-language"]'),
        "版本": ('meta[name="citation_publication_date"]',),
    }
    for name, alternatives in selectors.items():
        if fields.get(name):
            continue
        for selector in alternatives:
            node = soup.select_one(selector)
            value = _first_text(node.get("content") if node is not None else None)
            if value:
                fields[name] = _language_value(value) if name == "语言" else value
                break
    return {key: value for key, value in fields.items() if value}


def _extract_text(*, url: str, media_type: str, text: str) -> tuple[str, str]:
    if media_type in {"text/plain", "text/markdown"}:
        title = urlsplit(url).hostname or "来源页面"
        content = "\n".join(line.strip() for line in text.splitlines() if line.strip())
        return title[:500], content[:_MAX_READER_BYTES]
    if media_type in {"application/json", "application/ld+json"}:
        try:
            raw = json.loads(text)
        except (TypeError, ValueError):
            raise ProviderUpstreamError("reader JSON is invalid") from None
        title, fields, description = _json_book_fields(url, raw)
        if not fields:
            raise ProviderUpstreamError("reader JSON book metadata is unavailable")
        content = "\n".join(
            [*(f"{name}：{value}" for name, value in fields.items()), description]
        ).strip()
        return title, content[:_MAX_READER_BYTES]
    soup = BeautifulSoup(text, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    metadata_fields = _html_meta_book_fields(soup)
    for node in soup(["script", "style", "noscript", "svg", "form", "nav", "footer"]):
        node.decompose()
    root = soup.find("article") or soup.find("main") or soup.body or soup
    heading = root.find(["h1", "h2"])
    heading_text = heading.get_text(" ", strip=True) if heading else ""
    structured_lines = [
        f"{field_name}：{value}"
        for field_name, value in metadata_fields.items()
    ]
    infobox = root.select_one("table.infobox")
    field_aliases = {
        "书名": "书名",
        "書名": "书名",
        "标题": "书名",
        "標題": "书名",
        "作者": "作者",
        "语言": "语言",
        "語言": "语言",
        "语种": "语言",
        "語種": "语言",
        "版本": "版本",
        "版次": "版本",
        "译者": "译者",
        "譯者": "译者",
    }
    if infobox is not None:
        seen_fields: set[str] = set(metadata_fields)
        for row in infobox.find_all("tr"):
            cells = row.find_all(["th", "td"], recursive=False)
            if len(cells) < 2:
                continue
            raw_name = cells[0].get_text(" ", strip=True)
            field_name = field_aliases.get(raw_name)
            value = cells[1].get_text(" ", strip=True)
            if field_name is None or field_name in seen_fields or not value:
                continue
            seen_fields.add(field_name)
            structured_lines.append(f"{field_name}：{value}")
    lines = [line.strip() for line in root.get_text("\n").splitlines() if line.strip()]
    projected_lines = ([f"# {heading_text}"] if heading_text else []) + structured_lines + lines
    content = "\n".join(projected_lines)[:_MAX_READER_BYTES]
    if not title:
        title = heading_text
    if not title:
        title = urlsplit(url).hostname or "来源页面"
    return title[:500], content


class PinnedPageReader:
    """仅连接调用方批准的公网 IP，不跟随重定向。"""

    def __init__(
        self,
        *,
        fetch: Fetcher | None = None,
        google_books_api_key: str = "",
    ) -> None:
        self._fetch = fetch or _fetch_pinned_https
        self._google_books_api_key = google_books_api_key

    def read(
        self,
        *,
        url: str,
        approved_resolved_addresses: Sequence[str],
        redirect_policy: str,
        prefetch_policy: str,
    ) -> dict[str, Any]:
        _validated_https_url(url)
        approved = _public_addresses(approved_resolved_addresses)
        if redirect_policy != "forbid" or prefetch_policy != "connect-approved-address-only":
            raise ProviderRequestError("reader security policy is invalid")
        try:
            fetch_arguments: dict[str, Any] = {
                "url": url,
                "approved_addresses": approved,
                "timeout_seconds": _READER_TIMEOUT_SECONDS,
                "max_response_bytes": _MAX_READER_BYTES,
            }
            parts = urlsplit(url)
            if (
                self._google_books_api_key
                and (parts.hostname or "").casefold() == "www.googleapis.com"
                and parts.path.startswith("/books/v1/volumes/")
            ):
                fetch_arguments["request_headers"] = {
                    "X-Goog-Api-Key": self._google_books_api_key
                }
            response = self._fetch(
                **fetch_arguments,
            )
        except ProviderGatewayError:
            raise
        except Exception:
            raise ProviderUpstreamError("reader provider is unavailable") from None
        if response.resolved_address not in approved:
            raise ProviderUpstreamError("reader resolved address was not approved")
        if not isinstance(response.body, bytes) or len(response.body) > _MAX_READER_BYTES:
            raise ProviderUpstreamError("reader response is too large")
        if 300 <= response.status_code < 400:
            raise ProviderUpstreamError("reader redirect is forbidden")
        if response.status_code != 200:
            raise ProviderUpstreamError("reader provider returned a failing status")
        media_type, text = _decoded_body(response)
        title, content = _extract_text(url=url, media_type=media_type, text=text)
        if not title.strip() or not content.strip():
            raise ProviderUpstreamError("reader content is empty")
        return {
            "url": url,
            "title": title,
            "content": content,
            "content_digest": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            "content_type": "text/plain",
            "security": {
                "resolved_address": response.resolved_address,
                "redirect_chain": [url],
                "redirect_policy": "forbid",
                "prefetch_policy": "connect-approved-address-only",
            },
        }


class ReaderProvider(Protocol):
    def read(self, **arguments: Any) -> dict[str, Any]: ...


def _envelope(tool_name: str, schema_digest: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "tool_name": tool_name,
        "schema_digest": schema_digest,
        "payload": payload,
    }


def _mcp(name: str, *, port: int) -> FastMCP[None]:
    return FastMCP(
        name,
        host=_HOST,
        port=port,
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
    )


def _search_upstream_policy(provider_profile: str) -> dict[str, Any]:
    if provider_profile == LEGACY_KEYED_V1_PROFILE:
        return {
            "book_discovery": [
                "google-books-api",
                "open-library-api",
                "crossref-rest-api",
                "wikidata-query-expansion",
            ],
            "research_primary": "zhipu-coding-plan-web-search-prime-mcp",
            "final_fallback": "zh-wikipedia-mediawiki-api",
            "fallback_on": [
                "structured-catalogues-empty-or-unavailable",
                "http-429",
                "http-5xx",
                "network-unavailable",
            ],
        }
    if provider_profile == PUBLIC_KEYLESS_V1_PROFILE:
        return {
            "book_discovery": [
                "open-library-api",
                "crossref-rest-api",
                "wikidata-query-expansion",
            ],
            "generic_search": "zh-wikipedia-mediawiki-api",
            "search_scope": "zh-wikipedia-only",
        }
    raise ValueError(f"unsupported provider profile: {provider_profile!r}")


def build_search_mcp(
    provider: SearchProvider,
    *,
    provider_profile: str,
) -> FastMCP[None]:
    upstream_policy = _search_upstream_policy(provider_profile)
    mcp = _mcp("Shidu Search MCP", port=SEARCH_PORT)

    def invoke(arguments: Mapping[str, Any]) -> dict[str, Any]:
        if set(arguments) != {"query", "max_results"}:
            raise ProviderRequestError("search arguments are invalid")
        try:
            return provider.search(
                arguments["query"], max_results=arguments["max_results"]
            )
        except ProviderGatewayError:
            raise
        except Exception:
            raise ProviderUpstreamError("search provider is unavailable") from None

    @mcp.tool(name=SEARCH_TOOL_NAME)
    def coding_plan_search(
        query: SearchQuery, max_results: SearchLimit = 10
    ) -> dict[str, Any]:
        return invoke({"query": query, "max_results": max_results})

    @mcp.custom_route("/health", methods=["GET"])
    async def health(_: Request) -> Response:
        return JSONResponse({"ok": True, "service": SEARCH_SERVICE_VERSION})

    @mcp.custom_route("/discover", methods=["GET"])
    async def discover(_: Request) -> Response:
        return JSONResponse(
            {
                "service_version": SEARCH_SERVICE_VERSION,
                "tool_name": SEARCH_TOOL_NAME,
                "schema_digest": SEARCH_SCHEMA_DIGEST,
                "upstream_policy": upstream_policy,
            }
        )

    @mcp.custom_route("/invoke", methods=["POST"])
    async def http_invoke(request: Request) -> Response:
        try:
            raw = await request.json()
            if not isinstance(raw, dict) or raw.get("tool_name") != SEARCH_TOOL_NAME:
                raise ProviderRequestError("search tool is invalid")
            arguments = raw.get("arguments")
            if not isinstance(arguments, dict):
                raise ProviderRequestError("search arguments are invalid")
            return JSONResponse(
                _envelope(SEARCH_TOOL_NAME, SEARCH_SCHEMA_DIGEST, invoke(arguments))
            )
        except (json.JSONDecodeError, UnicodeDecodeError):
            return JSONResponse({"error": "search_call_failed"}, status_code=400)
        except ProviderRequestError:
            return JSONResponse({"error": "search_call_failed"}, status_code=422)
        except Exception:
            return JSONResponse({"error": "search_call_failed"}, status_code=502)

    return mcp


def build_reader_mcp(provider: ReaderProvider) -> FastMCP[None]:
    mcp = _mcp("Shidu Reader MCP", port=READER_PORT)
    required = {
        "url",
        "approved_resolved_addresses",
        "redirect_policy",
        "prefetch_policy",
    }

    def invoke(arguments: Mapping[str, Any]) -> dict[str, Any]:
        if set(arguments) != required:
            raise ProviderRequestError("reader arguments are invalid")
        try:
            return provider.read(**arguments)
        except ProviderGatewayError:
            raise
        except Exception:
            raise ProviderUpstreamError("reader provider is unavailable") from None

    @mcp.tool(name=READER_TOOL_NAME)
    def coding_plan_read_page(
        url: ReaderURL,
        approved_resolved_addresses: ApprovedAddresses,
        redirect_policy: str,
        prefetch_policy: str,
    ) -> dict[str, Any]:
        return invoke(
            {
                "url": url,
                "approved_resolved_addresses": approved_resolved_addresses,
                "redirect_policy": redirect_policy,
                "prefetch_policy": prefetch_policy,
            }
        )

    @mcp.custom_route("/health", methods=["GET"])
    async def health(_: Request) -> Response:
        return JSONResponse({"ok": True, "service": READER_SERVICE_VERSION})

    @mcp.custom_route("/discover", methods=["GET"])
    async def discover(_: Request) -> Response:
        return JSONResponse(
            {
                "service_version": READER_SERVICE_VERSION,
                "tool_name": READER_TOOL_NAME,
                "schema_digest": READER_SCHEMA_DIGEST,
                "security_capabilities": {
                    "address_binding": "caller-pinned-ip-v1",
                    "redirect_handling": "forbidden",
                    "prefetch_validation": "required",
                },
            }
        )

    @mcp.custom_route("/invoke", methods=["POST"])
    async def http_invoke(request: Request) -> Response:
        try:
            raw = await request.json()
            if not isinstance(raw, dict) or raw.get("tool_name") != READER_TOOL_NAME:
                raise ProviderRequestError("reader tool is invalid")
            arguments = raw.get("arguments")
            if not isinstance(arguments, dict):
                raise ProviderRequestError("reader arguments are invalid")
            return JSONResponse(
                _envelope(READER_TOOL_NAME, READER_SCHEMA_DIGEST, invoke(arguments))
            )
        except (json.JSONDecodeError, UnicodeDecodeError):
            return JSONResponse({"error": "reader_call_failed"}, status_code=400)
        except ProviderRequestError:
            return JSONResponse({"error": "reader_call_failed"}, status_code=422)
        except Exception:
            return JSONResponse({"error": "reader_call_failed"}, status_code=502)

    return mcp


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="运行书单试读 Search/Reader MCP")
    parser.add_argument(
        "role",
        nargs="?",
        choices=("search", "reader"),
        default=os.getenv("SHIDU_PROVIDER_MCP_ROLE"),
    )
    parser.add_argument(
        "--profile",
        "--provider-profile",
        dest="provider_profile",
        choices=_PROVIDER_PROFILES,
        default=os.getenv("SHIDU_PROVIDER_MCP_PROFILE", "").strip() or None,
        help="显式选择 provider profile（也可设置 SHIDU_PROVIDER_MCP_PROFILE）",
    )
    arguments = parser.parse_args(argv)
    if arguments.provider_profile is None:
        raise SystemExit("必须显式指定 provider profile")
    if arguments.provider_profile not in _PROVIDER_PROFILES:
        raise SystemExit("provider profile 不受支持")
    if arguments.role == "search":
        if arguments.provider_profile == PUBLIC_KEYLESS_V1_PROFILE:
            build_search_mcp(
                BookAwareSearch(
                    catalogues=CompositeBookSearch(
                        sources=(OpenLibraryClient(), CrossrefClient()),
                    ),
                    generic_search=MediaWikiSearch(),
                ),
                provider_profile=arguments.provider_profile,
            ).run("streamable-http")
            return
        zhipu_key_file = os.getenv(
            "SHIDU_ZHIPU_CODING_PLAN_API_KEY_FILE", ""
        ).strip()
        google_key_file = os.getenv(
            "SHIDU_GOOGLE_BOOKS_API_KEY_FILE", ""
        ).strip()
        if not zhipu_key_file:
            raise SystemExit("SHIDU_ZHIPU_CODING_PLAN_API_KEY_FILE 未配置")
        if not google_key_file:
            raise SystemExit("SHIDU_GOOGLE_BOOKS_API_KEY_FILE 未配置")
        google_api_key = _read_secret(Path(google_key_file))
        generic_search = CodingPlanWebSearchMCP(
            key_file=zhipu_key_file,
            fallback=MediaWikiSearch(),
        )
        build_search_mcp(
            BookAwareSearch(
                catalogues=CompositeBookSearch(
                    google_api_key=google_api_key,
                ),
                generic_search=generic_search,
            ),
            provider_profile=arguments.provider_profile,
        ).run("streamable-http")
        return
    if arguments.role == "reader":
        if arguments.provider_profile == PUBLIC_KEYLESS_V1_PROFILE:
            build_reader_mcp(PinnedPageReader()).run("streamable-http")
            return
        google_key_file = os.getenv(
            "SHIDU_GOOGLE_BOOKS_API_KEY_FILE", ""
        ).strip()
        if not google_key_file:
            raise SystemExit("SHIDU_GOOGLE_BOOKS_API_KEY_FILE 未配置")
        build_reader_mcp(
            PinnedPageReader(
                google_books_api_key=_read_secret(Path(google_key_file))
            )
        ).run("streamable-http")
        return
    raise SystemExit("必须指定 search 或 reader")


if __name__ == "__main__":
    main()
