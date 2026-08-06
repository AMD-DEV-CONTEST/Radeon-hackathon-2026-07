"""Fail-closed Search MCP to Reader MCP book identity discovery."""

from __future__ import annotations

import hashlib
import re
from typing import Protocol
from uuid import UUID

from creative_hub.shidu.book_identity import (
    BookIdentity,
    normalize_book_identity,
    normalize_book_title,
)
from creative_hub.shidu.providers import (
    CODING_PLAN_READER_SCHEMA_DIGEST,
    CODING_PLAN_READER_TOOL_NAME,
    CODING_PLAN_SEARCH_SCHEMA_DIGEST,
    CODING_PLAN_SEARCH_TOOL_NAME,
    PageReaderProvider,
    ReadPageRequest,
    ReaderSecurityCapabilities,
    SearchHit,
    SearchProvider,
    SearchRequest,
    SourceDocumentPayload,
)
from creative_hub.shidu.schemas import (
    BookDiscoveryResolution,
    CreateBookDiscoveryResolution,
    DiscoveredBookIdentity,
    Stored,
)
from creative_hub.shidu.url_security import ReaderURLGuard, UnsafeSourceURL


DISCOVERY_SEARCH_SUFFIX = " 书籍 作者 版本 译者"
MAX_DISCOVERY_RESULTS = 20

# Short commercial/common names are deliberately explicit.  A generic suffix
# rule would make an unrelated Reader title such as ``伪乔布斯传`` look like a
# match for ``乔布斯传``.  Keep this fail-closed list small and reviewable; the
# complete Reader title is still the persisted identity.
_CONTROLLED_SHORT_TITLE_ALIASES = {
    normalize_book_title("乔布斯传"): frozenset(
        {normalize_book_title("史蒂夫·乔布斯传")}
    ),
}


class BookDiscoveryDependencyError(RuntimeError):
    """A retryable and deliberately detail-free external dependency failure."""

    retryable = True
    code = "book_discovery_dependency_unavailable"

    def __init__(self) -> None:
        super().__init__("book discovery dependency is unavailable")


class DiscoveryRepository(Protocol):
    def get_book_discovery_replay(
        self,
        project_id: UUID,
        command_key: str,
        title: str,
    ) -> BookDiscoveryResolution | None: ...

    def create_book_discovery_resolution(
        self, command: CreateBookDiscoveryResolution
    ) -> Stored[BookDiscoveryResolution]: ...


_FIELD_LINE = re.compile(
    r"^\s*(?:[-*]\s+)?(?:\*\*|__)?"
    r"(书名|标题|作者|语言|语种|版本|版次|译者|title|author|language|edition|translator)"
    r"(?:\*\*|__)?\s*[:：]\s*(.*?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_FIELD_NAMES = {
    "书名": "title",
    "标题": "title",
    "title": "title",
    "作者": "author",
    "author": "author",
    "语言": "language",
    "语种": "language",
    "language": "language",
    "版本": "edition",
    "版次": "edition",
    "edition": "edition",
    "译者": "translator",
    "translator": "translator",
}
_MARKDOWN_HEADING = re.compile(r"^\s*#\s+(.+?)\s*$", re.MULTILINE)
_NATURAL_AUTHOR = re.compile(
    r"^\s*([^|：:\r\n]{1,200}?)\s+著\s*$", re.MULTILINE
)
_NATURAL_TRANSLATOR = re.compile(
    r"^\s*([^|：:\r\n]{1,200}?)\s+译\s*$", re.MULTILINE
)
_NATURAL_EDITION = re.compile(
    r"^\s*((?:\d{4}\s*年?版)|(?:第[^\s]{1,20}版))\s*$", re.MULTILINE
)
_BOOK_QUOTED_TITLE = re.compile(r"《([^》]{1,300})》")
_PARENTHETICAL_SUFFIX = re.compile(r"\s*[（(][^）)]{1,100}[）)]\s*$")
_LANGUAGE_ALIASES = {
    "中文": "zh-CN",
    "汉语": "zh-CN",
    "简体中文": "zh-CN",
    "繁体中文": "zh-TW",
    "chi": "zh-CN",
    "zho": "zh-CN",
    "zh": "zh-CN",
    "zh-cn": "zh-CN",
    "zh-hans": "zh-CN",
    "zh-tw": "zh-TW",
    "zh-hant": "zh-TW",
    "英语": "en",
    "英文": "en",
    "eng": "en",
}
_EMPTY_IDENTITY_VALUES = frozenset({"", "-", "—", "无", "无译者", "不详", "none"})
_FIELD_LIMITS = {
    "title": 300,
    "author": 200,
    "language": 32,
    "edition": 200,
    "translator": 200,
}


def _markdown_cells(line: str) -> tuple[str, ...]:
    stripped = line.strip()
    if not stripped.startswith("|") or not stripped.endswith("|"):
        return ()
    return tuple(cell.strip() for cell in stripped[1:-1].split("|"))


def _field_name(value: str) -> str | None:
    return _FIELD_NAMES.get(value.strip().strip("*_`").casefold())


