from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from datetime import UTC, datetime
import hashlib
from time import perf_counter
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from creative_hub.db.models import ProjectRecord
from creative_hub.models import OrchestrationBase
from creative_hub.shidu.providers import SearchHit as ProviderSearchHit
from creative_hub.shidu.providers import (
    ReaderSecurityAttestation,
    ReaderSecurityCapabilities,
    SourceDocumentPayload,
)
from creative_hub.shidu.query_planner import (
    QueryPlan,
    QueryPlanError,
    QueryPlanner,
)
from creative_hub.shidu.research_service import (
    AICompletedContent,
    InsecureReaderProvider,
    InvalidResearchState,
    ResearchService,
    registrable_site_key,
)
from creative_hub.shidu.repository import (
    InvalidResearchJobTransition,
    ShiduRepository,
)
from creative_hub.shidu.schemas import (
    Book,
    CreateBook,
    CreateResearchJob,
    CreateSearchHit,
    CreateSearchQuery,
    ResearchJob,
    SearchHit,
    SearchQuery,
    SourceDocumentRevision,
    SourceFailure,
    StoreSourceFailure,
)
from creative_hub.shidu.url_security import ReaderURLGuard


NOW = datetime(2026, 8, 3, tzinfo=UTC)


class FixedPlanner:
    def __init__(self, count: int = 6) -> None:
        self.count = count
        self.calls = 0

    def plan(self, _book: Book) -> QueryPlan:
        self.calls += 1
        return QueryPlan(
            queries=tuple(f"query {number}" for number in range(self.count)),
            evidence_gaps=("publication context",),
        )


class FakeSearch:
    def __init__(self, hits_per_query: int = 3) -> None:
        self.hits_per_query = hits_per_query
        self.calls = 0

    def search(self, request):
        self.calls += 1
        base = (self.calls - 1) * self.hits_per_query
        return tuple(
            ProviderSearchHit(
                title=f"Source {base + offset}",
                url=f"https://source{base + offset}.example/book",
                snippet=f"untrusted snippet fact {base + offset}",
            )
            for offset in range(self.hits_per_query)
        )


class SameDomainSearch(FakeSearch):
    def search(self, request):
        self.calls += 1
        return tuple(
            ProviderSearchHit(
                title=f"Mirror {offset}",
                url=f"https://same.example/book/{offset}",
                snippet="not evidence",
            )
            for offset in range(self.hits_per_query)
        )


class BoundarySearch(FakeSearch):
    def search(self, request):
        self.calls += 1
        if self.calls == 4:
            raise RuntimeError("fourth search fails")
        return ()


class DiversifyingSearch(FakeSearch):
    def search(self, request):
        self.calls += 1
        urls = [f"https://mirror{number}.example.com/book" for number in range(8)]
        urls.extend(
            [
                "https://later-independent.net/book",
                "https://reviews.independent.org/book",
            ]
        )
        return tuple(
            ProviderSearchHit(title=f"Source {number}", url=url, snippet="")
            for number, url in enumerate(urls)
        )


class FakeReader:
    security_capabilities = ReaderSecurityCapabilities.secure_default()

    def __init__(self, *, fail_suffix: str | None = None) -> None:
        self.fail_suffix = fail_suffix
        self.calls = 0
        self.requests = []

    def read(self, request):
        import hashlib

        self.calls += 1
        self.requests.append(request)
        if self.fail_suffix and request.url.endswith(self.fail_suffix):
            raise RuntimeError("secret-token=do-not-leak internal provider traceback")
        unique_context = hashlib.sha256(request.url.encode("utf-8")).hexdigest()
        content = (
            f"Full reader content for {request.url} with analysis and context. "
            f"Distinct source account: {unique_context} {unique_context}."
        )
        return SourceDocumentPayload(
            url=request.url,
            title="Reader title",
            content=content,
            content_digest=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            content_type="text/plain",
            security=ReaderSecurityAttestation(
                resolved_address=request.approved_resolved_addresses[0],
                redirect_chain=(request.url,),
                redirect_policy=request.redirect_policy,
                prefetch_policy=request.prefetch_policy,
            ),
        )


