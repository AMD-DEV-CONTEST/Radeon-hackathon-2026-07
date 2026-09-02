from __future__ import annotations

import threading
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from shidu_provider_mcp.book_sources import (
    BOOK_QUERY_SUFFIX,
    BookQueryExpansion,
    BookRecord,
    BookSourceError,
    CompositeBookSearch,
    CrossrefClient,
    GoogleBooksClient,
    OpenLibraryClient,
    WikidataBookExpander,
    build_book_queries,
    extract_book_title,
)


def test_extracts_only_the_fixed_discovery_suffix() -> None:
    assert extract_book_title("活着" + BOOK_QUERY_SUFFIX) == "活着"
    assert extract_book_title("活着 书籍 作者") is None
    assert extract_book_title(BOOK_QUERY_SUFFIX) is None


def test_queries_include_original_script_variants_aliases_and_authors() -> None:
    queries = build_book_queries(
        "史蒂夫·賈伯斯傳",
        aliases=("乔布斯传",),
        authors=("沃尔特·艾萨克森",),
    )

    assert queries[0] == "史蒂夫·賈伯斯傳"
    assert "史蒂夫·贾伯斯传" in queries
    assert "乔布斯传" in queries
    assert "乔布斯传 沃尔特·艾萨克森" in queries

    bounded = build_book_queries(
        "活着",
        aliases=tuple(f"alias-{index}" for index in range(10)),
        authors=("余华",),
        max_queries=6,
    )
    assert len(bounded) == 6
    assert "活着 余华" in bounded


def test_google_books_projects_structured_identity_without_leaking_key() -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": "safe-volume",
                        "volumeInfo": {
                            "title": "活着",
                            "authors": ["余华"],
                            "publisher": "作家出版社",
                            "publishedDate": "2012-08",
                            "industryIdentifiers": [
                                {"type": "ISBN_10", "identifier": "750636543X"}
                            ],
                        },
                    }
                ]
            },
        )

    secret = "google-secret-value"
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        source = GoogleBooksClient(api_key=secret, client=client)
        records = source.search("活着", max_results=3)

    assert "key" not in requests[0].url.params
    assert requests[0].headers["x-goog-api-key"] == secret
    assert requests[0].headers["user-agent"].startswith("ShiduBookSearchMCP/")
    assert records == [
        BookRecord(
            title="活着",
            url="https://www.googleapis.com/books/v1/volumes/safe-volume",
            authors=("余华",),
            publisher="作家出版社",
            year="2012",
            isbn="9787506365437",
            source="Google Books",
        )
    ]
    assert secret not in repr(source)
    assert secret not in records[0].url


def test_google_books_sanitizes_http_errors_that_contain_the_key() -> None:
    secret = "do-not-disclose"

    def handle(_: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="failure")

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        source = GoogleBooksClient(api_key=secret, client=client)
        with pytest.raises(BookSourceError) as raised:
            source.search("活着", max_results=1)

    assert secret not in str(raised.value)
    assert raised.value.__cause__ is None


def test_open_library_and_crossref_project_records() -> None:
    def open_library_handle(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "docs": [
                    {
                        "key": "/works/OL1W",
                        "title": "万历十五年",
                        "author_name": ["黄仁宇"],
                        "publisher": ["中华书局"],
                        "first_publish_year": 1981,
                        "isbn": ["9787101052039"],
                    }
                ]
            },
        )

    def crossref_handle(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "message": {
                    "items": [
                        {
                            "DOI": "10.1000/book.1",
                            "title": ["万历十五年"],
                            "author": [{"given": "Ray", "family": "Huang"}],
                            "publisher": "Example Press",
                            "issued": {"date-parts": [[1981, 1, 1]]},
                            "ISBN": ["9787101052039"],
                        }
                    ]
                }
            },
        )

    with (
        httpx.Client(transport=httpx.MockTransport(open_library_handle)) as ol_client,
        httpx.Client(transport=httpx.MockTransport(crossref_handle)) as cr_client,
    ):
        open_library = OpenLibraryClient(client=ol_client).search(
            "万历十五年", max_results=2
        )
        crossref = CrossrefClient(client=cr_client).search("万历十五年", max_results=2)

    open_library_url = urlsplit(open_library[0].url)
    open_library_query = parse_qs(open_library_url.query)
    assert open_library_url.path == "/search.json"
    assert open_library_query["isbn"] == ["9787101052039"]
    assert open_library_query["limit"] == ["1"]
    assert "language" in open_library_query["fields"][0]
    assert open_library[0].authors == ("黄仁宇",)
    assert crossref[0].url == "https://api.crossref.org/works/10.1000%2Fbook.1"
    assert crossref[0].year == "1981"