def _title_base(value: str) -> str:
    """Return a matching alias without changing the persisted title."""

    quoted = _BOOK_QUOTED_TITLE.search(value)
    if quoted is not None:
        value = quoted.group(1)
    value = _PARENTHETICAL_SUFFIX.sub("", value.strip())
    return normalize_book_title(
        re.split(r"\s*(?:[:：]|[—–]\s*)", value, maxsplit=1)[0]
    )


def _title_matches_requested(reader_title: str, requested_title: str) -> bool:
    """Match exact/qualified requests first, then unqualified main aliases."""

    if reader_title == requested_title:
        return True
    without_disambiguation = normalize_book_title(
        _PARENTHETICAL_SUFFIX.sub("", reader_title)
    )
    if without_disambiguation == requested_title:
        return True
    requested_base = _title_base(requested_title)
    return (
        requested_title == requested_base
        and (
            requested_title == _title_base(reader_title)
            or reader_title
            in _CONTROLLED_SHORT_TITLE_ALIASES.get(
                requested_title, frozenset()
            )
        )
    )


def _normalise_extracted_field(name: str, value: str) -> str:
    value = value.strip().strip("*_`").strip()
    if name == "title":
        # The Reader's complete title is an identity dimension. Matching
        # aliases are evaluated later and must never overwrite this value.
        return normalize_book_title(value)
    if name == "author":
        return re.sub(r"\s+著$", "", value).strip()
    if name == "language":
        return _LANGUAGE_ALIASES.get(value.casefold(), value)
    if name in {"edition", "translator"} and value.casefold() in _EMPTY_IDENTITY_VALUES:
        return ""
    return value


def _extract_identity(content: str, requested_title: str) -> BookIdentity | None:
    """Extract only explicit book fields present in the verified Reader body."""

    fields: dict[str, str] = {}

    def add_field(name: str, raw_value: str) -> bool:
        value = _normalise_extracted_field(name, raw_value)
        previous = fields.get(name)
        if previous is not None and previous != value:
            return False
        fields[name] = value
        return True

    for match in _FIELD_LINE.finditer(content):
        name = _FIELD_NAMES[match.group(1).casefold()]
        if not add_field(name, match.group(2)):
            return None

    table_rows = tuple(
        cells
        for cells in (_markdown_cells(line) for line in content.splitlines())
        if cells
    )
    for cells in table_rows:
        if len(cells) == 2:
            name = _field_name(cells[0])
            if name is not None and not add_field(name, cells[1]):
                return None
    for index in range(len(table_rows) - 2):
        headings, separator, values = table_rows[index : index + 3]
        names = tuple(_field_name(cell) for cell in headings)
        if (
            len(headings) == len(values)
            and len(separator) == len(headings)
            and all(re.fullmatch(r":?-{3,}:?", cell) for cell in separator)
            and "title" in names
            and "author" in names
        ):
            for name, value in zip(names, values, strict=True):
                if name is not None and not add_field(name, value):
                    return None

    # An explicit bibliographic title from a label/table is more precise than
    # a page heading. Use H1 only as a fallback and preserve it in full when it
    # is the sole Reader title source.
    heading = _MARKDOWN_HEADING.search(content)
    if (
        "title" not in fields
        and heading is not None
        and not add_field("title", heading.group(1))
    ):
        return None

    if "author" not in fields:
        author = _NATURAL_AUTHOR.search(content)
        if author is not None and not add_field("author", author.group(1)):
            return None
    if "translator" not in fields:
        translator = _NATURAL_TRANSLATOR.search(content)
        if translator is not None and not add_field(
            "translator", translator.group(1)
        ):
            return None
        if re.search(r"^\s*无译者\s*$", content, re.MULTILINE):
            fields["translator"] = ""
    if "language" not in fields:
        for language in _LANGUAGE_ALIASES:
            if re.search(rf"^\s*{re.escape(language)}\s*$", content, re.MULTILINE):
                add_field("language", language)
                break
    if "edition" not in fields:
        edition = _NATURAL_EDITION.search(content)
        if edition is not None and not add_field("edition", edition.group(1)):
            return None
    if not fields.get("title") or not fields.get("author") or not fields.get(
        "language"
    ):
        return None
    if any(
        len(fields.get(name, "")) > maximum
        for name, maximum in _FIELD_LIMITS.items()
    ):
        return None
    try:
        identity = normalize_book_identity(
            fields["title"],
            fields["author"],
            fields["language"],
            fields.get("edition", ""),
            fields.get("translator", ""),
        )
    except (TypeError, ValueError):
        return None
    if not _title_matches_requested(identity.title, requested_title):
        return None
    return identity