class NearDuplicateReader(FakeReader):
    def read(self, request):
        self.calls += 1
        suffix = "today" if self.calls == 1 else "today."
        content = ("A detailed critical account of the book and its reception " * 8) + suffix
        return SourceDocumentPayload(
            url=request.url,
            title="Reader title",
            content=content,
            content_digest=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            content_type="text/plain",
            security=ReaderSecurityAttestation(
                resolved_address=request.approved_resolved_addresses[0],
                redirect_chain=(request.url,),
                redirect_policy=request.redirect_policy,
                prefetch_policy=request.prefetch_policy,
            ),
        )


class FailEighthReader(FakeReader):
    def read(self, request):
        if self.calls == 7:
            self.calls += 1
            self.requests.append(request)
            raise RuntimeError("eighth reader fails")
        return super().read(request)


class AttestationMismatchReader(FakeReader):
    def __init__(self, *, redirect: bool = False) -> None:
        super().__init__()
        self.redirect = redirect

    def read(self, request):
        self.calls += 1
        self.requests.append(request)
        chain = (request.url, "https://redirect.invalid/page") if self.redirect else (request.url,)
        return SourceDocumentPayload(
            url=request.url,
            title="Reader title",
            content="Synthetic reader content",
            content_digest=hashlib.sha256(
                "Synthetic reader content".encode("utf-8")
            ).hexdigest(),
            content_type="text/plain",
            security=ReaderSecurityAttestation(
                resolved_address=(
                    request.approved_resolved_addresses[0]
                    if self.redirect
                    else "1.1.1.1"
                ),
                redirect_chain=chain,
                redirect_policy=request.redirect_policy,
                prefetch_policy=request.prefetch_policy,
            ),
        )


class InsecureReader:
    def __init__(self) -> None:
        self.calls = 0

    def read(self, request):
        self.calls += 1
        raise AssertionError("insecure reader must never be called")


class FakeAICompleter:
    model_id = "test-ai-completer-v1"

    def __init__(self) -> None:
        self.calls: list[tuple[Book, tuple[SourceDocumentRevision, ...]]] = []

    def complete(
        self,
        *,
        book: Book,
        sources: tuple[SourceDocumentRevision, ...],
    ) -> AICompletedContent:
        self.calls.append((book, sources))
        return AICompletedContent(
            content=(
                "情节梗概：主人公面对处境变化，作出影响人生方向的选择。"
                "情绪脉络：从迟疑走向承担，过程保留不确定性。"
                "适读提示：适合关注人物选择与命运变化的读者。"
            ),
            model_id=self.model_id,
        )


class LargeNearDuplicateReader(FakeReader):
    def __init__(self) -> None:
        super().__init__()
        self.content = "alpha beta gamma delta epsilon " * 30_000

    def read(self, request):
        self.calls += 1
        self.requests.append(request)
        content = self.content + ("." if self.calls == 2 else "")
        return SourceDocumentPayload(
            url=request.url,
            title="Large document",
            content=content,
            content_digest=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            content_type="text/plain",
            security=ReaderSecurityAttestation(
                resolved_address=request.approved_resolved_addresses[0],
                redirect_chain=(request.url,),
                redirect_policy=request.redirect_policy,
                prefetch_policy=request.prefetch_policy,
            ),
        )


