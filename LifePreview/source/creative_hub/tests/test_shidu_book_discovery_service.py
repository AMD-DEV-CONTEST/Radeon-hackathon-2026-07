from __future__ import annotations

import hashlib
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from creative_hub.db.models import (
    BookDiscoveryCandidateRecord,
    InputResolutionRecord,
    ProjectRecord,
)
from creative_hub.models import OrchestrationBase
from creative_hub.shidu.book_identity import normalize_book_title
from creative_hub.shidu.book_discovery_service import (
    BookDiscoveryDependencyError,
    BookDiscoveryService,
)
from creative_hub.shidu.providers import (
    ProviderContractError,
    ReaderSecurityAttestation,
    ReaderSecurityCapabilities,
    SearchHit,
    SourceDocumentPayload,
)
from creative_hub.shidu.repository import ShiduRepository
from creative_hub.shidu.repository import IdempotencyConflict
from creative_hub.shidu.url_security import ReaderURLGuard


PROJECT_ID = UUID("11111111-1111-4111-8111-111111111111")
PUBLIC_ADDRESS = "8.8.8.8"
FIXTURE_DIRECTORY = Path(__file__).parent / "fixtures" / "shidu"


@pytest.fixture()
def session() -> Session:
    engine = create_engine(
        "sqlite+pysqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def attach(connection, _record) -> None:
        connection.execute("ATTACH DATABASE ':memory:' AS orchestration")
        connection.execute("PRAGMA foreign_keys = ON")

    OrchestrationBase.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as value:
        value.add(
            ProjectRecord(
                id=PROJECT_ID,
                project_key="book-discovery-service",
                title="Book discovery service",
                config={},
                config_digest="0" * 64,
            )
        )
        value.commit()
        yield value
    engine.dispose()


def _body(
    title: str = "活着",
    author: str = "余华",
    language: str = "zh-CN",
    edition: str = "2012 版",
    translator: str = "",
) -> str:
    return "\n".join(
        (
            f"书名：{title}",
            f"作者：{author}",
            f"语言：{language}",
            f"版本：{edition}",
            f"译者：{translator}",
            "这是 Reader 核验正文。",
        )
    )


class SearchFixture:
    def __init__(self, hits: tuple[SearchHit, ...]) -> None:
        self.hits = hits
        self.requests = []

    def search(self, request):
        self.requests.append(request)
        return self.hits


class ReaderFixture:
    security_capabilities = ReaderSecurityCapabilities.secure_default()

    def __init__(self, bodies: dict[str, str]) -> None:
        self.bodies = bodies
        self.requests = []

    def read(self, request):
        self.requests.append(request)
        body = self.bodies[request.url]
        return SourceDocumentPayload(
            url=request.url,
            title="Reader page title must not define book identity",
            content=body,
            content_digest=hashlib.sha256(body.encode("utf-8")).hexdigest(),
            content_type="text/plain",
            security=ReaderSecurityAttestation(
                resolved_address=PUBLIC_ADDRESS,
                redirect_chain=(request.url,),
                redirect_policy="forbid",
                prefetch_policy="connect-approved-address-only",
            ),
        )


def _service(session: Session, search, reader, *, resolver=None):
    return BookDiscoveryService(
        repository=ShiduRepository(session),
        search_provider=search,
        reader_provider=reader,
        url_guard=ReaderURLGuard(
            resolver=resolver or (lambda _host: (PUBLIC_ADDRESS,))
        ),
    )


def _counts(session: Session) -> tuple[int, int]:
    return (
        session.scalar(select(func.count()).select_from(InputResolutionRecord)),
        session.scalar(
            select(func.count()).select_from(BookDiscoveryCandidateRecord)
        ),
    )


def test_resolve_input_runs_fixed_search_then_reader_and_returns_only_verified_candidates(
    session: Session,
) -> None:
    first_url = "https://books.example.org/z-edition"
    second_url = "https://books.example.org/a-edition"
    search = SearchFixture(
        (
            SearchHit(
                title="untrusted search title",
                url=first_url,
                snippet=_body(title="搜索摘要伪造书名", author="攻击者"),
            ),
            SearchHit(
                title="another untrusted title",
                url=second_url,
                snippet=_body(title="另一个伪造书名", author="攻击者"),
            ),
        )
    )
    reader = ReaderFixture(
        {
            first_url: _body(edition="2021 版"),
            second_url: _body(edition="2012 版"),
        }
    )

    result = _service(session, search, reader).resolve(
        project_id=PROJECT_ID,
        title="《活着》",
        command_key="discover:verified",
    )

    assert len(search.requests) == 1
    assert search.requests[0].query == "活着 书籍 作者 版本 译者"
    assert search.requests[0].max_results == 20
    assert [request.url for request in reader.requests] == sorted(
        (first_url, second_url)
    )
    assert result.status == "AMBIGUOUS"
    assert [candidate.ordinal for candidate in result.candidates] == [1, 2]
    assert [candidate.canonical_url for candidate in result.candidates] == sorted(
        (first_url, second_url)
    )
    assert {candidate.title for candidate in result.candidates} == {"活着"}
    assert {candidate.author for candidate in result.candidates} == {"余华"}
    assert "搜索摘要伪造书名" not in {
        candidate.title for candidate in result.candidates
    }
    assert _counts(session) == (1, 2)


@pytest.mark.parametrize(
    "failure_kind", ["ssrf", "attestation", "schema", "tool"]
)
def test_discovery_rejects_reader_url_ssrf_attestation_and_schema_drift_without_partial_candidates(
    session: Session,
    failure_kind: str,
) -> None:
    safe_url = "https://safe.example.org/book"
    other_url = "https://other.example.org/book"
    search = SearchFixture(
        (
            SearchHit(title="safe first", url=safe_url, snippet=""),
            SearchHit(title="fails later", url=other_url, snippet=""),
        )
    )
    reader = ReaderFixture({safe_url: _body(), other_url: _body(edition="2021")})

    if failure_kind == "ssrf":
        resolver = lambda host: (
            ("127.0.0.1",) if host == "other.example.org" else (PUBLIC_ADDRESS,)
        )
    else:
        resolver = None

    if failure_kind == "attestation":
        original_read = reader.read

        def mismatched_attestation(request):
            document = original_read(request)
            if request.url == other_url:
                return SourceDocumentPayload(
                    url=request.url,
                    title=document.title,
                    content=document.content,
                    content_digest=document.content_digest,
                    content_type=document.content_type,
                    security=ReaderSecurityAttestation(
                        resolved_address="1.1.1.1",
                        redirect_chain=(request.url,),
                        redirect_policy="forbid",
                        prefetch_policy="connect-approved-address-only",
                    ),
                )
            return document

        reader.read = mismatched_attestation

    if failure_kind in {"schema", "tool"}:
        original_read = reader.read

        def schema_drift(request):
            if request.url == other_url:
                raise ProviderContractError(
                    f"reader {failure_kind} contract mismatch"
                )
            return original_read(request)

        reader.read = schema_drift

    with pytest.raises(BookDiscoveryDependencyError) as captured:
        _service(session, search, reader, resolver=resolver).resolve(
            project_id=PROJECT_ID,
            title="活着",
            command_key=f"discover:{failure_kind}",
        )

    assert captured.value.retryable is True
    assert _counts(session) == (0, 0)


def test_discovery_unresolved_is_non_retryable_and_provider_unavailable_is_retryable(
    session: Session,
) -> None:
    url = "https://books.example.org/unrelated"
    unresolved = _service(
        session,
        SearchFixture((SearchHit(title="search only", url=url, snippet=_body()),)),
        ReaderFixture({url: "Reader 正文没有结构化书目信息。"}),
    ).resolve(
        project_id=PROJECT_ID,
        title="活着",
        command_key="discover:unresolved",
    )

    assert unresolved.status == "UNRESOLVED"
    assert unresolved.retryable is False
    assert unresolved.candidates == ()
    assert _counts(session) == (1, 0)

    class UnavailableSearch:
        def search(self, request):
            raise ProviderContractError("MCP provider is unavailable")

    with pytest.raises(BookDiscoveryDependencyError) as captured:
        _service(session, UnavailableSearch(), ReaderFixture({})).resolve(
            project_id=PROJECT_ID,
            title="兄弟",
            command_key="discover:unavailable",
        )
    assert captured.value.retryable is True
    assert _counts(session) == (1, 0)


def test_discovery_sorting_and_identity_dedup_are_stable_and_search_snippet_cannot_form_candidate(
    session: Session,
) -> None:
    urls = (
        "https://books.example.org/z",
        "https://books.example.org/a",
        "https://books.example.org/m",
    )
    search = SearchFixture(
        tuple(
            SearchHit(title="untrusted", url=url, snippet=_body()) for url in urls
        )
    )
    reader = ReaderFixture(
        {
            urls[0]: _body(edition="same"),
            urls[1]: _body(edition="same"),
            urls[2]: "正文没有书目字段。",
        }
    )

    result = _service(session, search, reader).resolve(
        project_id=PROJECT_ID,
        title="活着",
        command_key="discover:stable",
    )

    assert len(result.candidates) == 1
    assert result.candidates[0].canonical_url == min(urls[:2])
    assert result.candidates[0].ordinal == 1
    assert _counts(session) == (1, 1)


@pytest.mark.parametrize(
    (
        "reader_body",
        "expected_title",
        "expected_edition",
        "expected_translator",
    ),
    [
        (
            (FIXTURE_DIRECTORY / "book-discovery-reader-page.md").read_text(
                encoding="utf-8"
            ),
            "活着",
            "2012 年版",
            "",
        ),
        (
            """# 活着：一部长篇小说（版本消歧）

| 书名 | 作者 | 语种 | 版本 | 译者 |
| --- | --- | --- | --- | --- |
| 活着 | 余华 | 简体中文 | 2021 年版 | 无 |
""",
            "活着",
            "2021 年版",
            "",
        ),
        (
            """# 《活着》（长篇小说）

书目信息
余华 著
简体中文
1993 年版
无译者
""",
            normalize_book_title("《活着》（长篇小说）"),
            "1993 年版",
            "",
        ),
    ],
)
def test_reader_only_real_page_shapes_extract_deterministic_book_identity(
    session: Session,
    reader_body: str,
    expected_title: str,
    expected_edition: str,
    expected_translator: str,
) -> None:
    url = f"https://catalog.example.org/book/{expected_edition[:4]}"
    search = SearchFixture(
        (
            SearchHit(
                title="Search title must stay untrusted",
                url=url,
                snippet=_body(title="摘要伪造书名", author="摘要伪造作者"),
            ),
        )
    )

    result = _service(session, search, ReaderFixture({url: reader_body})).resolve(
        project_id=PROJECT_ID,
        title="活着",
        command_key=f"discover:real-page:{expected_edition}",
    )

    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.title == expected_title
    assert candidate.author == "余华"
    assert candidate.language == "zh-cn"
    assert candidate.edition == expected_edition.casefold()
    assert candidate.translator == expected_translator
    assert "摘要伪造" not in f"{candidate.title}{candidate.author}"


def test_discovery_preserves_full_reader_title_when_request_includes_subtitle(
    session: Session,
) -> None:
    url = "https://catalog.example.org/books/test-book-part-one"
    full_title = "测试之书：上篇"

    result = _service(
        session,
        SearchFixture((SearchHit(title="untrusted", url=url, snippet=""),)),
        ReaderFixture(
            {
                url: _body(
                    title=full_title,
                    author="同一作者",
                    language="zh-CN",
                    edition="初版",
                )
            }
        ),
    ).resolve(
        project_id=PROJECT_ID,
        title=full_title,
        command_key="discover:full-subtitle",
    )

    assert [candidate.title for candidate in result.candidates] == [
        normalize_book_title(full_title)
    ]


def test_discovery_main_title_request_keeps_distinct_reader_subtitle_identities(
    session: Session,
) -> None:
    urls_and_titles = (
        (
            "https://catalog.example.org/books/test-book-part-one",
            "测试之书：上篇",
        ),
        (
            "https://catalog.example.org/books/test-book-part-two",
            "测试之书：下篇",
        ),
    )
    search = SearchFixture(
        tuple(
            SearchHit(title="untrusted", url=url, snippet="")
            for url, _title in urls_and_titles
        )
    )
    reader = ReaderFixture(
        {
            url: _body(
                title=title,
                author="同一作者",
                language="zh-CN",
                edition="同版",
            )
            for url, title in urls_and_titles
        }
    )

    result = _service(session, search, reader).resolve(
        project_id=PROJECT_ID,
        title="测试之书",
        command_key="discover:distinct-subtitles",
    )

    assert {candidate.title for candidate in result.candidates} == {
        normalize_book_title(title) for _url, title in urls_and_titles
    }
    assert len({candidate.identity_digest for candidate in result.candidates}) == 2


def test_discovery_accepts_a_common_short_title_suffix_without_overwriting_identity(
    session: Session,
) -> None:
    url = "https://catalog.example.org/books/steve-jobs"
    result = _service(
        session,
        SearchFixture((SearchHit(title="untrusted", url=url, snippet=""),)),
        ReaderFixture(
            {
                url: _body(
                    title="史蒂夫·乔布斯传",
                    author="沃尔特·艾萨克森",
                    language="zh-CN",
                    edition="初版",
                )
            }
        ),
    ).resolve(
        project_id=PROJECT_ID,
        title="乔布斯传",
        command_key="discover:common-short-title",
    )

    assert [candidate.title for candidate in result.candidates] == [
        normalize_book_title("史蒂夫·乔布斯传")
    ]


def test_discovery_rejects_an_uncontrolled_title_that_only_shares_a_suffix(
    session: Session,
) -> None:
    url = "https://catalog.example.org/books/not-steve-jobs"
    result = _service(
        session,
        SearchFixture((SearchHit(title="untrusted", url=url, snippet=""),)),
        ReaderFixture(
            {
                url: _body(
                    title="伪乔布斯传",
                    author="未知作者",
                    language="zh-CN",
                    edition="初版",
                )
            }
        ),
    ).resolve(
        project_id=PROJECT_ID,
        title="乔布斯传",
        command_key="discover:reject-uncontrolled-suffix",
    )

    assert result.status == "UNRESOLVED"
    assert result.candidates == ()


def test_discovery_parenthetical_and_dash_suffixes_are_not_identity_collapsed(
    session: Session,
) -> None:
    urls_and_titles = (
        (
            "https://catalog.example.org/books/test-book-hardcover",
            "测试之书（精装版）",
        ),
        (
            "https://catalog.example.org/books/test-book-collectors",
            "测试之书—典藏版",
        ),
    )
    result = _service(
        session,
        SearchFixture(
            tuple(
                SearchHit(title="untrusted", url=url, snippet="")
                for url, _title in urls_and_titles
            )
        ),
        ReaderFixture(
            {
                url: _body(
                    title=title,
                    author="同一作者",
                    language="zh-CN",
                    edition="同版",
                )
                for url, title in urls_and_titles
            }
        ),
    ).resolve(
        project_id=PROJECT_ID,
        title="测试之书",
        command_key="discover:distinct-title-suffixes",
    )

    assert {candidate.title for candidate in result.candidates} == {
        normalize_book_title(title) for _url, title in urls_and_titles
    }
    assert len({candidate.identity_digest for candidate in result.candidates}) == 2


def test_discovery_skips_static_unsafe_search_hits_but_keeps_verified_https_hit(
    session: Session,
) -> None:
    good_url = "https://catalog.example.org/books/to-live"
    search = SearchFixture(
        (
            SearchHit(title="plain HTTP", url="http://example.org/book", snippet=""),
            SearchHit(
                title="IP literal",
                url="https://127.0.0.1/book",
                snippet="",
            ),
            SearchHit(
                title="non-default port",
                url="https://example.org:444/book",
                snippet="",
            ),
            SearchHit(title="verified", url=good_url, snippet=""),
        )
    )
    reader = ReaderFixture({good_url: _body()})

    result = _service(session, search, reader).resolve(
        project_id=PROJECT_ID,
        title="活着",
        command_key="discover:mixed-static-unsafe",
    )

    assert [request.url for request in reader.requests] == [good_url]
    assert [candidate.canonical_url for candidate in result.candidates] == [
        good_url
    ]
    assert _counts(session) == (1, 1)


def test_discovery_all_static_unsafe_search_hits_is_stable_unresolved(
    session: Session,
) -> None:
    search = SearchFixture(
        (
            SearchHit(title="plain HTTP", url="http://example.org/book", snippet=""),
            SearchHit(
                title="IP literal",
                url="https://127.0.0.1/book",
                snippet="",
            ),
        )
    )
    reader = ReaderFixture({})

    result = _service(session, search, reader).resolve(
        project_id=PROJECT_ID,
        title="活着",
        command_key="discover:all-static-unsafe",
    )

    assert result.status == "UNRESOLVED"
    assert result.retryable is False
    assert result.candidates == ()
    assert reader.requests == []
    assert _counts(session) == (1, 0)


def test_discovery_dns_rebinding_after_static_acceptance_fails_whole_batch(
    session: Session,
) -> None:
    answers = iter(((PUBLIC_ADDRESS,), ("1.1.1.1",)))
    url = "https://catalog.example.org/book"

    with pytest.raises(BookDiscoveryDependencyError):
        _service(
            session,
            SearchFixture((SearchHit(title="book", url=url, snippet=""),)),
            ReaderFixture({url: _body()}),
            resolver=lambda _host: next(answers),
        ).resolve(
            project_id=PROJECT_ID,
            title="活着",
            command_key="discover:dns-rebinding",
        )

    assert _counts(session) == (0, 0)


def test_discovery_durable_replay_precedes_remote_calls_and_title_conflict(
    session: Session,
) -> None:
    url = "https://catalog.example.org/books/to-live"
    search = SearchFixture((SearchHit(title="book", url=url, snippet=""),))
    reader = ReaderFixture({url: _body()})
    service = _service(session, search, reader)

    first = service.resolve(
        project_id=PROJECT_ID,
        title="《活着》",
        command_key="discover:durable-replay",
    )
    replay = service.resolve(
        project_id=PROJECT_ID,
        title=" 活着 ",
        command_key="discover:durable-replay",
    )

    assert replay.id == first.id
    assert replay.digest == first.digest
    assert len(search.requests) == 1
    assert len(reader.requests) == 1

    with pytest.raises(IdempotencyConflict):
        service.resolve(
            project_id=PROJECT_ID,
            title="兄弟",
            command_key="discover:durable-replay",
        )
    assert len(search.requests) == 1
    assert len(reader.requests) == 1
