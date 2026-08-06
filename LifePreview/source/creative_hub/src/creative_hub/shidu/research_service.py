"""Bounded Search/Reader orchestration for a Shidu ResearchJob."""

from __future__ import annotations

import hashlib
import heapq
import re
from collections import deque
from dataclasses import dataclass
from typing import Any, Protocol, TypeVar
from urllib.parse import urlsplit
from uuid import UUID

from creative_hub.shidu.providers import (
    PageReaderProvider,
    ReadPageRequest,
    ReaderSecurityCapabilities,
    SearchHit as ProviderSearchHit,
    SearchProvider,
    SearchRequest,
    SourceDocumentPayload,
)
from creative_hub.shidu.query_planner import QueryPlanError
from creative_hub.shidu.schemas import (
    Book,
    CreateSearchHit,
    CreateSearchQuery,
    ResearchJob,
    SearchQuery,
    SourceDocumentRevision,
    SourceFailure,
    StoreSourceDocument,
    StoreSourceFailure,
)
from creative_hub.shidu.url_security import (
    ReaderURLGuard,
    ReaderURLIdentity,
    UnsafeSourceURL,
)


MAX_QUERY_CALLS = 4
MAX_READER_CALLS = 8
MAX_RETRIES = 2
MAX_TOTAL_PROVIDER_CALLS = MAX_QUERY_CALLS + MAX_READER_CALLS
SOURCE_CLASSIFICATION_VERSION = "shidu-source-type-v2"
AI_COMPLETION_CLASSIFICATION_VERSION = "shidu-ai-completion-v1"
AI_COMPLETION_NOTICE = "【AI补全内容·非原文】"
_ORIGINAL_TEXT_SITES = frozenset({"archive.org", "gutenberg.org"})
_REFERENCE_SITES = frozenset(
    {
        "archive.org",
        "britannica.com",
        "gutenberg.org",
        "loc.gov",
        "wikipedia.org",
        "worldcat.org",
    }
)
_PUBLISHER_SITES = frozenset(
    {
        "harpercollins.com",
        "macmillan.com",
        "penguinrandomhouse.com",
        "simonandschuster.com",
    }
)
_MEDIA_SITES = frozenset(
    {
        "bookpage.com",
        "kirkusreviews.com",
        "nytimes.com",
        "publishersweekly.com",
        "theguardian.com",
    }
)


class ResearchServiceError(RuntimeError):
    pass


class InvalidResearchState(ResearchServiceError):
    pass


class InsecureReaderProvider(ResearchServiceError):
    pass


class _ReaderSecurityMismatch(ResearchServiceError):
    pass


class QueryPlannerProtocol(Protocol):
    def plan(self, book: Book): ...


@dataclass(frozen=True, slots=True)
class AICompletedContent:
    content: str
    model_id: str


class AICompletionProvider(Protocol):
    model_id: str

    def complete(
        self,
        *,
        book: Book,
        sources: tuple[SourceDocumentRevision, ...],
    ) -> AICompletedContent: ...


class ResearchRepository(Protocol):
    def get_research_job(self, job_id: UUID) -> ResearchJob: ...

    def get_book(self, project_id: UUID, book_id: UUID) -> Book: ...

    def transition_research_job(
        self, job_id: UUID, expected_status: str, new_status: str
    ) -> ResearchJob: ...


@dataclass(frozen=True)
class ResearchJobResult:
    job_id: UUID
    status: str
    queries: tuple[SearchQuery, ...]
    sources: tuple[SourceDocumentRevision, ...]
    failures: tuple[SourceFailure, ...]
    evidence_facts: tuple[object, ...]
    search_calls: int
    reader_calls: int
    retry_count: int
    cache_hits: int
    independent_source_count: int
    ai_completed: bool = False

    @property
    def source_count(self) -> int:
        return len(self.sources)


@dataclass
class _RuntimeBudget:
    retries_remaining: int
    search_limit: int
    reader_limit: int
    total_limit: int
    search_calls: int = 0
    reader_calls: int = 0
    retry_count: int = 0


class _ProviderFailure(RuntimeError):
    def __init__(self, stage: str, attempts: int) -> None:
        super().__init__(f"{stage} provider failed")
        self.stage = stage
        self.attempts = attempts


T = TypeVar("T")