class FakeRepository:
    def __init__(self, book: Book, jobs: tuple[ResearchJob, ...]) -> None:
        self.book = book
        self.jobs = {job.id: job for job in jobs}
        self.queries: dict[UUID, list[SearchQuery]] = defaultdict(list)
        self.hits: dict[UUID, list[SearchHit]] = defaultdict(list)
        self.sources: dict[UUID, list[SourceDocumentRevision]] = defaultdict(list)
        self.failures: dict[UUID, list[SourceFailure]] = defaultdict(list)
        self.transitions: list[tuple[str, str]] = []

    def get_research_job(self, job_id: UUID) -> ResearchJob:
        return self.jobs[job_id]

    def get_book(self, project_id: UUID, book_id: UUID) -> Book:
        assert project_id == self.book.project_id and book_id == self.book.id
        return self.book

    def transition_research_job(
        self, job_id: UUID, expected_status: str, new_status: str
    ) -> ResearchJob:
        job = self.jobs[job_id]
        if job.status != expected_status:
            raise InvalidResearchState("stale research state")
        updated = replace(job, status=new_status)
        self.jobs[job_id] = updated
        self.transitions.append((expected_status, new_status))
        return updated

    def find_reusable_research_job(
        self,
        *,
        project_id: UUID,
        book_id: UUID,
        provider_version: str,
        exclude_job_id: UUID,
    ) -> ResearchJob | None:
        for job in self.jobs.values():
            if (
                job.id != exclude_job_id
                and job.project_id == project_id
                and job.book_id == book_id
                and job.provider_version == provider_version
                and job.status in {"ready", "insufficient"}
            ):
                return job
        return None

    def append_search_query(self, command) -> SearchQuery:
        query = SearchQuery(
            id=uuid4(),
            project_id=command.project_id,
            research_job_id=command.research_job_id,
            ordinal=command.ordinal,
            query=command.query,
            provider=command.provider,
            provider_version=command.provider_version,
            digest=f"{command.ordinal:064x}",
        )
        self.queries[command.research_job_id].append(query)
        return query

    def append_search_hit(self, command) -> SearchHit:
        query = next(
            query
            for queries in self.queries.values()
            for query in queries
            if query.id == command.search_query_id
        )
        hit = SearchHit(
            id=uuid4(),
            project_id=command.project_id,
            research_job_id=query.research_job_id,
            search_query_id=command.search_query_id,
            ordinal=command.ordinal,
            canonical_url=command.canonical_url,
            title=command.title,
            snippet=command.snippet,
            source_type=command.source_type,
            digest=f"{command.ordinal:064x}",
        )
        self.hits[command.search_query_id].append(hit)
        return hit

    def append_source_failure(self, command) -> SourceFailure:
        failure = SourceFailure(
            id=uuid4(),
            project_id=command.project_id,
            research_job_id=command.research_job_id,
            stage=command.stage,
            canonical_url=command.canonical_url,
            reason_code=command.reason_code,
            attempts=command.attempts,
            command_key=command.command_key,
            created_at=NOW,
        )
        self.failures[command.research_job_id].append(failure)
        return failure

    def store_source_revision(self, command) -> SourceDocumentRevision:
        import hashlib

        digest = hashlib.sha256(command.content.encode("utf-8")).hexdigest()
        source = SourceDocumentRevision(
            id=uuid4(),
            project_id=command.project_id,
            research_job_id=command.research_job_id,
            canonical_url=command.canonical_url,
            source_type=command.source_type,
            source_classification_version=command.source_classification_version,
            registered_domain=registrable_site_key(
                command.canonical_url.split("/", 3)[2]
            ),
            search_hit_id=command.search_hit_id,
            revision=1,
            content=command.content,
            content_digest=digest,
            digest=digest,
            command_key=command.command_key,
            created_at=NOW,
        )
        self.sources[command.research_job_id].append(source)
        return source

    def list_search_queries(self, job_id: UUID) -> tuple[SearchQuery, ...]:
        return tuple(self.queries[job_id])

    def list_search_hits(self, job_id: UUID) -> tuple[SearchHit, ...]:
        query_ids = {query.id for query in self.queries[job_id]}
        return tuple(hit for query_id in query_ids for hit in self.hits[query_id])

    def list_source_revisions(self, job_id: UUID) -> tuple[SourceDocumentRevision, ...]:
        return tuple(self.sources[job_id])

    def list_source_failures(self, job_id: UUID) -> tuple[SourceFailure, ...]:
        return tuple(self.failures[job_id])


@pytest.fixture
def book_and_jobs() -> tuple[Book, ResearchJob, ResearchJob]:
    project_id = uuid4()
    book = Book(
        id=uuid4(),
        project_id=project_id,
        identity_digest="a" * 64,
        title="The Book",
        author="The Author",
        language="en",
        edition="",
        translator="",
        created_at=NOW,
    )

    def job(command: str) -> ResearchJob:
        return ResearchJob(
            id=uuid4(),
            project_id=project_id,
            book_id=book.id,
            provider_version="coding-plan-v1",
            status="queued",
            query_budget=99,
            reader_budget=99,
            retry_budget=99,
            digest="b" * 64,
            command_key=command,
            created_at=NOW,
        )

    return book, job("job-1"), job("job-2")


def make_service(
    repository,
    search,
    reader,
    planner=None,
    *,
    ai_completer=None,
) -> ResearchService:
    return ResearchService(
        repository=repository,
        planner=planner or FixedPlanner(),
        search_provider=search,
        reader_provider=reader,
        url_guard=ReaderURLGuard(resolver=lambda _host: ("93.184.216.34",)),
        search_provider_name="coding-plan-search",
        ai_completion_provider=ai_completer,
    )