def test_crossref_excludes_explicit_non_book_types() -> None:
    def handle(_: httpx.Request) -> httpx.Response:
        common = {
            "author": [{"given": "Test", "family": "Author"}],
            "publisher": "Example Press",
        }
        return httpx.Response(
            200,
            json={
                "message": {
                    "items": [
                        {
                            **common,
                            "DOI": "10.1000/article",
                            "title": ["活着研究"],
                            "type": "journal-article",
                        },
                        {
                            **common,
                            "DOI": "10.1000/proceedings",
                            "title": ["活着会议论文"],
                            "type": "proceedings-article",
                        },
                        {
                            **common,
                            "DOI": "10.1000/monograph",
                            "title": ["活着"],
                            "type": "monograph",
                        },
                        {
                            **common,
                            "DOI": "10.1000/book",
                            "title": ["活着：英译本"],
                            "type": "book",
                        },
                    ]
                }
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        records = CrossrefClient(client=client).search("活着", max_results=5)

    assert [record.title for record in records] == ["活着", "活着：英译本"]


def test_open_library_uses_the_work_key_when_no_valid_isbn_exists() -> None:
    def handle(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "docs": [
                    {
                        "key": "/works/OL2W",
                        "title": "围城",
                        "author_name": ["钱钟书"],
                        # Incorrect check digit: it must not become an ISBN key.
                        "isbn": ["9787101052038"],
                    }
                ]
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        record = OpenLibraryClient(client=client).search("围城", max_results=1)[0]

    params = parse_qs(urlsplit(record.url).query)
    assert record.isbn == ""
    assert params["q"] == ["key:/works/OL2W"]
    assert "isbn" not in params


def test_wikidata_expands_aliases_and_author_labels() -> None:
    calls: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        action = request.url.params["action"]
        calls.append(action)
        if action == "wbsearchentities":
            return httpx.Response(200, json={"search": [{"id": "Q1", "label": "乔布斯传"}]})
        if request.url.params["ids"] == "Q1":
            return httpx.Response(
                200,
                json={
                    "entities": {
                        "Q1": {
                            "labels": {"zh": {"value": "史蒂夫·乔布斯传"}},
                            "aliases": {"en": [{"value": "Steve Jobs"}]},
                            "claims": {
                                "P50": [
                                    {
                                        "mainsnak": {
                                            "datavalue": {"value": {"id": "Q2"}}
                                        }
                                    }
                                ]
                            },
                        }
                    }
                },
            )
        return httpx.Response(
            200,
            json={
                "entities": {
                    "Q2": {
                        "labels": {"zh": {"value": "沃尔特·艾萨克森"}},
                        "aliases": {},
                    }
                }
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        expansion = WikidataBookExpander(client=client).expand("乔布斯传")

    assert calls == ["wbsearchentities", "wbgetentities", "wbgetentities"]
    assert "Steve Jobs" in expansion.aliases
    assert expansion.authors == ("沃尔特·艾萨克森",)


def test_composite_isolates_sources_deduplicates_and_respects_limit() -> None:
    requests: list[tuple[str, str]] = []

    class Expander:
        def expand(self, _: str) -> BookQueryExpansion:
            return BookQueryExpansion(aliases=("To Live",), authors=("余华",))

        def close(self) -> None:
            pass

    class FailingSource:
        def search(self, query: str, *, max_results: int) -> list[BookRecord]:
            requests.append(("failed", query))
            raise RuntimeError("one source is down")

        def close(self) -> None:
            pass

    class Source:
        def __init__(self, name: str, records: list[BookRecord]) -> None:
            self.name = name
            self.records = records

        def search(self, query: str, *, max_results: int) -> list[BookRecord]:
            requests.append((self.name, query))
            return self.records if query == "活着" else []

        def close(self) -> None:
            pass

    isbn_record = BookRecord(
        title="活着",
        url="https://books.example/one?key=must-be-removed&lang=zh",
        authors=("余华",),
        publisher="作家出版社",
        year="2012",
        isbn="9787506365437",
        source="one",
    )
    isbn_duplicate = BookRecord(
        title="To Live",
        url="https://books.example/two",
        authors=("Yu Hua",),
        publisher="Anchor",
        year="2003",
        isbn="9787506365437",
        source="two",
    )
    metadata_record = BookRecord(
        title="兄弟",
        url="https://books.example/three",
        authors=("余华",),
        publisher="作家出版社",
        year="2015",
        source="two",
    )
    composite = CompositeBookSearch(
        sources=(
            FailingSource(),
            Source("one", [isbn_record]),
            Source("two", [isbn_duplicate, metadata_record]),
        ),
        wikidata=Expander(),
    )

    result = composite.search("活着" + BOOK_QUERY_SUFFIX, max_results=2)

    assert [hit["title"] for hit in result["hits"]] == ["活着", "兄弟"]
    assert result["hits"][0]["url"] == "https://books.example/one?lang=zh"
    assert "To Live" in [query for _, query in requests]
    assert "活着 余华" in [query for _, query in requests]
    assert all(
        len([query for called_source, query in requests if called_source == source])
        <= 6
        for source in ("failed", "one", "two")
    )
    assert len(result["hits"]) == 2


def test_composite_preserves_rows_when_a_later_alias_fails() -> None:
    class IntermittentSource:
        def search(self, query: str, *, max_results: int) -> list[BookRecord]:
            if query == "活着":
                return [
                    BookRecord(
                        title="活着",
                        url="https://books.example/to-live",
                        authors=("余华",),
                        source="catalogue",
                    )
                ]
            raise BookSourceError("alias unavailable")

        def close(self) -> None:
            pass

    class Expander:
        def expand(self, _: str) -> BookQueryExpansion:
            return BookQueryExpansion(aliases=("To Live",))

        def close(self) -> None:
            pass

    composite = CompositeBookSearch(
        sources=(IntermittentSource(),),
        wikidata=Expander(),
    )

    result = composite.search("活着" + BOOK_QUERY_SUFFIX, max_results=5)

    assert [hit["title"] for hit in result["hits"]] == ["活着"]


def test_composite_globally_ranks_before_deduplication_and_truncation() -> None:
    shared_isbn = "9787506365437"

    class Expander:
        def expand(self, _: str) -> BookQueryExpansion:
            return BookQueryExpansion(aliases=("To Live",))

        def close(self) -> None:
            pass

    class Source:
        def __init__(self, records: list[BookRecord]) -> None:
            self.records = records

        def search(self, query: str, *, max_results: int) -> list[BookRecord]:
            return self.records if query == "活着" else []

        def close(self) -> None:
            pass

    google = Source(
        [
            BookRecord(
                title="Unrelated catalogue row",
                url="https://google.example/wrong-duplicate",
                isbn=shared_isbn,
            ),
            BookRecord(
                title="Another unrelated row",
                url="https://google.example/wrong",
                isbn="9787101052039",
            ),
        ]
    )
    open_library = Source(
        [
            BookRecord(
                title="To Live",
                url="https://openlibrary.example/alias",
                isbn="9781400031863",
            )
        ]
    )
    crossref = Source(
        [
            BookRecord(
                title="活着",
                url="https://crossref.example/exact",
                isbn=shared_isbn,
            )
        ]
    )
    composite = CompositeBookSearch(
        sources=(google, open_library, crossref),
        wikidata=Expander(),
    )

    result = composite.search("活着" + BOOK_QUERY_SUFFIX, max_results=2)

    assert [(hit["title"], hit["url"]) for hit in result["hits"]] == [
        ("活着", "https://crossref.example/exact"),
        ("To Live", "https://openlibrary.example/alias"),
    ]


def test_composite_ranking_is_stable_for_equal_title_relevance() -> None:
    class Expander:
        def expand(self, _: str) -> BookQueryExpansion:
            return BookQueryExpansion()

        def close(self) -> None:
            pass

    class Source:
        def __init__(self, ordinal: int) -> None:
            self.ordinal = ordinal

        def search(self, query: str, *, max_results: int) -> list[BookRecord]:
            if query != "活着":
                return []
            return [
                BookRecord(
                    title="活着",
                    url=f"https://source-{self.ordinal}.example/book",
                    publisher=f"publisher-{self.ordinal}",
                )
            ]

        def close(self) -> None:
            pass

    composite = CompositeBookSearch(
        sources=(Source(0), Source(1), Source(2)),
        wikidata=Expander(),
    )

    result = composite.search("活着" + BOOK_QUERY_SUFFIX, max_results=3)

    assert [hit["url"] for hit in result["hits"]] == [
        "https://source-0.example/book",
        "https://source-1.example/book",
        "https://source-2.example/book",
    ]


def test_composite_runs_sources_in_parallel_but_merges_in_source_order() -> None:
    barrier = threading.Barrier(3)

    class Expander:
        def expand(self, _: str) -> BookQueryExpansion:
            return BookQueryExpansion()

        def close(self) -> None:
            pass

    class ConcurrentSource:
        def __init__(self, ordinal: int) -> None:
            self.ordinal = ordinal
            self.first_call = True

        def search(self, query: str, *, max_results: int) -> list[BookRecord]:
            if self.first_call:
                self.first_call = False
                barrier.wait(timeout=1)
                return [
                    BookRecord(
                        title=f"book-{self.ordinal}",
                        url=f"https://source-{self.ordinal}.example/book",
                        isbn=f"97871010520{self.ordinal}9",
                    )
                ]
            return []

        def close(self) -> None:
            pass

    composite = CompositeBookSearch(
        sources=tuple(ConcurrentSource(index) for index in range(3)),
        wikidata=Expander(),
    )

    result = composite.search("活着" + BOOK_QUERY_SUFFIX, max_results=3)

    assert [hit["title"] for hit in result["hits"]] == [
        "book-0",
        "book-1",
        "book-2",
    ]


def test_catalogue_rejects_an_oversized_or_redirect_response() -> None:
    body = b'{"items":[],"padding":"' + (b"x" * 100) + b'"}'

    def oversized(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body)

    with httpx.Client(transport=httpx.MockTransport(oversized)) as client:
        with pytest.raises(BookSourceError, match="large"):
            GoogleBooksClient(
                client=client,
                max_response_bytes=50,
            ).search("活着", max_results=1)

    def redirect(_: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://evil.example/"})

    with httpx.Client(transport=httpx.MockTransport(redirect)) as client:
        with pytest.raises(BookSourceError, match="unavailable"):
            OpenLibraryClient(client=client).search("活着", max_results=1)