class BookDiscoveryService:
    """Runs fixed Search/Reader providers and persists only a complete batch."""

    def __init__(
        self,
        *,
        repository: DiscoveryRepository,
        search_provider: SearchProvider,
        reader_provider: PageReaderProvider,
        url_guard: ReaderURLGuard,
        search_provider_name: str = CODING_PLAN_SEARCH_TOOL_NAME,
        search_schema_digest: str = CODING_PLAN_SEARCH_SCHEMA_DIGEST,
        reader_provider_name: str = CODING_PLAN_READER_TOOL_NAME,
        reader_schema_digest: str = CODING_PLAN_READER_SCHEMA_DIGEST,
    ) -> None:
        self._repository = repository
        self._search_provider = search_provider
        self._reader_provider = reader_provider
        self._url_guard = url_guard
        self._search_provider_name = search_provider_name
        self._search_schema_digest = search_schema_digest
        self._reader_provider_name = reader_provider_name
        self._reader_schema_digest = reader_schema_digest

    def resolve(
        self,
        *,
        project_id: UUID,
        title: str,
        command_key: str,
    ) -> BookDiscoveryResolution:
        if not isinstance(project_id, UUID):
            raise TypeError("project_id must be a UUID")
        if not isinstance(title, str):
            raise TypeError("title must be a string")
        normalized_title = normalize_book_title(title)
        if not normalized_title:
            raise ValueError("title is required")
        query = f"{normalized_title}{DISCOVERY_SEARCH_SUFFIX}"
        if len(query) > 70:
            raise ValueError("title is too long")
        if not isinstance(command_key, str) or not command_key:
            raise ValueError("command_key is required")
        replay = self._repository.get_book_discovery_replay(
            project_id,
            command_key,
            normalized_title,
        )
        if replay is not None:
            return replay

        try:
            capabilities = getattr(
                self._reader_provider, "security_capabilities", None
            )
            if capabilities != ReaderSecurityCapabilities.secure_default():
                raise UnsafeSourceURL(
                    "Reader lacks the required address-binding contract"
                )
            hits = self._search_provider.search(
                SearchRequest(query=query, max_results=MAX_DISCOVERY_RESULTS)
            )
            if not isinstance(hits, tuple) or any(
                not isinstance(hit, SearchHit) for hit in hits
            ):
                raise TypeError("Search returned an invalid payload")
            if len(hits) > MAX_DISCOVERY_RESULTS:
                raise ValueError("Search exceeded the result limit")

            # Search contributes URLs only.  Its title and snippet never enter
            # extraction, persistence, or the returned identity.
            canonical_urls: set[str] = set()
            for hit in hits:
                try:
                    canonical_urls.add(self._url_guard.canonicalize(hit.url))
                except UnsafeSourceURL:
                    # A malformed/static-unsafe Search result is untrusted
                    # provider data, not a failure of the Reader dependency.
                    continue
            discovered: list[DiscoveredBookIdentity] = []
            seen_identities: set[str] = set()
            for canonical_url in sorted(canonical_urls):
                # Dual-DNS validation happens immediately before the Reader
                # call. DNS drift or a non-global answer is a batch failure.
                identity = self._url_guard.validate(canonical_url)
                document = self._reader_provider.read(
                    ReadPageRequest(
                        url=identity.canonical_url,
                        approved_resolved_addresses=tuple(
                            sorted(identity.approved_addresses)
                        ),
                        redirect_policy="forbid",
                        prefetch_policy="connect-approved-address-only",
                    )
                )
                if not isinstance(document, SourceDocumentPayload):
                    raise TypeError("Reader returned an invalid payload")
                self._url_guard.validate_reader_attestation(
                    identity,
                    document_url=document.url,
                    resolved_address=document.security.resolved_address,
                    redirect_chain=document.security.redirect_chain,
                    redirect_policy=document.security.redirect_policy,
                    prefetch_policy=document.security.prefetch_policy,
                )
                actual_digest = hashlib.sha256(
                    document.content.encode("utf-8")
                ).hexdigest()
                if document.content_digest != actual_digest:
                    raise ValueError("Reader content digest mismatch")
                book_identity = _extract_identity(
                    document.content, normalized_title
                )
                if (
                    book_identity is None
                    or book_identity.digest in seen_identities
                ):
                    continue
                seen_identities.add(book_identity.digest)
                discovered.append(
                    DiscoveredBookIdentity(
                        title=book_identity.title,
                        author=book_identity.author,
                        language=book_identity.language,
                        edition=book_identity.edition,
                        translator=book_identity.translator,
                        canonical_url=identity.canonical_url,
                        reader_content_digest=actual_digest,
                    )
                )
        except BookDiscoveryDependencyError:
            raise
        except Exception as error:
            raise BookDiscoveryDependencyError() from error

        stored = self._repository.create_book_discovery_resolution(
            CreateBookDiscoveryResolution(
                project_id=project_id,
                raw_input=title,
                candidates=tuple(discovered),
                search_provider=self._search_provider_name,
                search_schema_digest=self._search_schema_digest,
                reader_provider=self._reader_provider_name,
                reader_schema_digest=self._reader_schema_digest,
                command_key=command_key,
            )
        )
        return stored.value


__all__ = [
    "BookDiscoveryDependencyError",
    "BookDiscoveryService",
    "DISCOVERY_SEARCH_SUFFIX",
    "MAX_DISCOVERY_RESULTS",
]