def test_code_enforces_four_search_eight_reader_and_two_retry_caps(book_and_jobs) -> None:
    book, job, _ = book_and_jobs
    repository = FakeRepository(book, (job,))
    search = FakeSearch(hits_per_query=3)
    reader = FakeReader()

    result = make_service(repository, search, reader).run(job.id)

    assert result.search_calls == 4
    assert result.reader_calls == 8
    assert result.retry_count == 0
    assert search.calls == 4
    assert reader.calls == 8
    assert len(repository.queries[job.id]) == 4


def test_search_retry_at_fourth_attempt_cannot_exceed_search_cap(book_and_jobs) -> None:
    book, job, _ = book_and_jobs
    repository = FakeRepository(book, (job,))
    search = BoundarySearch()

    result = make_service(repository, search, FakeReader(), FixedPlanner(count=4)).run(
        job.id
    )

    assert search.calls == result.search_calls == 4
    assert result.retry_count == 0


def test_reader_retry_at_eighth_attempt_cannot_exceed_reader_cap(book_and_jobs) -> None:
    book, job, _ = book_and_jobs
    repository = FakeRepository(book, (job,))
    reader = FailEighthReader()

    result = make_service(
        repository, FakeSearch(hits_per_query=8), reader, FixedPlanner(count=1)
    ).run(job.id)

    assert reader.calls == result.reader_calls == 8
    assert result.retry_count == 0
    assert result.search_calls + result.reader_calls <= 12


def test_same_book_and_provider_version_reuses_search_and_reader_cache(
    book_and_jobs,
) -> None:
    book, first_job, _ = book_and_jobs
    repository = FakeRepository(book, (first_job,))
    search = FakeSearch(hits_per_query=1)
    reader = FakeReader()
    service = make_service(repository, search, reader, FixedPlanner(count=4))

    first = service.run(first_job.id)
    search_calls = search.calls
    reader_calls = reader.calls
    second = service.run(first_job.id)

    assert first.status == "ready"
    assert second.status == first.status
    assert second.search_calls == 0
    assert second.reader_calls == 0
    assert second.cache_hits == first.search_calls
    assert search.calls == search_calls
    assert reader.calls == reader_calls


def test_same_domain_pages_are_not_counted_as_independent_sources(book_and_jobs) -> None:
    book, job, _ = book_and_jobs
    repository = FakeRepository(book, (job,))

    result = make_service(
        repository,
        SameDomainSearch(hits_per_query=3),
        FakeReader(),
        FixedPlanner(count=1),
    ).run(job.id)

    assert result.source_count == 3
    assert result.independent_source_count == 1
    assert result.status == "insufficient"


def test_ai_completion_creates_explicitly_labeled_source_when_original_is_missing(
    book_and_jobs,
) -> None:
    book, job, _ = book_and_jobs
    repository = FakeRepository(book, (job,))
    completer = FakeAICompleter()

    result = make_service(
        repository,
        SameDomainSearch(hits_per_query=3),
        FakeReader(fail_suffix="/book/0"),
        FixedPlanner(count=1),
        ai_completer=completer,
    ).run(job.id)

    assert result.status == "ready"
    assert result.ai_completed is True
    assert len(completer.calls) == 1
    assert any(
        failure.reason_code == "reader_provider_failed"
        for failure in result.failures
    )
    generated = next(
        source for source in result.sources if source.source_type == "ai_generated"
    )
    assert generated.canonical_url.startswith("shidu-ai://completion/")
    assert generated.content.startswith("【AI补全内容·非原文】")
    assert generated.search_hit_id is None


def test_ai_completion_can_proceed_from_book_identity_when_search_finds_nothing(
    book_and_jobs,
) -> None:
    book, job, _ = book_and_jobs
    repository = FakeRepository(book, (job,))
    completer = FakeAICompleter()

    result = make_service(
        repository,
        FakeSearch(hits_per_query=0),
        FakeReader(),
        FixedPlanner(count=1),
        ai_completer=completer,
    ).run(job.id)

    assert result.status == "ready"
    assert result.ai_completed is True
    assert completer.calls[0][1] == ()