_TRANSITIONS: dict[str, frozenset[str]] = {
    "queued": frozenset({"resolving"}),
    "resolving": frozenset({"searching", "failed"}),
    "searching": frozenset({"reading", "failed"}),
    "reading": frozenset({"extracting", "failed"}),
    "extracting": frozenset({"synthesizing", "failed"}),
    "synthesizing": frozenset(
        {"ready", "insufficient", "retryable_failed", "failed"}
    ),
    "ready": frozenset(),
    "insufficient": frozenset(),
    "retryable_failed": frozenset(),
    "failed": frozenset(),
}

_MULTI_LABEL_PUBLIC_SUFFIXES = frozenset(
    {
        "co.jp",
        "co.kr",
        "co.uk",
        "com.au",
        "com.br",
        "com.cn",
        "com.hk",
        "com.sg",
        "net.au",
        "net.cn",
        "org.au",
        "org.cn",
        "org.uk",
    }
)
_WORD = re.compile(r"[^\W_]+", re.UNICODE)
_SIGNATURE_SHINGLE_WORDS = 5
_SIGNATURE_SIZE = 128


@dataclass(frozen=True)
class _ContentFingerprint:
    digest: str
    length: int
    signature: frozenset[int]


@dataclass(frozen=True)
class _ReaderCandidate:
    canonical_url: str
    identity: ReaderURLIdentity
    source_type: str
    site_key: str
    search_hit_id: UUID


def _normalise_content(content: str) -> str:
    return re.sub(r"\s+", " ", content).strip()


