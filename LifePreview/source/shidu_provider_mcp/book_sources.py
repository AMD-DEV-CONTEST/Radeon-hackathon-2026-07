"""Bounded, best-effort aggregation of public bibliographic catalogues.

The search gateway deliberately exposes only its small ``hits`` contract.  The
types in this module keep the richer catalogue identity internally so records
can be de-duplicated before they are projected onto that contract.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import quote, urlencode, urlsplit, urlunsplit

import httpx


BOOK_QUERY_SUFFIX = " 书籍 作者 版本 译者"
BOOK_SOURCE_USER_AGENT = (
    "ShiduBookSearchMCP/1.0 "
    "(bibliographic discovery; contact: local-operator@example.invalid)"
)
DEFAULT_TIMEOUT_SECONDS = 6.0
DEFAULT_MAX_RESPONSE_BYTES = 1_000_000
MAX_QUERY_VARIANTS = 16
MAX_SOURCE_QUERY_VARIANTS = 6

_GOOGLE_BOOKS_URL = "https://www.googleapis.com/books/v1/volumes"
_OPEN_LIBRARY_URL = "https://openlibrary.org/search.json"
_CROSSREF_URL = "https://api.crossref.org/works"
_WIKIDATA_URL = "https://www.wikidata.org/w/api.php"
_CROSSREF_BOOK_TYPES = frozenset(
    {
        "book",
        "book-chapter",
        "book-part",
        "book-section",
        "book-series",
        "book-set",
        "edited-book",
        "monograph",
        "reference-book",
    }
)
_SENSITIVE_QUERY_KEYS = frozenset(
    {"key", "api_key", "apikey", "access_token", "token", "authorization"}
)


class BookSourceError(RuntimeError):
    """A deliberately detail-free error raised by one catalogue client."""


class BookSearchRequestError(ValueError):
    """The gateway supplied a query outside the frozen search contract."""


@dataclass(frozen=True, slots=True)
class BookRecord:
    title: str
    url: str
    authors: tuple[str, ...] = ()
    publisher: str = ""
    year: str = ""
    isbn: str = ""
    source: str = ""


@dataclass(frozen=True, slots=True)
class BookQueryExpansion:
    aliases: tuple[str, ...] = ()
    authors: tuple[str, ...] = ()


class BookCatalogue(Protocol):
    def search(self, query: str, *, max_results: int) -> Sequence[BookRecord]: ...

    def close(self) -> None: ...


class BookEntityExpander(Protocol):
    def expand(self, title: str) -> BookQueryExpansion: ...

    def close(self) -> None: ...


def extract_book_title(query: str) -> str | None:
    """Return the title only for the fixed book-discovery query shape."""

    if not isinstance(query, str):
        return None
    query = query.strip()
    suffix = BOOK_QUERY_SUFFIX.strip()
    if not query.endswith(" " + suffix):
        return None
    title = query[: -len(suffix)].strip()
    if not title or len(title) > 300:
        return None
    return title


# OpenCC is intentionally optional in the provider image.  This conservative
# fallback covers the high-frequency bibliographic characters and all locally
# controlled aliases; OpenCC, when present, supplies the complete conversion.
_TRADITIONAL_TO_SIMPLIFIED = str.maketrans(
    {
        "臺": "台",
        "灣": "湾",
        "喬": "乔",
        "與": "与",
        "著": "着",
        "傳": "传",
        "書": "书",
        "圖": "图",
        "譯": "译",
        "華": "华",
        "國": "国",
        "歷": "历",
        "萬": "万",
        "蘇": "苏",
        "東": "东",
        "買": "买",
        "賣": "卖",
        "開": "开",
        "關": "关",
        "間": "间",
        "學": "学",
        "術": "术",
        "體": "体",
        "龍": "龙",
        "馬": "马",
        "門": "门",
        "風": "风",
        "雲": "云",
        "時": "时",
        "間": "间",
        "裡": "里",
        "這": "这",
        "個": "个",
        "們": "们",
        "為": "为",
        "後": "后",
        "發": "发",
        "現": "现",
        "實": "实",
        "點": "点",
        "愛": "爱",
        "心": "心",
        "導": "导",
        "語": "语",
        "說": "说",
        "讀": "读",
        "寫": "写",
        "聲": "声",
        "樂": "乐",
        "電": "电",
        "腦": "脑",
        "網": "网",
        "資": "资",
        "訊": "讯",
        "飛": "飞",
        "機": "机",
        "醫": "医",
        "藥": "药",
        "錢": "钱",
        "貴": "贵",
        "長": "长",
        "年": "年",
        "紀": "纪",
        "記": "记",
        "錄": "录",
        "靜": "静",
        "歡": "欢",
        "離": "离",
        "張": "张",
        "劉": "刘",
        "陳": "陈",
        "楊": "杨",
        "黃": "黄",
        "賈": "贾",
        "貝": "贝",
        "爾": "尔",
        "圍": "围",
        "獨": "独",
        "夢": "梦",
        "鄉": "乡",
        "誰": "谁",
        "殺": "杀",
        "紅": "红",
        "樓": "楼",
        "尋": "寻",
        "專": "专",
        "業": "业",
        "簡": "简",
        "藝": "艺",
        "組": "组",
        "織": "织",
        "啟": "启",
        "繫": "系",
    }
)
_SIMPLIFIED_TO_TRADITIONAL = str.maketrans(
    {
        # Ambiguous characters are omitted rather than converted incorrectly.
        simplified: traditional
        for traditional, simplified in {
            "臺": "台",
            "灣": "湾",
            "喬": "乔",
            "與": "与",
            "著": "着",
            "傳": "传",
            "書": "书",
            "圖": "图",
            "譯": "译",
            "華": "华",
            "國": "国",
            "歷": "历",
            "萬": "万",
            "蘇": "苏",
            "東": "东",
            "學": "学",
            "術": "术",
            "體": "体",
            "龍": "龙",
            "馬": "马",
            "門": "门",
            "風": "风",
            "雲": "云",
            "時": "时",
            "間": "间",
            "這": "这",
            "個": "个",
            "們": "们",
            "為": "为",
            "發": "发",
            "現": "现",
            "實": "实",
            "點": "点",
            "愛": "爱",
            "導": "导",
            "語": "语",
            "說": "说",
            "讀": "读",
            "寫": "写",
            "聲": "声",
            "電": "电",
            "腦": "脑",
            "網": "网",
            "資": "资",
            "訊": "讯",
            "飛": "飞",
            "機": "机",
            "醫": "医",
            "藥": "药",
            "錢": "钱",
            "貴": "贵",
            "長": "长",
            "紀": "纪",
            "記": "记",
            "錄": "录",
            "靜": "静",
            "歡": "欢",
            "離": "离",
            "張": "张",
            "劉": "刘",
            "陳": "陈",
            "楊": "杨",
            "黃": "黄",
            "賈": "贾",
            "貝": "贝",
            "爾": "尔",
            "圍": "围",
            "獨": "独",
            "夢": "梦",
            "鄉": "乡",
            "誰": "谁",
            "殺": "杀",
            "紅": "红",
            "樓": "楼",
            "尋": "寻",
            "專": "专",
            "業": "业",
            "簡": "简",
            "藝": "艺",
            "組": "组",
            "織": "织",
            "啟": "启",
            "繫": "系",
        }.items()
    }
)

_CONTROLLED_ALIASES: dict[str, tuple[str, ...]] = {
    "乔布斯传": ("史蒂夫·乔布斯传", "Steve Jobs"),
    "史蒂夫乔布斯传": ("乔布斯传", "Steve Jobs"),
    "史蒂夫贾伯斯传": ("贾伯斯传", "Steve Jobs"),
    "贾伯斯传": ("史蒂夫·贾伯斯传", "Steve Jobs"),
}


def _normalise_text(value: str) -> str:
    return "".join(character.casefold() for character in value if character.isalnum())


def _dedupe_text(values: Iterable[object], *, limit: int = MAX_QUERY_VARIANTS) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in values:
        if not isinstance(raw, str):
            continue
        value = " ".join(raw.split()).strip()
        key = _normalise_text(value)
        if not key or len(value) > 300 or key in seen:
            continue
        seen.add(key)
        result.append(value)
        if len(result) >= limit:
            break
    return tuple(result)


def _convert_chinese(value: str, configuration: str) -> str:
    try:
        from opencc import OpenCC  # type: ignore[import-not-found]

        return str(OpenCC(configuration).convert(value))
    except (ImportError, OSError, RuntimeError, ValueError):
        table = (
            _TRADITIONAL_TO_SIMPLIFIED
            if configuration == "t2s"
            else _SIMPLIFIED_TO_TRADITIONAL
        )
        return value.translate(table)


def simplified_title(title: str) -> str:
    return _convert_chinese(title, "t2s")


def traditional_title(title: str) -> str:
    return _convert_chinese(title, "s2t")


def controlled_title_aliases(title: str) -> tuple[str, ...]:
    key = _normalise_text(simplified_title(title))
    return _CONTROLLED_ALIASES.get(key, ())


def build_book_queries(
    title: str,
    *,
    aliases: Sequence[str] = (),
    authors: Sequence[str] = (),
    max_queries: int = MAX_QUERY_VARIANTS,
) -> tuple[str, ...]:
    """Build deterministic title and title/author query variants."""

    if not isinstance(title, str) or not title.strip():
        return ()
    if isinstance(max_queries, bool) or not isinstance(max_queries, int) or max_queries < 1:
        return ()
    base = _dedupe_text(
        (
            title,
            simplified_title(title),
            traditional_title(title),
            *controlled_title_aliases(title),
            *aliases,
        ),
        limit=max_queries,
    )
    author_values = _dedupe_text(authors, limit=max_queries)
    combined = list(base)
    for candidate in base:
        for author in author_values:
            combined.append(f"{candidate} {author}")
    queries = list(_dedupe_text(combined, limit=max_queries))
    if author_values and base:
        required_author_query = f"{base[0]} {author_values[0]}"
        required_key = _normalise_text(required_author_query)
        if all(_normalise_text(query) != required_key for query in queries):
            if len(queries) >= max_queries:
                queries[-1] = required_author_query
            else:
                queries.append(required_author_query)
    return tuple(queries)


def _new_client(timeout_seconds: float) -> httpx.Client:
    return httpx.Client(
        timeout=timeout_seconds,
        follow_redirects=False,
        trust_env=False,
        headers={"User-Agent": BOOK_SOURCE_USER_AGENT, "Accept": "application/json"},
    )


def _bounded_json_get(
    client: httpx.Client,
    url: str,
    *,
    params: Mapping[str, str],
    timeout_seconds: float,
    max_response_bytes: int,
    provider_name: str,
    request_headers: Mapping[str, str] | None = None,
) -> object:
    try:
        with client.stream(
            "GET",
            url,
            params=params,
            headers={
                "User-Agent": BOOK_SOURCE_USER_AGENT,
                "Accept": "application/json",
                **dict(request_headers or {}),
            },
            timeout=timeout_seconds,
            follow_redirects=False,
        ) as response:
            response.raise_for_status()
            length = response.headers.get("content-length")
            if length is not None:
                try:
                    declared_length = int(length)
                except ValueError:
                    raise BookSourceError(f"{provider_name} response is invalid") from None
                if declared_length < 0 or declared_length > max_response_bytes:
                    raise BookSourceError(f"{provider_name} response is too large")
            body = bytearray()
            for chunk in response.iter_bytes(chunk_size=65_536):
                if len(body) + len(chunk) > max_response_bytes:
                    raise BookSourceError(f"{provider_name} response is too large")
                body.extend(chunk)
    except BookSourceError:
        raise
    except Exception:
        # Never chain a transport exception: custom transports as well as
        # HTTPX can include the full request URL (and therefore a key).
        raise BookSourceError(f"{provider_name} is unavailable") from None
    try:
        return json.loads(bytes(body))
    except (UnicodeError, ValueError):
        raise BookSourceError(f"{provider_name} response is invalid") from None


def _safe_public_url(value: object, *, secret: str = "") -> str | None:
    if not isinstance(value, str) or not value or len(value) > 2_048:
        return None
    if secret and secret in value:
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
    filtered_query: list[tuple[str, str]] = []
    from urllib.parse import parse_qsl

    for key, item in parse_qsl(parts.query, keep_blank_values=True):
        if key.casefold() not in _SENSITIVE_QUERY_KEYS:
            filtered_query.append((key, item))
    result = urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(filtered_query), parts.fragment)
    )
    if secret and secret in result:
        return None
    return result


def _first_string(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        for item in value:
            if isinstance(item, str) and item.strip():
                return item.strip()
    return ""


def _strings(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return _dedupe_text(value, limit=20)


def _published_year(value: object) -> str:
    if isinstance(value, (int, str)):
        match = re.search(r"(?:1[0-9]{3}|20[0-9]{2}|2100)", str(value))
        return match.group(0) if match else ""
    return ""


def _canonical_isbn(values: Iterable[object]) -> str:
    candidates: list[str] = []
    for raw in values:
        if not isinstance(raw, str):
            continue
        isbn = "".join(character for character in raw.upper() if character.isdigit() or character == "X")
        if len(isbn) == 10:
            if (
                not isbn[:9].isdigit()
                or (not isbn[-1].isdigit() and isbn[-1] != "X")
                or sum(
                    (10 - index) * (10 if digit == "X" else int(digit))
                    for index, digit in enumerate(isbn)
                )
                % 11
                != 0
            ):
                continue
            stem = "978" + isbn[:9]
            total = sum((1 if index % 2 == 0 else 3) * int(digit) for index, digit in enumerate(stem))
            isbn = stem + str((10 - total % 10) % 10)
        if (
            len(isbn) == 13
            and isbn.isdigit()
            and sum(
                (1 if index % 2 == 0 else 3) * int(digit)
                for index, digit in enumerate(isbn[:12])
            )
            % 10
            == (10 - int(isbn[-1])) % 10
        ):
            candidates.append(isbn)
    return candidates[0] if candidates else ""


class _HTTPBookClient:
    _provider_name = "book source"

    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
    ) -> None:
        self._timeout_seconds = timeout_seconds
        self._max_response_bytes = max_response_bytes
        self._client = client or _new_client(timeout_seconds)
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> _HTTPBookClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def __repr__(self) -> str:
        return f"<{type(self).__name__}>"

    def _get(
        self,
        url: str,
        params: Mapping[str, str],
        *,
        request_headers: Mapping[str, str] | None = None,
    ) -> object:
        return _bounded_json_get(
            self._client,
            url,
            params=params,
            timeout_seconds=self._timeout_seconds,
            max_response_bytes=self._max_response_bytes,
            provider_name=self._provider_name,
            request_headers=request_headers,
        )


class GoogleBooksClient(_HTTPBookClient):
    _provider_name = "google books"

    def __init__(self, *, api_key: str | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._api_key = api_key.strip() if isinstance(api_key, str) else ""

    def search(self, query: str, *, max_results: int) -> Sequence[BookRecord]:
        params = {
            "q": query,
            "maxResults": str(min(max_results, 40)),
            "printType": "books",
        }
        headers = {"X-Goog-Api-Key": self._api_key} if self._api_key else None
        raw = self._get(
            _GOOGLE_BOOKS_URL,
            params,
            request_headers=headers,
        )
        if not isinstance(raw, Mapping) or not isinstance(raw.get("items", []), list):
            raise BookSourceError("google books response is invalid")
        records: list[BookRecord] = []
        for item in raw.get("items", []):
            if not isinstance(item, Mapping) or not isinstance(item.get("volumeInfo"), Mapping):
                continue
            info = item["volumeInfo"]
            title = _first_string(info.get("title"))
            item_id = _first_string(item.get("id"))
            if not title or not item_id:
                continue
            url = _safe_public_url(
                "https://www.googleapis.com/books/v1/volumes/"
                + quote(item_id, safe=""),
                secret=self._api_key,
            )
            if url is None:
                continue
            identifiers = info.get("industryIdentifiers", [])
            isbn_values = (
                entry.get("identifier")
                for entry in identifiers
                if isinstance(entry, Mapping)
            ) if isinstance(identifiers, list) else ()
            records.append(
                BookRecord(
                    title=title[:500],
                    url=url,
                    authors=_strings(info.get("authors")),
                    publisher=_first_string(info.get("publisher"))[:300],
                    year=_published_year(info.get("publishedDate")),
                    isbn=_canonical_isbn(isbn_values),
                    source="Google Books",
                )
            )
        return records[:max_results]


class OpenLibraryClient(_HTTPBookClient):
    _provider_name = "open library"

    def search(self, query: str, *, max_results: int) -> Sequence[BookRecord]:
        raw = self._get(
            _OPEN_LIBRARY_URL,
            {
                "q": query,
                "limit": str(min(max_results, 100)),
                "fields": (
                    "key,title,author_name,publisher,first_publish_year,isbn,language"
                ),
            },
        )
        if not isinstance(raw, Mapping) or not isinstance(raw.get("docs", []), list):
            raise BookSourceError("open library response is invalid")
        records: list[BookRecord] = []
        for item in raw.get("docs", []):
            if not isinstance(item, Mapping):
                continue
            title = _first_string(item.get("title"))
            key = _first_string(item.get("key"))
            if not title or not key or not key.startswith("/works/"):
                continue
            isbn = _canonical_isbn(
                item.get("isbn", [])
                if isinstance(item.get("isbn", []), list)
                else ()
            )
            identity_params = {"isbn": isbn} if isbn else {"q": f"key:{key}"}
            url = _safe_public_url(
                _OPEN_LIBRARY_URL
                + "?"
                + urlencode(
                    {
                        **identity_params,
                        "fields": (
                            "key,title,author_name,publisher,first_publish_year,"
                            "isbn,language"
                        ),
                        "limit": "1",
                    }
                )
            )
            if url is None:
                continue
            records.append(
                BookRecord(
                    title=title[:500],
                    url=url,
                    authors=_strings(item.get("author_name")),
                    publisher=_first_string(item.get("publisher"))[:300],
                    year=_published_year(item.get("first_publish_year")),
                    isbn=isbn,
                    source="Open Library",
                )
            )
        return records[:max_results]


def _crossref_year(item: Mapping[str, object]) -> str:
    for field in ("published-print", "published-online", "issued", "created"):
        value = item.get(field)
        if not isinstance(value, Mapping):
            continue
        parts = value.get("date-parts")
        if (
            isinstance(parts, list)
            and parts
            and isinstance(parts[0], list)
            and parts[0]
        ):
            year = _published_year(parts[0][0])
            if year:
                return year
    return ""


class CrossrefClient(_HTTPBookClient):
    _provider_name = "crossref"

    def search(self, query: str, *, max_results: int) -> Sequence[BookRecord]:
        raw = self._get(
            _CROSSREF_URL,
            {"query.bibliographic": query, "rows": str(min(max_results, 100))},
        )
        message = raw.get("message") if isinstance(raw, Mapping) else None
        if not isinstance(message, Mapping) or not isinstance(message.get("items", []), list):
            raise BookSourceError("crossref response is invalid")
        records: list[BookRecord] = []
        for item in message.get("items", []):
            if not isinstance(item, Mapping):
                continue
            item_type = _first_string(item.get("type")).casefold()
            if item_type and item_type not in _CROSSREF_BOOK_TYPES:
                continue
            title = _first_string(item.get("title"))
            doi = _first_string(item.get("DOI"))
            if not title or not doi:
                continue
            url = _safe_public_url(
                "https://api.crossref.org/works/" + quote(doi, safe="")
            )
            if url is None:
                continue
            authors: list[str] = []
            raw_authors = item.get("author", [])
            if isinstance(raw_authors, list):
                for author in raw_authors:
                    if not isinstance(author, Mapping):
                        continue
                    name = " ".join(
                        part
                        for part in (
                            _first_string(author.get("given")),
                            _first_string(author.get("family")),
                        )
                        if part
                    )
                    if name:
                        authors.append(name)
            records.append(
                BookRecord(
                    title=title[:500],
                    url=url,
                    authors=_dedupe_text(authors, limit=20),
                    publisher=_first_string(item.get("publisher"))[:300],
                    year=_crossref_year(item),
                    isbn=_canonical_isbn(item.get("ISBN", []) if isinstance(item.get("ISBN", []), list) else ()),
                    source="Crossref",
                )
            )
        return records[:max_results]


def _wikidata_values(entity: Mapping[str, object], field: str) -> tuple[str, ...]:
    container = entity.get(field)
    if not isinstance(container, Mapping):
        return ()
    values: list[str] = []
    for language in ("zh", "zh-cn", "zh-hans", "zh-tw", "zh-hant", "en"):
        entry = container.get(language)
        entries = entry if isinstance(entry, list) else [entry]
        for candidate in entries:
            if isinstance(candidate, Mapping) and isinstance(candidate.get("value"), str):
                values.append(candidate["value"])
    return _dedupe_text(values, limit=40)


class WikidataBookExpander(_HTTPBookClient):
    _provider_name = "wikidata"

    def expand(self, title: str) -> BookQueryExpansion:
        searched = self._get(
            _WIKIDATA_URL,
            {
                "action": "wbsearchentities",
                "search": title,
                "language": "zh",
                "uselang": "zh",
                "type": "item",
                "limit": "3",
                "format": "json",
            },
        )
        if not isinstance(searched, Mapping) or not isinstance(searched.get("search", []), list):
            raise BookSourceError("wikidata response is invalid")
        search_items = [item for item in searched.get("search", []) if isinstance(item, Mapping)]
        entity_ids = _dedupe_text(
            (item.get("id") for item in search_items),
            limit=3,
        )
        aliases: list[object] = []
        for item in search_items:
            aliases.extend((item.get("label"), item.get("match", {}).get("text") if isinstance(item.get("match"), Mapping) else None))
            raw_aliases = item.get("aliases")
            if isinstance(raw_aliases, list):
                aliases.extend(raw_aliases)
        if not entity_ids:
            return BookQueryExpansion(aliases=_dedupe_text(aliases, limit=12))

        details = self._get(
            _WIKIDATA_URL,
            {
                "action": "wbgetentities",
                "ids": "|".join(entity_ids),
                "props": "labels|aliases|claims",
                "languages": "zh|zh-cn|zh-hans|zh-tw|zh-hant|en",
                "format": "json",
            },
        )
        entities = details.get("entities") if isinstance(details, Mapping) else None
        if not isinstance(entities, Mapping):
            raise BookSourceError("wikidata response is invalid")
        author_ids: list[object] = []
        for entity in entities.values():
            if not isinstance(entity, Mapping):
                continue
            aliases.extend(_wikidata_values(entity, "labels"))
            aliases.extend(_wikidata_values(entity, "aliases"))
            claims = entity.get("claims")
            p50 = claims.get("P50", []) if isinstance(claims, Mapping) else []
            if isinstance(p50, list):
                for claim in p50:
                    if not isinstance(claim, Mapping):
                        continue
                    mainsnak = claim.get("mainsnak")
                    datavalue = mainsnak.get("datavalue") if isinstance(mainsnak, Mapping) else None
                    value = datavalue.get("value") if isinstance(datavalue, Mapping) else None
                    if isinstance(value, Mapping):
                        author_ids.append(value.get("id"))
        clean_author_ids = _dedupe_text(author_ids, limit=10)
        authors: list[object] = []
        if clean_author_ids:
            author_details = self._get(
                _WIKIDATA_URL,
                {
                    "action": "wbgetentities",
                    "ids": "|".join(clean_author_ids),
                    "props": "labels|aliases",
                    "languages": "zh|zh-cn|zh-hans|zh-tw|zh-hant|en",
                    "format": "json",
                },
            )
            author_entities = author_details.get("entities") if isinstance(author_details, Mapping) else None
            if not isinstance(author_entities, Mapping):
                raise BookSourceError("wikidata response is invalid")
            for entity in author_entities.values():
                if isinstance(entity, Mapping):
                    authors.extend(_wikidata_values(entity, "labels"))
                    authors.extend(_wikidata_values(entity, "aliases"))
        return BookQueryExpansion(
            aliases=_dedupe_text(aliases, limit=12),
            authors=_dedupe_text(authors, limit=8),
        )


def _record_key(record: BookRecord) -> tuple[str, ...]:
    isbn = _canonical_isbn((record.isbn,))
    if isbn:
        return ("isbn", isbn)
    return (
        "metadata",
        _normalise_text(record.title),
        "|".join(sorted(_normalise_text(author) for author in record.authors)),
        _normalise_text(record.publisher),
        record.year,
    )


def _normalised_title(value: str) -> str:
    return _normalise_text(simplified_title(value))


def _title_relevance(
    record_title: str,
    candidate_titles: Sequence[str],
) -> tuple[int, float, int]:
    """Rank exact, containing, overlapping, then unrelated titles.

    The candidate order is meaningful: the user's original title precedes
    script variants, controlled aliases, and finally Wikidata aliases. Python's
    stable sort preserves catalogue/response order when every score component
    ties.
    """

    record = _normalised_title(record_title)
    targets = tuple(_normalised_title(title) for title in candidate_titles)
    for index, target in enumerate(targets):
        if record and record == target:
            return (0, 0.0, index)

    best_containment: tuple[float, int] | None = None
    for index, target in enumerate(targets):
        if not record or not target or (record not in target and target not in record):
            continue
        coverage = min(len(record), len(target)) / max(len(record), len(target))
        score = (-coverage, index)
        if best_containment is None or score < best_containment:
            best_containment = score
    if best_containment is not None:
        return (1, best_containment[0], best_containment[1])

    record_units = set(record)
    best_overlap: tuple[float, int] | None = None
    for index, target in enumerate(targets):
        target_units = set(target)
        union = record_units | target_units
        if not union:
            continue
        similarity = len(record_units & target_units) / len(union)
        if similarity <= 0:
            continue
        score = (-similarity, index)
        if best_overlap is None or score < best_overlap:
            best_overlap = score
    if best_overlap is not None:
        return (2, best_overlap[0], best_overlap[1])
    return (3, 0.0, len(targets))


def _record_snippet(record: BookRecord) -> str:
    fields = [f"书名：{record.title}"]
    if record.authors:
        fields.append("作者：" + "、".join(record.authors))
    if record.publisher:
        fields.append("出版社：" + record.publisher)
    if record.year:
        fields.append("出版年：" + record.year)
    if record.isbn:
        fields.append("ISBN：" + record.isbn)
    if record.source:
        fields.append("来源：" + record.source)
    return "\n".join(fields)[:5_000]


class CompositeBookSearch:
    """Search several catalogues and isolate every upstream failure."""

    def __init__(
        self,
        *,
        google_api_key: str | None = None,
        google: BookCatalogue | None = None,
        open_library: BookCatalogue | None = None,
        crossref: BookCatalogue | None = None,
        wikidata: BookEntityExpander | None = None,
        sources: Sequence[BookCatalogue] | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
    ) -> None:
        if sources is None:
            source_kwargs = {
                "timeout_seconds": timeout_seconds,
                "max_response_bytes": max_response_bytes,
            }
            google = google or GoogleBooksClient(api_key=google_api_key, **source_kwargs)
            open_library = open_library or OpenLibraryClient(**source_kwargs)
            crossref = crossref or CrossrefClient(**source_kwargs)
            sources = (google, open_library, crossref)
        self._sources = tuple(sources)
        self._wikidata = wikidata or WikidataBookExpander(
            timeout_seconds=timeout_seconds,
            max_response_bytes=max_response_bytes,
        )

    def __repr__(self) -> str:
        return f"<CompositeBookSearch sources={len(self._sources)}>"

    def close(self) -> None:
        closed: set[int] = set()
        for provider in (*self._sources, self._wikidata):
            if id(provider) in closed:
                continue
            closed.add(id(provider))
            try:
                provider.close()
            except Exception:
                pass

    def __enter__(self) -> CompositeBookSearch:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def search(self, query: str, *, max_results: int) -> dict[str, Any]:
        if (
            not isinstance(query, str)
            or not query.strip()
            or len(query.strip()) > 400
        ):
            raise BookSearchRequestError("book search query is invalid")
        if (
            isinstance(max_results, bool)
            or not isinstance(max_results, int)
            or not 1 <= max_results <= 20
        ):
            raise BookSearchRequestError("book search result limit is invalid")
        title = extract_book_title(query)
        if title is None:
            raise BookSearchRequestError("book search query suffix is invalid")

        expansion = BookQueryExpansion()
        try:
            expansion = self._wikidata.expand(title)
        except Exception:
            pass
        queries = build_book_queries(
            title,
            aliases=expansion.aliases,
            authors=expansion.authors,
        )
        candidate_titles = build_book_queries(
            title,
            aliases=expansion.aliases,
            max_queries=MAX_QUERY_VARIANTS,
        )

        source_queries = queries[:MAX_SOURCE_QUERY_VARIANTS]
        source_results: list[Sequence[BookRecord] | None] = [
            None for _ in self._sources
        ]
        if self._sources:
            with ThreadPoolExecutor(
                max_workers=min(3, len(self._sources)),
                thread_name_prefix="shidu-book-source",
            ) as executor:
                futures: list[Future[Sequence[BookRecord]]] = [
                    executor.submit(
                        self._search_source,
                        source,
                        source_queries,
                        max_results,
                    )
                    for source in self._sources
                ]
                # Futures are consumed in source order, not completion order,
                # making hit ordering deterministic while requests run in
                # parallel.
                for index, future in enumerate(futures):
                    try:
                        source_results[index] = future.result()
                    except Exception:
                        source_results[index] = None

        candidates: list[tuple[BookRecord, str]] = []
        for source_records in source_results:
            if source_records is None:
                continue
            for record in source_records:
                if not isinstance(record, BookRecord) or not record.title.strip():
                    continue
                url = _safe_public_url(record.url)
                if url is not None:
                    candidates.append((record, url))

        candidates.sort(
            key=lambda candidate: _title_relevance(
                candidate[0].title,
                candidate_titles,
            )
        )

        hits: list[dict[str, str]] = []
        seen: set[tuple[str, ...]] = set()
        for record, url in candidates:
            key = _record_key(record)
            if key in seen:
                continue
            seen.add(key)
            hits.append(
                {
                    "title": record.title.strip()[:500],
                    "url": url,
                    "snippet": _record_snippet(record),
                }
            )
            if len(hits) >= max_results:
                return {"hits": hits}
        return {"hits": hits}

    @staticmethod
    def _search_source(
        source: BookCatalogue,
        queries: Sequence[str],
        max_results: int,
    ) -> Sequence[BookRecord]:
        records: list[BookRecord] = []
        for variant in queries:
            try:
                records.extend(source.search(variant, max_results=max_results))
            except Exception:
                # Query expansion is best-effort. A catalogue may reject or
                # transiently fail one alias after returning useful rows for
                # another; keep those earlier rows instead of losing the
                # entire source. Stop this catalogue after its first failure
                # so one unavailable free provider cannot consume the request
                # budget once per alias.
                break
        return records


# Names that make the intent clear to callers using either "source" or
# "client" terminology.
GoogleBooksSource = GoogleBooksClient
OpenLibrarySource = OpenLibraryClient
CrossrefSource = CrossrefClient
extract_title_from_book_query = extract_book_title
generate_book_queries = build_book_queries


__all__ = [
    "BOOK_QUERY_SUFFIX",
    "MAX_SOURCE_QUERY_VARIANTS",
    "BookQueryExpansion",
    "BookRecord",
    "BookSearchRequestError",
    "BookSourceError",
    "CompositeBookSearch",
    "CrossrefClient",
    "CrossrefSource",
    "GoogleBooksClient",
    "GoogleBooksSource",
    "OpenLibraryClient",
    "OpenLibrarySource",
    "WikidataBookExpander",
    "build_book_queries",
    "controlled_title_aliases",
    "extract_book_title",
    "extract_title_from_book_query",
    "generate_book_queries",
    "simplified_title",
    "traditional_title",
]