def test_ai_completion_can_proceed_when_discovered_pages_cannot_be_read(
    book_and_jobs,
) -> None:
    book, job, _ = book_and_jobs
    repository = FakeRepository(book, (job,))
    completer = FakeAICompleter()

    result = make_service(
        repository,
        FakeSearch(hits_per_query=1),
        FakeReader(fail_suffix="/book"),
        FixedPlanner(count=1),
        ai_completer=completer,
    ).run(job.id)

    assert result.status == "ready"
    assert result.ai_completed is True
    assert len(completer.calls) == 1
    assert completer.calls[0][1] == ()
    assert result.failures[0].reason_code == "reader_provider_failed"


def test_provider_outage_does_not_masquerade_as_missing_original(
    book_and_jobs,
) -> None:
    book, job, _ = book_and_jobs
    repository = FakeRepository(book, (job,))
    completer = FakeAICompleter()

    result = make_service(
        repository,
        BoundarySearch(),
        FakeReader(),
        FixedPlanner(count=4),
        ai_completer=completer,
    ).run(job.id)

    assert result.status == "retryable_failed"
    assert result.ai_completed is False
    assert completer.calls == []


def test_registered_domain_collapses_sibling_subdomains_and_www() -> None:
    assert registrable_site_key("example.com") == "example.com"
    assert registrable_site_key("www.example.com") == "example.com"
    assert registrable_site_key("reviews.example.com") == "example.com"
    assert registrable_site_key("a.example.co.uk") == "example.co.uk"


def test_reader_candidates_are_diversified_before_eight_target_cap(book_and_jobs) -> None:
    book, job, _ = book_and_jobs
    repository = FakeRepository(book, (job,))
    reader = FakeReader()

    result = make_service(
        repository, DiversifyingSearch(), reader, FixedPlanner(count=1)
    ).run(job.id)

    requested_hosts = {request.url.split("/")[2] for request in reader.requests}
    assert reader.calls == 8
    assert "later-independent.net" in requested_hosts
    assert "reviews.independent.org" in requested_hosts
    assert result.independent_source_count == 3


def test_snippets_never_become_evidence_facts(book_and_jobs) -> None:
    book, job, _ = book_and_jobs
    repository = FakeRepository(book, (job,))

    result = make_service(
        repository, FakeSearch(hits_per_query=2), FakeReader(), FixedPlanner(count=1)
    ).run(job.id)

    assert result.evidence_facts == ()
    assert all("untrusted snippet fact" not in source.content for source in result.sources)
    stored_hit_ids = {
        hit.id for hits in repository.hits.values() for hit in hits
    }
    assert all(source.search_hit_id in stored_hit_ids for source in result.sources)
    assert all(source.source_type == "web" for source in result.sources)
    assert all(
        source.source_classification_version == "shidu-source-type-v2"
        for source in result.sources
    )
    hits_by_id = {
        hit.id: hit for hits in repository.hits.values() for hit in hits
    }
    assert all(
        source.canonical_url == hits_by_id[source.search_hit_id].canonical_url
        and source.source_type == hits_by_id[source.search_hit_id].source_type
        for source in result.sources
    )


def test_reader_failures_use_only_two_retries_are_sanitized_and_excluded(
    book_and_jobs,
) -> None:
    book, job, _ = book_and_jobs
    repository = FakeRepository(book, (job,))
    search = SameDomainSearch(hits_per_query=1)
    reader = FakeReader(fail_suffix="/0")

    result = make_service(repository, search, reader, FixedPlanner(count=1)).run(job.id)

    assert reader.calls == 3
    assert result.reader_calls == 3
    assert result.retry_count == 2
    assert result.source_count == 0
    assert result.independent_source_count == 0
    assert len(result.failures) == 1
    assert len(repository.failures[job.id]) == 1
    assert result.failures[0].reason_code == "reader_provider_failed"
    assert "secret-token" not in result.failures[0].reason_code
    assert len(result.failures[0].reason_code) <= 80


def test_content_digest_and_near_duplicate_documents_are_collapsed(book_and_jobs) -> None:
    book, job, _ = book_and_jobs
    repository = FakeRepository(book, (job,))

    result = make_service(
        repository,
        FakeSearch(hits_per_query=2),
        NearDuplicateReader(),
        FixedPlanner(count=1),
    ).run(job.id)

    assert result.reader_calls == 2
    assert result.source_count == 1
    assert len({source.content_digest for source in result.sources}) == 1