def _content_digest(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _content_signature(content: str) -> frozenset[int]:
    """Bottom-k word-shingle signature with fixed memory and linear time."""

    window: deque[str] = deque(maxlen=_SIGNATURE_SHINGLE_WORDS)
    retained: set[int] = set()
    maximum_heap: list[int] = []
    for match in _WORD.finditer(content):
        window.append(match.group(0).casefold()[:64])
        if len(window) < _SIGNATURE_SHINGLE_WORDS:
            continue
        value = int.from_bytes(
            hashlib.blake2b(
                "\x1f".join(window).encode("utf-8"), digest_size=8
            ).digest(),
            "big",
        )
        if value in retained:
            continue
        if len(maximum_heap) < _SIGNATURE_SIZE:
            heapq.heappush(maximum_heap, -value)
            retained.add(value)
            continue
        current_maximum = -maximum_heap[0]
        if value < current_maximum:
            removed = -heapq.heapreplace(maximum_heap, -value)
            retained.remove(removed)
            retained.add(value)
    if retained:
        return frozenset(retained)
    fallback = hashlib.blake2b(
        content.casefold()[:4_096].encode("utf-8"), digest_size=8
    ).digest()
    return frozenset({int.from_bytes(fallback, "big")})


def _fingerprint(content: str, digest: str) -> _ContentFingerprint:
    return _ContentFingerprint(
        digest=digest,
        length=len(content),
        signature=_content_signature(content),
    )


def _is_near_duplicate(
    left: _ContentFingerprint, right: _ContentFingerprint
) -> bool:
    if left.digest == right.digest:
        return True
    if left.length == 0 or right.length == 0:
        return False
    shorter, longer = sorted((left.length, right.length))
    if shorter / longer < 0.85:
        return False
    union = left.signature | right.signature
    if not union:
        return False
    return len(left.signature & right.signature) / len(union) >= 0.85


def registrable_site_key(host: str) -> str:
    """Conservative deterministic site key without a runtime PSL dependency."""

    labels = tuple(label for label in host.lower().rstrip(".").split(".") if label)
    if len(labels) <= 2:
        return ".".join(labels)
    public_suffix = ".".join(labels[-2:])
    if public_suffix in _MULTI_LABEL_PUBLIC_SUFFIXES and len(labels) >= 3:
        return ".".join(labels[-3:])
    # Unknown suffix structures deliberately over-collapse to the last two
    # labels, which is fail-closed for independence/coverage calculations.
    return public_suffix


def classify_source_type(canonical_url: str) -> str:
    host = (urlsplit(canonical_url).hostname or "").lower()
    site = registrable_site_key(host)
    if host.endswith(".edu") or host in {"doi.org", "www.doi.org"}:
        return "academic"
    if site in _REFERENCE_SITES:
        return "reference"
    if site in _PUBLISHER_SITES:
        return "publisher"
    if site in _MEDIA_SITES:
        return "media"
    return "web"


class ResearchService:
    def __init__(
        self,
        *,
        repository: ResearchRepository,
        planner: QueryPlannerProtocol,
        search_provider: SearchProvider,
        reader_provider: PageReaderProvider,
        url_guard: ReaderURLGuard,
        search_provider_name: str = "coding-plan-search",
        minimum_independent_sources: int = 2,
        ai_completion_provider: AICompletionProvider | None = None,
    ) -> None:
        if not search_provider_name or len(search_provider_name) > 100:
            raise ValueError("search_provider_name is invalid")
        if minimum_independent_sources < 1:
            raise ValueError("minimum_independent_sources must be positive")
        capabilities = getattr(reader_provider, "security_capabilities", None)
        if capabilities != ReaderSecurityCapabilities.secure_default():
            raise InsecureReaderProvider(
                "reader provider lacks the required address-binding contract"
            )
        self._repository = repository
        self._planner = planner
        # Provider selection is constructor-owned application configuration. A
        # planner has no field or callback through which it can replace tools.
        self._search_provider = search_provider
        self._reader_provider = reader_provider
        self._url_guard = url_guard
        self._search_provider_name = search_provider_name
        self._minimum_independent_sources = minimum_independent_sources
        self._ai_completion_provider = ai_completion_provider

    def run(self, job_id: UUID) -> ResearchJobResult:
        job = self._repository.get_research_job(job_id)
        if job.status in {"ready", "insufficient"}:
            return self._persisted_result(job, cache_hits=True)
        if job.status != "queued":
            raise InvalidResearchState(
                "research job must be queued or in a completed cache state"
            )

        search_limit = min(job.query_budget, MAX_QUERY_CALLS)
        reader_limit = min(job.reader_budget, MAX_READER_CALLS)
        budget = _RuntimeBudget(
            retries_remaining=min(job.retry_budget, MAX_RETRIES),
            search_limit=search_limit,
            reader_limit=reader_limit,
            total_limit=min(
                search_limit + reader_limit, MAX_TOTAL_PROVIDER_CALLS
            ),
        )
        job = self._transition(job, "resolving")
        book = self._repository.get_book(job.project_id, job.book_id)

        try:
            plan = self._planner.plan(book)
        except QueryPlanError:
            self._transition(job, "failed")
            raise
        except Exception as error:
            self._transition(job, "failed")
            raise ResearchServiceError("query planner failed") from error

        raw_queries = tuple(getattr(plan, "queries", ()))
        query_limit = budget.search_limit
        planned_queries = raw_queries[:query_limit]
        if any(not isinstance(query, str) or not query.strip() for query in planned_queries):
            self._transition(job, "failed")
            raise QueryPlanError("planner returned invalid queries")

        job = self._transition(job, "searching")
        candidates: list[_ReaderCandidate] = []
        seen_urls: set[str] = set()
        failures: list[SourceFailure] = []
        queries: list[SearchQuery] = []

        for ordinal, query_text in enumerate(planned_queries, start=1):
            stored_query = self._repository.append_search_query(
                CreateSearchQuery(
                    project_id=job.project_id,
                    research_job_id=job.id,
                    ordinal=ordinal,
                    query=query_text.strip(),
                    provider=self._search_provider_name,
                    provider_version=job.provider_version,
                    command_key=f"research:{job.id}:query:{ordinal}",
                )
            )
            queries.append(stored_query)
            try:
                hits, _attempts = self._invoke(
                    "search",
                    budget,
                    lambda query=query_text: self._validated_search(query),
                )
            except _ProviderFailure as failure:
                failures.append(
                    self._record_failure(
                        job,
                        stage="search",
                        canonical_url="",
                        reason_code="search_provider_failed",
                        attempts=failure.attempts,
                        ordinal=len(failures) + 1,
                    )
                )
                continue

            hit_ordinal = 0
            for hit in hits:
                try:
                    identity = self._url_guard.validate(hit.url)
                except UnsafeSourceURL:
                    failures.append(
                        self._record_failure(
                            job,
                            stage="url_guard",
                            canonical_url="",
                            reason_code="unsafe_source_url",
                            attempts=0,
                            ordinal=len(failures) + 1,
                        )
                    )
                    continue
                if identity.canonical_url in seen_urls:
                    continue
                seen_urls.add(identity.canonical_url)
                hit_ordinal += 1
                source_type = classify_source_type(identity.canonical_url)
                stored_hit = self._repository.append_search_hit(
                    CreateSearchHit(
                        project_id=job.project_id,
                        search_query_id=stored_query.id,
                        ordinal=hit_ordinal,
                        canonical_url=identity.canonical_url,
                        title=hit.title,
                        snippet=hit.snippet,
                        source_type=source_type,
                    )
                )
                candidates.append(
                    _ReaderCandidate(
                        canonical_url=identity.canonical_url,
                        identity=identity,
                        source_type=source_type,
                        site_key=registrable_site_key(identity.host),
                        search_hit_id=stored_hit.id,
                    )
                )

        job = self._transition(job, "reading")
        sources: list[SourceDocumentRevision] = []
        content_digests: set[str] = set()
        fingerprints: list[_ContentFingerprint] = []
        selected_candidates = self._diversify_candidates(
            candidates, budget.reader_limit
        )
        for ordinal, candidate in enumerate(selected_candidates, start=1):
            canonical_url = candidate.canonical_url
            # Validate again immediately before each call. No URL discovered by
            # Search reaches the Reader without this guard.
            try:
                fetch_identity = self._url_guard.validate(canonical_url)
            except UnsafeSourceURL:
                failures.append(
                    self._record_failure(
                        job,
                        stage="url_guard",
                        canonical_url="",
                        reason_code="unsafe_source_url",
                        attempts=0,
                        ordinal=len(failures) + 1,
                    )
                )
                continue
            try:
                document, attempts = self._invoke(
                    "reader",
                    budget,
                    lambda identity=fetch_identity: self._validated_read(identity),
                )
            except _ReaderSecurityMismatch:
                failures.append(
                    self._record_failure(
                        job,
                        stage="reader",
                        canonical_url=canonical_url,
                        reason_code="reader_security_mismatch",
                        attempts=1,
                        ordinal=len(failures) + 1,
                    )
                )
                continue
            except _ProviderFailure as failure:
                failures.append(
                    self._record_failure(
                        job,
                        stage="reader",
                        canonical_url=canonical_url,
                        reason_code="reader_provider_failed",
                        attempts=failure.attempts,
                        ordinal=len(failures) + 1,
                    )
                )
                continue

            content = _normalise_content(document.content)
            if not content:
                failures.append(
                    self._record_failure(
                        job,
                        stage="reader",
                        canonical_url=fetch_identity.canonical_url,
                        reason_code="empty_reader_document",
                        attempts=attempts,
                        ordinal=len(failures) + 1,
                    )
                )
                continue
            digest = _content_digest(content)
            if digest in content_digests:
                continue
            fingerprint = _fingerprint(content, digest)
            if any(_is_near_duplicate(fingerprint, existing) for existing in fingerprints):
                continue
            content_digests.add(digest)
            fingerprints.append(fingerprint)
            source = self._repository.store_source_revision(
                StoreSourceDocument(
                    project_id=job.project_id,
                    research_job_id=job.id,
                    canonical_url=fetch_identity.canonical_url,
                    content=content,
                    command_key=f"research:{job.id}:source:{digest}",
                    source_type=candidate.source_type,
                    source_classification_version=SOURCE_CLASSIFICATION_VERSION,
                    search_hit_id=candidate.search_hit_id,
                )
            )
            sources.append(source)

        job = self._transition(job, "extracting")
        # Extraction/synthesis receives Reader documents only. Search snippets
        # are intentionally absent and can never become evidence facts here.
        job = self._transition(job, "synthesizing")
        independent_count = self._independent_source_count(tuple(sources))
        # A Reader failure can mean a particular page rejected or could not be
        # projected, while Search still proved that the lookup itself worked.
        # In that case the explicit AI fallback may proceed from book identity.
        # A Search provider outage is systemic and must remain retryable instead.
        systemic_provider_failure = any(
            failure.stage == "search"
            and failure.reason_code.endswith("provider_failed")
            for failure in failures
        ) and not sources
        reader_security_failed = any(
            failure.reason_code == "reader_security_mismatch"
            for failure in failures
        )
        original_text_available = any(
            registrable_site_key(source.registered_domain)
            in _ORIGINAL_TEXT_SITES
            for source in sources
        )
        ai_completed = False
        ai_completion_failed = False
        if (
            not original_text_available
            and independent_count < self._minimum_independent_sources
            and not systemic_provider_failure
            and not reader_security_failed
            and self._ai_completion_provider is not None
        ):
            try:
                completed = self._ai_completion_provider.complete(
                    book=book,
                    sources=tuple(sources),
                )
                if (
                    not isinstance(completed, AICompletedContent)
                    or completed.model_id
                    != self._ai_completion_provider.model_id
                ):
                    raise ResearchServiceError(
                        "AI completion provider returned an invalid payload"
                    )
                body = _normalise_content(completed.content)
                if not 40 <= len(body) <= 12_000:
                    raise ResearchServiceError(
                        "AI completion provider returned invalid content"
                    )
                content = f"{AI_COMPLETION_NOTICE}\n{body}"
                digest = _content_digest(content)
                generated = self._repository.store_source_revision(
                    StoreSourceDocument(
                        project_id=job.project_id,
                        research_job_id=job.id,
                        canonical_url=(
                            "shidu-ai://completion/"
                            f"{job.id}/{digest}"
                        ),
                        content=content,
                        command_key=(
                            f"research:{job.id}:ai-completion:{digest}"
                        ),
                        source_type="ai_generated",
                        source_classification_version=(
                            AI_COMPLETION_CLASSIFICATION_VERSION
                        ),
                        search_hit_id=None,
                    )
                )
                sources.append(generated)
                independent_count = self._independent_source_count(
                    tuple(sources)
                )
                ai_completed = True
            except Exception:
                ai_completion_failed = True
        if reader_security_failed:
            final_status = "retryable_failed"
        elif ai_completion_failed and independent_count < self._minimum_independent_sources:
            final_status = "retryable_failed"
        elif systemic_provider_failure:
            final_status = "retryable_failed"
        elif ai_completed or independent_count >= self._minimum_independent_sources:
            final_status = "ready"
        else:
            final_status = "insufficient"
        job = self._transition(job, final_status)
        return ResearchJobResult(
            job_id=job.id,
            status=job.status,
            queries=tuple(queries),
            sources=tuple(sources),
            failures=tuple(failures),
            evidence_facts=(),
            search_calls=budget.search_calls,
            reader_calls=budget.reader_calls,
            retry_count=budget.retry_count,
            cache_hits=0,
            independent_source_count=independent_count,
            ai_completed=ai_completed,
        )

    def _validated_search(self, query: str) -> tuple[ProviderSearchHit, ...]:
        hits = self._search_provider.search(SearchRequest(query=query, max_results=20))
        if not isinstance(hits, tuple) or any(
            not isinstance(hit, ProviderSearchHit) for hit in hits
        ):
            raise ResearchServiceError("search provider returned an invalid payload")
        return hits

    def _validated_read(self, identity: ReaderURLIdentity) -> SourceDocumentPayload:
        request = ReadPageRequest(
            url=identity.canonical_url,
            approved_resolved_addresses=tuple(sorted(identity.approved_addresses)),
            redirect_policy="forbid",
            prefetch_policy="connect-approved-address-only",
        )
        document = self._reader_provider.read(request)
        if not isinstance(document, SourceDocumentPayload):
            raise ResearchServiceError("reader provider returned an invalid payload")
        if (
            document.url != request.url
            or document.security.resolved_address
            not in request.approved_resolved_addresses
            or document.security.redirect_chain != (request.url,)
            or document.security.redirect_policy != request.redirect_policy
            or document.security.prefetch_policy != request.prefetch_policy
        ):
            raise _ReaderSecurityMismatch("reader security attestation mismatch")
        return document

    @staticmethod
    def _invoke(stage: str, budget: _RuntimeBudget, operation) -> tuple[T, int]:
        attempts = 0
        while True:
            stage_calls = (
                budget.search_calls if stage == "search" else budget.reader_calls
            )
            stage_limit = (
                budget.search_limit if stage == "search" else budget.reader_limit
            )
            if (
                stage_calls >= stage_limit
                or budget.search_calls + budget.reader_calls >= budget.total_limit
            ):
                raise _ProviderFailure(stage, attempts)
            attempts += 1
            if stage == "search":
                budget.search_calls += 1
            else:
                budget.reader_calls += 1
            try:
                return operation(), attempts
            except _ReaderSecurityMismatch:
                raise
            except Exception as error:
                stage_calls = (
                    budget.search_calls
                    if stage == "search"
                    else budget.reader_calls
                )
                if (
                    budget.retries_remaining <= 0
                    or stage_calls >= stage_limit
                    or budget.search_calls + budget.reader_calls
                    >= budget.total_limit
                ):
                    raise _ProviderFailure(stage, attempts) from error
                budget.retries_remaining -= 1
                budget.retry_count += 1

    def _transition(self, job: ResearchJob, new_status: str) -> ResearchJob:
        if new_status not in _TRANSITIONS.get(job.status, frozenset()):
            raise InvalidResearchState(
                f"invalid research state transition: {job.status} -> {new_status}"
            )
        updated = self._repository.transition_research_job(
            job.id, job.status, new_status
        )
        if updated.status != new_status:
            raise InvalidResearchState("repository did not persist the requested state")
        return updated

    def _record_failure(
        self,
        job: ResearchJob,
        *,
        stage: str,
        canonical_url: str,
        reason_code: str,
        attempts: int,
        ordinal: int,
    ) -> SourceFailure:
        safe_stage = stage[:32]
        safe_reason = reason_code[:80]
        safe_url = canonical_url[:2_048]
        return self._repository.append_source_failure(
            StoreSourceFailure(
                project_id=job.project_id,
                research_job_id=job.id,
                stage=safe_stage,
                canonical_url=safe_url,
                reason_code=safe_reason,
                attempts=max(0, attempts),
                command_key=f"research:{job.id}:failure:{ordinal}",
            )
        )

    def _persisted_result(
        self, job: ResearchJob, *, cache_hits: bool
    ) -> ResearchJobResult:
        queries = tuple(self._repository.list_search_queries(job.id))
        sources = tuple(self._repository.list_source_revisions(job.id))
        failures = tuple(self._repository.list_source_failures(job.id))
        return ResearchJobResult(
            job_id=job.id,
            status=job.status,
            queries=queries,
            sources=sources,
            failures=failures,
            evidence_facts=(),
            search_calls=0,
            reader_calls=0,
            retry_count=0,
            cache_hits=len(queries) if cache_hits else 0,
            independent_source_count=self._independent_source_count(sources),
        )

    @staticmethod
    def _independent_source_count(
        sources: tuple[SourceDocumentRevision, ...]
    ) -> int:
        return len(
            {
                registrable_site_key(
                    (urlsplit(source.canonical_url).hostname or "").lower()
                )
                for source in sources
                if (
                    source.source_type != "ai_generated"
                    and urlsplit(source.canonical_url).hostname
                )
            }
        )

    @staticmethod
    def _diversify_candidates(
        candidates: list[_ReaderCandidate], limit: int
    ) -> tuple[_ReaderCandidate, ...]:
        if limit <= 0:
            return ()
        selected: list[_ReaderCandidate] = []
        selected_indexes: set[int] = set()
        seen_sites: set[str] = set()
        for index, candidate in enumerate(candidates):
            if candidate.site_key in seen_sites:
                continue
            selected.append(candidate)
            selected_indexes.add(index)
            seen_sites.add(candidate.site_key)
            if len(selected) == limit:
                return tuple(selected)
        seen_types = {candidate.source_type for candidate in selected}
        for index, candidate in enumerate(candidates):
            if index in selected_indexes or candidate.source_type in seen_types:
                continue
            selected.append(candidate)
            selected_indexes.add(index)
            seen_types.add(candidate.source_type)
            if len(selected) == limit:
                return tuple(selected)
        for index, candidate in enumerate(candidates):
            if index in selected_indexes:
                continue
            selected.append(candidate)
            if len(selected) == limit:
                break
        return tuple(selected)


__all__ = [
    "InvalidResearchState",
    "InsecureReaderProvider",
    "MAX_QUERY_CALLS",
    "MAX_READER_CALLS",
    "MAX_RETRIES",
    "MAX_TOTAL_PROVIDER_CALLS",
    "ResearchJobResult",
    "ResearchService",
    "ResearchServiceError",
    "SOURCE_CLASSIFICATION_VERSION",
    "classify_source_type",
    "registrable_site_key",
]