def test_near_megabyte_deduplication_is_bounded_and_deterministic(book_and_jobs) -> None:
    book, job, _ = book_and_jobs
    repository = FakeRepository(book, (job,))
    started = perf_counter()

    result = make_service(
        repository,
        FakeSearch(hits_per_query=2),
        LargeNearDuplicateReader(),
        FixedPlanner(count=1),
    ).run(job.id)

    assert result.source_count == 1
    assert perf_counter() - started < 2.0


def test_insecure_reader_capability_is_rejected_before_any_fetch(book_and_jobs) -> None:
    book, job, _ = book_and_jobs
    insecure = InsecureReader()

    with pytest.raises(InsecureReaderProvider):
        make_service(FakeRepository(book, (job,)), FakeSearch(), insecure)

    assert insecure.calls == 0


@pytest.mark.parametrize("redirect", [False, True])
def test_reader_security_attestation_mismatch_is_excluded(book_and_jobs, redirect) -> None:
    book, job, _ = book_and_jobs
    repository = FakeRepository(book, (job,))

    result = make_service(
        repository,
        FakeSearch(hits_per_query=1),
        AttestationMismatchReader(redirect=redirect),
        FixedPlanner(count=1),
    ).run(job.id)

    assert result.source_count == 0
    assert result.failures[0].reason_code == "reader_security_mismatch"


@pytest.mark.parametrize("redirect", [False, True])
def test_reader_security_attestation_mismatch_blocks_ai_completion(
    book_and_jobs,
    redirect,
) -> None:
    book, job, _ = book_and_jobs
    repository = FakeRepository(book, (job,))
    completer = FakeAICompleter()

    result = make_service(
        repository,
        FakeSearch(hits_per_query=1),
        AttestationMismatchReader(redirect=redirect),
        FixedPlanner(count=1),
        ai_completer=completer,
    ).run(job.id)

    assert result.status == "retryable_failed"
    assert result.ai_completed is False
    assert completer.calls == []
    assert result.source_count == 0
    assert result.failures[0].reason_code == "reader_security_mismatch"


def test_invalid_research_state_fails_closed_without_provider_calls(
    book_and_jobs,
) -> None:
    book, job, _ = book_and_jobs
    job = replace(job, status="searching")
    repository = FakeRepository(book, (job,))
    search = FakeSearch()
    reader = FakeReader()

    with pytest.raises(InvalidResearchState):
        make_service(repository, search, reader).run(job.id)

    assert search.calls == 0
    assert reader.calls == 0


def test_planner_cannot_select_provider_or_tool() -> None:
    planner = QueryPlanner(
        lambda _book: {
            "queries": ["valid query"],
            "evidence_gaps": [],
            "tool": "attacker.selected.tool",
        }
    )

    with pytest.raises(QueryPlanError):
        planner.plan(object())


@pytest.mark.parametrize(
    "url",
    [
        "https://www.gutenberg.org/ebooks/6811",
        "https://archive.org/details/lincoln-biography",
        "https://www.wikipedia.org/wiki/Abraham_Lincoln",
    ],
)
def test_public_archives_are_classified_as_reference_sources(url: str) -> None:
    from creative_hub.shidu.research_service import classify_source_type

    assert classify_source_type(url) == "reference"


@pytest.mark.parametrize(
    "url",
    [
        "https://gutenberg.attacker.example/ebooks/6811",
        "https://lincoln-archive.example/details/biography",
        "https://city.library.example/books/lincoln",
        "https://trusted-review.example/lincoln",
    ],
)
def test_source_type_tokens_cannot_forge_diversity(url: str) -> None:
    from creative_hub.shidu.research_service import classify_source_type

    assert classify_source_type(url) == "web"


def test_repository_persists_status_queries_hits_and_append_only_failures() -> None:
    engine = create_engine(
        "sqlite+pysqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    from sqlalchemy import event

    @event.listens_for(engine, "connect")
    def attach(connection, _record) -> None:
        connection.execute("ATTACH DATABASE ':memory:' AS orchestration")
        connection.execute("PRAGMA foreign_keys = ON")

    OrchestrationBase.metadata.create_all(engine)
    project_id = uuid4()
    with Session(engine, expire_on_commit=False) as session:
        session.add(
            ProjectRecord(
                id=project_id,
                project_key="task-5-repository",
                title="Task 5",
                config={},
                config_digest="0" * 64,
            )
        )
        session.flush()
        repository = ShiduRepository(session)
        book = repository.create_or_reuse_book(
            CreateBook(
                project_id=project_id,
                title="The Book",
                author="The Author",
                language="en",
                edition="",
                translator="",
                command_key="book:task-5",
            )
        ).value
        job = repository.create_or_reuse_research_job(
            CreateResearchJob(
                project_id=project_id,
                book_id=book.id,
                provider_version="coding-plan-v1",
                command_key="research:task-5",
            )
        ).value

        resolving = repository.transition_research_job(job.id, "queued", "resolving")
        query = repository.append_search_query(
            CreateSearchQuery(
                project_id=project_id,
                research_job_id=job.id,
                ordinal=1,
                query="book reception",
                provider="coding-plan-search",
                provider_version="coding-plan-v1",
                command_key="query:task-5:1",
            )
        )
        hit = repository.append_search_hit(
            CreateSearchHit(
                project_id=project_id,
                search_query_id=query.id,
                ordinal=1,
                canonical_url="https://example.com/book",
                title="Review",
                snippet="not evidence",
                source_type="media",
            )
        )
        failure = repository.append_source_failure(
            StoreSourceFailure(
                project_id=project_id,
                research_job_id=job.id,
                stage="reader",
                canonical_url="https://example.com/book",
                reason_code="reader_provider_failed",
                attempts=3,
                command_key="failure:task-5:1",
            )
        )

        assert resolving.status == "resolving"
        assert repository.get_book(project_id, book.id) == book
        assert repository.list_search_queries(job.id) == (query,)
        assert repository.list_search_hits(job.id) == (hit,)
        assert repository.list_source_failures(job.id) == (failure,)
        with pytest.raises(InvalidResearchJobTransition):
            repository.transition_research_job(job.id, "resolving", "ready")
    engine.dispose()


def test_repository_preserves_failed_attempt_and_reuses_active_then_ready_attempt() -> None:
    engine = create_engine(
        "sqlite+pysqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    from sqlalchemy import event

    @event.listens_for(engine, "connect")
    def attach(connection, _record) -> None:
        connection.execute("ATTACH DATABASE ':memory:' AS orchestration")
        connection.execute("PRAGMA foreign_keys = ON")

    OrchestrationBase.metadata.create_all(engine)
    project_id = uuid4()
    with Session(engine, expire_on_commit=False) as session:
        session.add(
            ProjectRecord(
                id=project_id,
                project_key="task-5-retry-cache",
                title="Task 5 retry cache",
                config={},
                config_digest="0" * 64,
            )
        )
        session.flush()
        repository = ShiduRepository(session)
        book = repository.create_or_reuse_book(
            CreateBook(
                project_id=project_id,
                title="Retry Book",
                author="Author",
                language="en",
                edition="",
                translator="",
                command_key="book:retry-cache",
            )
        ).value

        def create(command_key: str):
            return repository.create_or_reuse_research_job(
                CreateResearchJob(
                    project_id=project_id,
                    book_id=book.id,
                    provider_version="coding-plan-v1",
                    command_key=command_key,
                )
            )

        failed = create("research:failed")
        resolving = repository.transition_research_job(
            failed.value.id, "queued", "resolving"
        )
        repository.transition_research_job(resolving.id, "resolving", "failed")
        replacement = create("research:replacement")
        coalesced = create("research:coalesced")

        assert replacement.created is True
        assert replacement.value.id != failed.value.id
        assert coalesced.created is False
        assert coalesced.value.id == replacement.value.id
        assert repository.get_research_job(failed.value.id).status == "failed"

        current = replacement.value
        for state in (
            "resolving",
            "searching",
            "reading",
            "extracting",
            "synthesizing",
            "ready",
        ):
            current = repository.transition_research_job(current.id, current.status, state)
        cached = create("research:cache")
        assert cached.created is False
        assert cached.value.id == replacement.value.id

        service = make_service(repository, FakeSearch(), FakeReader())
        result = service.run(cached.value.id)
        assert result.status == "ready"
        assert result.search_calls == result.reader_calls == 0
    engine.dispose()


def test_research_job_semantic_constraint_removed_and_source_failure_defaults_match() -> None:
    research_table = OrchestrationBase.metadata.tables["orchestration.research_jobs"]
    assert all(
        constraint.name != "uq_orch_research_jobs_semantic"
        for constraint in research_table.constraints
    )
    failure_table = OrchestrationBase.metadata.tables["orchestration.source_failures"]
    assert failure_table.c.canonical_url.server_default is not None
    assert failure_table.c.attempts.server_default is not None
