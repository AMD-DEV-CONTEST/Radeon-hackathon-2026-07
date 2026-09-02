"""Transactional, append-only persistence commands for Shidu facts."""

from __future__ import annotations

import hashlib
import math
from collections import Counter
from typing import Iterable
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from creative_hub.db.canonical import canonical_json_digest
from creative_hub.db.models import (
    BookDiscoveryCandidateRecord,
    BookDiscoverySelectionRecord,
    BookMergeRecord,
    BookRecord,
    EvidenceConflictAdjudicationMembershipRecord,
    EvidenceConflictAdjudicationRevisionRecord,
    EvidenceClaimRecord,
    EvidencePackMembershipRecord,
    EvidencePackRevisionRecord,
    InputResolutionRecord,
    ProjectRecord,
    ResearchJobRecord,
    ResonanceDirectionRevisionRecord,
    SearchHitRecord,
    SearchQueryRecord,
    SourceDocumentRevisionRecord,
    SourceFailureRecord,
    TTSTakeRecord,
    TrialMethodologyRevisionRecord,
    TrialScriptRevisionRecord,
    VideoBookBindingRecord,
    VoicePresetRevisionRecord,
)
from creative_hub.shidu.book_identity import (
    normalize_book_identity,
    normalize_book_title,
)
from creative_hub.shidu.research_service import registrable_site_key
from creative_hub.shidu.schemas import (
    BindVideoToBook,
    AppendEvidenceClaim,
    Book,
    BookDiscoveryCandidate,
    BookDiscoveryResolution,
    BookMergeRecord as BookMerge,
    CreateBookDiscoveryResolution,
    CreateBook,
    CreateResearchJob,
    CreateSearchHit,
    CreateSearchQuery,
    DirectionDraft,
    EvidenceConflictAdjudicationRevision,
    EvidenceClaim,
    EvidencePackRevision,
    FreezeEvidencePack,
    FreezeTrialMethodology,
    MergeBooks,
    PublishDirections,
    RecordTTSTake,
    ResearchJob,
    ResonanceDirectionRevision,
    SearchHit,
    SearchQuery,
    SelectBookDiscoveryCandidate,
    SourceDocumentRevision,
    SourceFailure,
    StoreSourceDocument,
    StoreSourceFailure,
    StoreConflictAdjudication,
    StoreTrialScript,
    StoreVoicePresetRevision,
    Stored,
    TTSTake,
    TrialMethodologyRevision,
    TrialScriptRevision,
    VideoBookBinding,
    VoicePresetRevision,
)


class ShiduPersistenceError(RuntimeError):
    pass


class IdempotencyConflict(ShiduPersistenceError):
    pass


class InvalidResearchJobTransition(ShiduPersistenceError):
    pass


class EvidencePackNotPublishable(ShiduPersistenceError):
    pass


_RESEARCH_TRANSITIONS = {
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
_INTERACTION_NORMALIZATION_VERSION = "shidu-public-interaction-v1"
_QWEN_TTS_PROVIDER = "qwen3-tts-custom-voice-mcp"
_QWEN_TTS_MODEL = "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice"
_QWEN_TTS_TOOL = "qwen_tts.custom_voice"
_QWEN_TTS_SCHEMA = (
    "99334726611ccf58a148b0814696bfa6fe08c1b2d027e946beccf5a74331c9aa"
)
_DEFAULT_TTS_SPEAKERS = frozenset({"Serena", "Uncle_Fu"})
_GATED_TTS_SPEAKERS = frozenset({"Vivian", "Dylan"})
_TTS_SPEAKERS = _DEFAULT_TTS_SPEAKERS | _GATED_TTS_SPEAKERS
_VOICE_CLONE_TERMS = ("voice clone", "reference audio", "clone", "克隆", "参考音频")


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _require_key(value: str, label: str) -> None:
    if not value or len(value) > 255:
        raise ValueError(f"{label} must contain 1 to 255 characters")


def _require_digest(value: str, label: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")


def _normalize_interaction_metrics(
    value: dict[str, int] | None,
) -> tuple[dict[str, int] | None, float | None]:
    if value is None:
        return None, None
    allowed = {"likes", "saves", "replies"}
    if (
        not isinstance(value, dict)
        or not value
        or not set(value).issubset(allowed)
    ):
        raise ValueError("interaction_metrics are invalid")
    metrics: dict[str, int] = {}
    for name, count in value.items():
        if isinstance(count, bool) or not isinstance(count, int):
            raise ValueError("interaction_metrics are invalid")
        if count < 0 or count > 1_000_000_000_000:
            raise ValueError("interaction_metrics are invalid")
        metrics[name] = count
    ordered = dict(sorted(metrics.items()))
    # Public counts are normalized only here; neither a model nor prose can
    # supply or estimate the score. Zero remains an observed zero.
    signal = min(1.0, sum(ordered.values()) / 1000.0)
    return ordered, signal


def _adjudication_semantic_lock_key(
    project_id: UUID,
    research_job_id: UUID,
    evidence_set_digest: str,
    adjudicator_version: str,
) -> str:
    return (
        f"adjudication-semantic:{project_id}:{research_job_id}:"
        f"{evidence_set_digest}:{adjudicator_version}"
    )


class ShiduRepository:
    """Uses the caller's transaction and never commits on its behalf."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def _serialize(self, *keys: str) -> None:
        if self.session.get_bind().dialect.name != "postgresql":
            return
        for key in sorted(set(keys)):
            self.session.execute(
                text(
                    "SELECT pg_advisory_xact_lock("
                    "hashtextextended(:shidu_command_key, 0))"
                ),
                {"shidu_command_key": f"creative-hub:shidu:{key}"},
            )

    def _require_book(self, project_id: UUID, book_id: UUID) -> BookRecord:
        book = self.session.scalar(
            select(BookRecord).where(
                BookRecord.id == book_id,
                BookRecord.project_id == project_id,
            )
        )
        if book is None:
            raise ValueError("book does not belong to project")
        return book

    def _require_job(
        self, project_id: UUID, research_job_id: UUID
    ) -> ResearchJobRecord:
        job = self.session.scalar(
            select(ResearchJobRecord).where(
                ResearchJobRecord.id == research_job_id,
                ResearchJobRecord.project_id == project_id,
            )
        )
        if job is None:
            raise ValueError("research job does not belong to project")
        return job

    def _require_query(
        self, project_id: UUID, search_query_id: UUID
    ) -> SearchQueryRecord:
        query = self.session.scalar(
            select(SearchQueryRecord).where(
                SearchQueryRecord.id == search_query_id,
                SearchQueryRecord.project_id == project_id,
            )
        )
        if query is None:
            raise ValueError("search query does not belong to project")
        return query

    def get_book(self, project_id: UUID, book_id: UUID) -> Book:
        return self._book(self._require_book(project_id, book_id))

    def get_research_job(self, job_id: UUID) -> ResearchJob:
        record = self.session.get(ResearchJobRecord, job_id)
        if record is None:
            raise ValueError("research job does not exist")
        return self._research_job(record)

    def get_source_revision(
        self, source_document_revision_id: UUID
    ) -> SourceDocumentRevision:
        record = self.session.get(
            SourceDocumentRevisionRecord, source_document_revision_id
        )
        if record is None:
            raise ValueError("source document revision does not exist")
        return self._source_revision(record)

    def is_latest_source_revision(
        self, source_document_revision_id: UUID
    ) -> bool:
        record = self.session.get(
            SourceDocumentRevisionRecord, source_document_revision_id
        )
        if record is None:
            return False
        latest = self.session.scalar(
            select(func.max(SourceDocumentRevisionRecord.revision)).where(
                SourceDocumentRevisionRecord.project_id == record.project_id,
                SourceDocumentRevisionRecord.canonical_url
                == record.canonical_url,
            )
        )
        return latest == record.revision

    def transition_research_job(
        self,
        job_id: UUID,
        expected_status: str,
        new_status: str,
    ) -> ResearchJob:
        if new_status not in _RESEARCH_TRANSITIONS.get(expected_status, frozenset()):
            raise InvalidResearchJobTransition("research state transition is not allowed")
        self._serialize(f"research-state:{job_id}")
        record = self.session.scalar(
            select(ResearchJobRecord)
            .where(ResearchJobRecord.id == job_id)
            .with_for_update()
        )
        if record is None:
            raise ValueError("research job does not exist")
        if record.status != expected_status:
            raise InvalidResearchJobTransition("research state is stale")
        record.status = new_status
        self.session.flush()
        return self._research_job(record)

    def append_search_query(self, command: CreateSearchQuery) -> SearchQuery:
        _require_key(command.command_key, "command_key")
        query_text = " ".join(command.query.split())
        if command.ordinal < 1 or not query_text or len(query_text) > 500:
            raise ValueError("search query is invalid")
        if not command.provider or len(command.provider) > 100:
            raise ValueError("search provider is invalid")
        if not command.provider_version or len(command.provider_version) > 160:
            raise ValueError("search provider version is invalid")
        self._require_job(command.project_id, command.research_job_id)
        digest = canonical_json_digest(
            {
                "research_job_id": str(command.research_job_id),
                "ordinal": command.ordinal,
                "query": query_text,
                "provider": command.provider,
                "provider_version": command.provider_version,
            }
        )
        replay = self.session.scalar(
            select(SearchQueryRecord).where(
                SearchQueryRecord.project_id == command.project_id,
                SearchQueryRecord.command_idempotency_key == command.command_key,
            )
        )
        if replay is not None:
            if replay.digest != digest:
                raise IdempotencyConflict(
                    "search query command key belongs to a different query"
                )
            return self._search_query(replay)
        ordinal_record = self.session.scalar(
            select(SearchQueryRecord).where(
                SearchQueryRecord.project_id == command.project_id,
                SearchQueryRecord.research_job_id == command.research_job_id,
                SearchQueryRecord.ordinal == command.ordinal,
            )
        )
        if ordinal_record is not None:
            if ordinal_record.digest != digest:
                raise IdempotencyConflict("search query ordinal is already occupied")
            return self._search_query(ordinal_record)
        record = SearchQueryRecord(
            project_id=command.project_id,
            research_job_id=command.research_job_id,
            ordinal=command.ordinal,
            query=query_text,
            provider=command.provider,
            provider_version=command.provider_version,
            digest=digest,
            command_idempotency_key=command.command_key,
        )
        self.session.add(record)
        self.session.flush()
        return self._search_query(record)

    def append_search_hit(self, command: CreateSearchHit) -> SearchHit:
        if command.ordinal < 1 or not command.canonical_url or not command.title:
            raise ValueError("search hit is invalid")
        if len(command.canonical_url) > 2_048 or len(command.source_type) > 64:
            raise ValueError("search hit is too long")
        query = self._require_query(command.project_id, command.search_query_id)
        digest = canonical_json_digest(
            {
                "research_job_id": str(query.research_job_id),
                "search_query_id": str(command.search_query_id),
                "ordinal": command.ordinal,
                "canonical_url": command.canonical_url,
                "title": command.title,
                "snippet": command.snippet,
                "source_type": command.source_type,
            }
        )
        existing = self.session.scalar(
            select(SearchHitRecord).where(
                SearchHitRecord.project_id == command.project_id,
                SearchHitRecord.search_query_id == query.id,
                SearchHitRecord.ordinal == command.ordinal,
            )
        )
        if existing is not None:
            if existing.digest != digest:
                raise IdempotencyConflict("search hit ordinal is already occupied")
            return self._search_hit(existing)
        record = SearchHitRecord(
            project_id=command.project_id,
            research_job_id=query.research_job_id,
            search_query_id=query.id,
            ordinal=command.ordinal,
            canonical_url=command.canonical_url,
            title=command.title,
            snippet=command.snippet,
            source_type=command.source_type,
            digest=digest,
        )
        self.session.add(record)
        self.session.flush()
        return self._search_hit(record)

    def append_source_failure(self, command: StoreSourceFailure) -> SourceFailure:
        _require_key(command.command_key, "command_key")
        if command.stage not in {"search", "url_guard", "reader", "redirect"}:
            raise ValueError("source failure stage is invalid")
        if (
            not command.reason_code
            or len(command.reason_code) > 80
            or command.attempts < 0
            or len(command.canonical_url) > 2_048
        ):
            raise ValueError("source failure is invalid")
        self._require_job(command.project_id, command.research_job_id)
        replay = self.session.scalar(
            select(SourceFailureRecord).where(
                SourceFailureRecord.project_id == command.project_id,
                SourceFailureRecord.command_idempotency_key == command.command_key,
            )
        )
        if replay is not None:
            if (
                replay.research_job_id != command.research_job_id
                or replay.stage != command.stage
                or replay.canonical_url != command.canonical_url
                or replay.reason_code != command.reason_code
                or replay.attempts != command.attempts
            ):
                raise IdempotencyConflict(
                    "source failure command key belongs to a different failure"
                )
            return self._source_failure(replay)
        record = SourceFailureRecord(
            project_id=command.project_id,
            research_job_id=command.research_job_id,
            stage=command.stage,
            canonical_url=command.canonical_url,
            reason_code=command.reason_code,
            attempts=command.attempts,
            command_idempotency_key=command.command_key,
        )
        self.session.add(record)
        self.session.flush()
        return self._source_failure(record)

    def list_search_queries(self, job_id: UUID) -> tuple[SearchQuery, ...]:
        records = self.session.scalars(
            select(SearchQueryRecord)
            .where(SearchQueryRecord.research_job_id == job_id)
            .order_by(SearchQueryRecord.ordinal)
        ).all()
        return tuple(self._search_query(record) for record in records)

    def list_search_hits(self, job_id: UUID) -> tuple[SearchHit, ...]:
        records = self.session.scalars(
            select(SearchHitRecord)
            .join(
                SearchQueryRecord,
                SearchQueryRecord.id == SearchHitRecord.search_query_id,
            )
            .where(SearchQueryRecord.research_job_id == job_id)
            .order_by(SearchQueryRecord.ordinal, SearchHitRecord.ordinal)
        ).all()
        return tuple(self._search_hit(record) for record in records)

    def list_source_revisions(
        self, job_id: UUID
    ) -> tuple[SourceDocumentRevision, ...]:
        records = self.session.scalars(
            select(SourceDocumentRevisionRecord)
            .where(SourceDocumentRevisionRecord.research_job_id == job_id)
            .order_by(
                SourceDocumentRevisionRecord.canonical_url,
                SourceDocumentRevisionRecord.revision,
            )
        ).all()
        return tuple(self._source_revision(record) for record in records)

    def list_source_failures(self, job_id: UUID) -> tuple[SourceFailure, ...]:
        records = self.session.scalars(
            select(SourceFailureRecord)
            .where(SourceFailureRecord.research_job_id == job_id)
            .order_by(SourceFailureRecord.created_at, SourceFailureRecord.id)
        ).all()
        return tuple(self._source_failure(record) for record in records)

    def find_books_by_title(
        self,
        normalized_title: str,
        *,
        project_id: UUID | None = None,
    ) -> tuple[Book, ...]:
        title = normalize_book_title(normalized_title)
        if not title:
            return ()
        query = select(BookRecord).where(BookRecord.title == title)
        if project_id is not None:
            query = query.where(BookRecord.project_id == project_id)
        records = self.session.scalars(
            query.order_by(BookRecord.created_at, BookRecord.id)
        ).all()
        return tuple(self._book(record) for record in records)

    def create_book_discovery_resolution(
        self, command: CreateBookDiscoveryResolution
    ) -> Stored[BookDiscoveryResolution]:
        """Append one complete discovery batch without committing its transaction."""

        _require_key(command.command_key, "command_key")
        raw_input = command.raw_input.strip()
        normalized_input = normalize_book_title(raw_input)
        if not normalized_input or len(raw_input) > 300:
            raise ValueError("raw_input must contain 1 to 300 characters")
        if len(command.candidates) > 20:
            raise ValueError("discovery candidate limit exceeded")
        for label, value in (
            ("search_provider", command.search_provider),
            ("reader_provider", command.reader_provider),
        ):
            if not isinstance(value, str) or not value.strip() or len(value) > 200:
                raise ValueError(f"{label} is invalid")
        _require_digest(command.search_schema_digest, "search_schema_digest")
        _require_digest(command.reader_schema_digest, "reader_schema_digest")

        normalized_candidates = []
        identity_digests: set[str] = set()
        for ordinal, candidate in enumerate(command.candidates, start=1):
            identity = normalize_book_identity(
                candidate.title,
                candidate.author,
                candidate.language,
                candidate.edition,
                candidate.translator,
            )
            if identity.digest in identity_digests:
                raise ValueError("duplicate discovery candidate identity")
            identity_digests.add(identity.digest)
            if (
                not isinstance(candidate.canonical_url, str)
                or not candidate.canonical_url.startswith("https://")
                or len(candidate.canonical_url) > 2_048
            ):
                raise ValueError("candidate canonical_url is invalid")
            _require_digest(
                candidate.reader_content_digest, "reader_content_digest"
            )
            normalized_candidates.append(
                {
                    "ordinal": ordinal,
                    "title": identity.title,
                    "author": identity.author,
                    "language": identity.language,
                    "edition": identity.edition,
                    "translator": identity.translator,
                    "identity_digest": identity.digest,
                    "canonical_url": candidate.canonical_url,
                    "reader_content_digest": candidate.reader_content_digest,
                }
            )

        digest = canonical_json_digest(
            {
                "normalized_input": normalized_input,
                "candidates": normalized_candidates,
                "search_provider": command.search_provider,
                "search_schema_digest": command.search_schema_digest,
                "reader_provider": command.reader_provider,
                "reader_schema_digest": command.reader_schema_digest,
            }
        )
        self._serialize(
            f"discovery-command:{command.project_id}:{command.command_key}"
        )
        replay = self.session.scalar(
            select(InputResolutionRecord).where(
                InputResolutionRecord.project_id == command.project_id,
                InputResolutionRecord.command_idempotency_key
                == command.command_key,
            )
        )
        if replay is not None:
            if replay.digest != digest:
                raise IdempotencyConflict(
                    "discovery command key belongs to a different request"
                )
            return Stored(self._book_discovery_resolution(replay), False)

        project = self.session.scalar(
            select(ProjectRecord.id).where(ProjectRecord.id == command.project_id)
        )
        if project is None:
            raise ValueError("project does not exist")
        resolution = InputResolutionRecord(
            project_id=command.project_id,
            raw_input=raw_input,
            normalized_input=normalized_input,
            status="AMBIGUOUS" if normalized_candidates else "UNRESOLVED",
            candidate_book_ids=[],
            selected_book_id=None,
            digest=digest,
            command_idempotency_key=command.command_key,
        )
        self.session.add(resolution)
        self.session.flush()
        records = [
            BookDiscoveryCandidateRecord(
                project_id=command.project_id,
                input_resolution_id=resolution.id,
                search_provider=command.search_provider,
                search_schema_digest=command.search_schema_digest,
                reader_provider=command.reader_provider,
                reader_schema_digest=command.reader_schema_digest,
                **candidate,
            )
            for candidate in normalized_candidates
        ]
        self.session.add_all(records)
        self.session.flush()
        return Stored(
            self._book_discovery_resolution(resolution, records=records), True
        )

    def get_book_discovery_replay(
        self,
        project_id: UUID,
        command_key: str,
        title: str,
    ) -> BookDiscoveryResolution | None:
        """Resolve a durable idempotent replay before any remote side effect."""

        _require_key(command_key, "command_key")
        normalized_title = normalize_book_title(title)
        if not normalized_title:
            raise ValueError("title is required")
        record = self.session.scalar(
            select(InputResolutionRecord).where(
                InputResolutionRecord.project_id == project_id,
                InputResolutionRecord.command_idempotency_key == command_key,
            )
        )
        if record is None:
            return None
        if record.normalized_input != normalized_title:
            raise IdempotencyConflict(
                "discovery command key belongs to a different title"
            )
        return self._book_discovery_resolution(record)

    def get_book_discovery_resolution(
        self, project_id: UUID, input_resolution_id: UUID
    ) -> BookDiscoveryResolution:
        record = self.session.scalar(
            select(InputResolutionRecord).where(
                InputResolutionRecord.id == input_resolution_id,
                InputResolutionRecord.project_id == project_id,
            )
        )
        if record is None:
            raise ValueError("input resolution does not belong to project")
        return self._book_discovery_resolution(record)

    def list_book_discovery_candidates(
        self, project_id: UUID, input_resolution_id: UUID
    ) -> tuple[BookDiscoveryCandidate, ...]:
        resolution = self.session.scalar(
            select(InputResolutionRecord.id).where(
                InputResolutionRecord.id == input_resolution_id,
                InputResolutionRecord.project_id == project_id,
            )
        )
        if resolution is None:
            raise ValueError("input resolution does not belong to project")
        records = self.session.scalars(
            select(BookDiscoveryCandidateRecord)
            .where(
                BookDiscoveryCandidateRecord.project_id == project_id,
                BookDiscoveryCandidateRecord.input_resolution_id
                == input_resolution_id,
            )
            .order_by(
                BookDiscoveryCandidateRecord.ordinal,
                BookDiscoveryCandidateRecord.id,
            )
        ).all()
        return tuple(self._book_discovery_candidate(record) for record in records)

    def select_book_discovery_candidate(
        self, command: SelectBookDiscoveryCandidate
    ) -> Stored[Book]:
        """Create/reuse Book identity only from the persisted candidate row."""

        _require_key(command.command_key, "command_key")
        self._serialize(
            f"discovery-selection-command:{command.project_id}:"
            f"{command.command_key}",
            f"discovery-select:{command.project_id}:{command.input_resolution_id}:"
            f"{command.command_key}",
            f"discovery-selection-resolution:{command.project_id}:"
            f"{command.input_resolution_id}",
        )
        replay = self.session.scalar(
            select(BookDiscoverySelectionRecord).where(
                BookDiscoverySelectionRecord.project_id == command.project_id,
                BookDiscoverySelectionRecord.command_idempotency_key
                == command.command_key,
            )
        )
        if replay is not None:
            if (
                replay.input_resolution_id != command.input_resolution_id
                or replay.candidate_id != command.candidate_id
            ):
                raise IdempotencyConflict(
                    "selection command key belongs to a different candidate"
                )
            return Stored(
                self._book(self._require_book(command.project_id, replay.book_id)),
                False,
            )

        existing = self.session.scalar(
            select(BookDiscoverySelectionRecord).where(
                BookDiscoverySelectionRecord.project_id == command.project_id,
                BookDiscoverySelectionRecord.input_resolution_id
                == command.input_resolution_id,
            )
        )
        if existing is not None:
            if existing.candidate_id != command.candidate_id:
                raise IdempotencyConflict(
                    "input resolution already selected a different candidate"
                )
            return Stored(
                self._book(
                    self._require_book(command.project_id, existing.book_id)
                ),
                False,
            )

        candidate = self.session.scalar(
            select(BookDiscoveryCandidateRecord).where(
                BookDiscoveryCandidateRecord.id == command.candidate_id,
                BookDiscoveryCandidateRecord.project_id == command.project_id,
                BookDiscoveryCandidateRecord.input_resolution_id
                == command.input_resolution_id,
            )
        )
        if candidate is None:
            raise ValueError(
                "candidate does not belong to project and input resolution"
            )
        selected_book = self.create_or_reuse_book(
            CreateBook(
                project_id=command.project_id,
                title=candidate.title,
                author=candidate.author,
                language=candidate.language,
                edition=candidate.edition,
                translator=candidate.translator,
                command_key=command.command_key,
            )
        )
        self.session.add(
            BookDiscoverySelectionRecord(
                project_id=command.project_id,
                input_resolution_id=command.input_resolution_id,
                candidate_id=candidate.id,
                book_id=selected_book.value.id,
                command_idempotency_key=command.command_key,
            )
        )
        self.session.flush()
        return Stored(selected_book.value, True)

    def create_or_reuse_book(self, command: CreateBook) -> Stored[Book]:
        _require_key(command.command_key, "command_key")
        identity = normalize_book_identity(
            command.title,
            command.author,
            command.language,
            command.edition,
            command.translator,
        )
        self._serialize(
            f"book-command:{command.project_id}:{command.command_key}",
            f"book-identity:{command.project_id}:{identity.digest}",
        )
        replay = self.session.scalar(
            select(BookRecord).where(
                BookRecord.project_id == command.project_id,
                BookRecord.command_idempotency_key == command.command_key,
            )
        )
        if replay is not None:
            if replay.identity_digest != identity.digest:
                raise IdempotencyConflict(
                    "book command key belongs to a different identity"
                )
            return Stored(self._book(replay), False)

        existing = self.session.scalar(
            select(BookRecord).where(
                BookRecord.project_id == command.project_id,
                BookRecord.identity_digest == identity.digest,
            )
        )
        if existing is not None:
            return Stored(self._book(existing), False)

        record = BookRecord(
            project_id=command.project_id,
            identity_digest=identity.digest,
            title=identity.title,
            author=identity.author,
            language=identity.language,
            edition=identity.edition,
            translator=identity.translator,
            command_idempotency_key=command.command_key,
        )
        self.session.add(record)
        self.session.flush()
        return Stored(self._book(record), True)

    def merge_books(self, command: MergeBooks) -> Stored[BookMerge]:
        _require_key(command.command_key, "command_key")
        reason = command.reason.strip()
        if not reason or len(reason) > 2_000:
            raise ValueError("reason must contain 1 to 2000 characters")
        if command.source_book_id == command.target_book_id:
            raise ValueError("source and target books must differ")
        self._serialize(
            f"book-merge-command:{command.project_id}:{command.command_key}",
            f"book-merge-graph:{command.project_id}",
            f"book-merge-source:{command.project_id}:{command.source_book_id}",
        )
        replay = self.session.scalar(
            select(BookMergeRecord).where(
                BookMergeRecord.project_id == command.project_id,
                BookMergeRecord.command_idempotency_key == command.command_key,
            )
        )
        if replay is not None:
            if (
                replay.source_book_id != command.source_book_id
                or replay.target_book_id != command.target_book_id
                or replay.reason != reason
            ):
                raise IdempotencyConflict(
                    "book-merge command key belongs to a different decision"
                )
            return Stored(self._book_merge(replay), False)

        self._require_book(command.project_id, command.source_book_id)
        self._require_book(command.project_id, command.target_book_id)
        existing = self.session.scalar(
            select(BookMergeRecord).where(
                BookMergeRecord.project_id == command.project_id,
                BookMergeRecord.source_book_id == command.source_book_id,
            )
        )
        if existing is not None:
            if (
                existing.target_book_id != command.target_book_id
                or existing.reason != reason
            ):
                raise IdempotencyConflict(
                    "source book already has a different merge decision"
                )
            return Stored(self._book_merge(existing), False)

        visited = {command.source_book_id}
        current = command.target_book_id
        while True:
            if current in visited:
                raise ValueError("book merge would create a cycle")
            visited.add(current)
            next_merge = self.session.scalar(
                select(BookMergeRecord).where(
                    BookMergeRecord.project_id == command.project_id,
                    BookMergeRecord.source_book_id == current,
                )
            )
            if next_merge is None:
                break
            current = next_merge.target_book_id

        record = BookMergeRecord(
            project_id=command.project_id,
            source_book_id=command.source_book_id,
            target_book_id=command.target_book_id,
            reason=reason,
            command_idempotency_key=command.command_key,
        )
        self.session.add(record)
        self.session.flush()
        return Stored(self._book_merge(record), True)

    def bind_video_to_book(
        self, command: BindVideoToBook
    ) -> Stored[VideoBookBinding]:
        _require_key(command.command_key, "command_key")
        video_id = command.video_id.strip()
        if not video_id or len(video_id) > 200:
            raise ValueError("video_id must contain 1 to 200 characters")
        self._serialize(
            f"video-binding-command:{command.project_id}:{command.command_key}",
            f"video-binding-pair:{command.project_id}:{video_id}:{command.book_id}",
        )
        replay = self.session.scalar(
            select(VideoBookBindingRecord).where(
                VideoBookBindingRecord.project_id == command.project_id,
                VideoBookBindingRecord.command_idempotency_key == command.command_key,
            )
        )
        if replay is not None:
            if replay.video_id != video_id or replay.book_id != command.book_id:
                raise IdempotencyConflict(
                    "video-binding command key belongs to a different association"
                )
            return Stored(self._video_binding(replay), False)

        self._require_book(command.project_id, command.book_id)
        existing = self.session.scalar(
            select(VideoBookBindingRecord).where(
                VideoBookBindingRecord.project_id == command.project_id,
                VideoBookBindingRecord.video_id == video_id,
                VideoBookBindingRecord.book_id == command.book_id,
            )
        )
        if existing is not None:
            return Stored(self._video_binding(existing), False)

        record = VideoBookBindingRecord(
            project_id=command.project_id,
            video_id=video_id,
            book_id=command.book_id,
            command_idempotency_key=command.command_key,
        )
        self.session.add(record)
        self.session.flush()
        return Stored(self._video_binding(record), True)

    def create_or_reuse_research_job(
        self,
        command: CreateResearchJob,
        *,
        reuse_insufficient: bool = True,
    ) -> Stored[ResearchJob]:
        _require_key(command.command_key, "command_key")
        if not command.provider_version:
            raise ValueError("provider_version is required")
        if min(
            command.query_budget,
            command.reader_budget,
            command.retry_budget,
        ) < 0:
            raise ValueError("research budgets cannot be negative")
        self._serialize(
            f"research-command:{command.project_id}:{command.command_key}",
            f"research-semantic:{command.project_id}:{command.book_id}:"
            f"{command.provider_version}",
        )
        digest = canonical_json_digest(
            {
                "book_id": str(command.book_id),
                "provider_version": command.provider_version,
                "query_budget": command.query_budget,
                "reader_budget": command.reader_budget,
                "retry_budget": command.retry_budget,
            }
        )
        replay = self.session.scalar(
            select(ResearchJobRecord).where(
                ResearchJobRecord.project_id == command.project_id,
                ResearchJobRecord.command_idempotency_key
                == command.command_key,
            )
        )
        if replay is not None:
            if replay.digest != digest:
                raise IdempotencyConflict(
                    "research command key belongs to a different request"
                )
            return Stored(self._research_job(replay), False)

        self._require_book(command.project_id, command.book_id)
        matches = self.session.scalars(
            select(ResearchJobRecord).where(
                ResearchJobRecord.project_id == command.project_id,
                ResearchJobRecord.book_id == command.book_id,
                ResearchJobRecord.provider_version == command.provider_version,
                ResearchJobRecord.digest == digest,
            )
            .order_by(ResearchJobRecord.created_at, ResearchJobRecord.id)
        ).all()
        successful_statuses = (
            {"ready", "insufficient"}
            if reuse_insufficient
            else {"ready"}
        )
        successful = next(
            (
                record
                for record in matches
                if record.status in successful_statuses
            ),
            None,
        )
        if successful is not None:
            return Stored(self._research_job(successful), False)
        active = next(
            (
                record
                for record in matches
                if record.status
                in {
                    "queued",
                    "resolving",
                    "searching",
                    "reading",
                    "extracting",
                    "synthesizing",
                }
            ),
            None,
        )
        if active is not None:
            return Stored(self._research_job(active), False)

        record = ResearchJobRecord(
            project_id=command.project_id,
            book_id=command.book_id,
            provider_version=command.provider_version,
            query_budget=command.query_budget,
            reader_budget=command.reader_budget,
            retry_budget=command.retry_budget,
            digest=digest,
            command_idempotency_key=command.command_key,
        )
        self.session.add(record)
        self.session.flush()
        return Stored(self._research_job(record), True)

    def store_source_revision(
        self, command: StoreSourceDocument
    ) -> SourceDocumentRevision:
        _require_key(command.command_key, "command_key")
        if not command.canonical_url or not command.content:
            raise ValueError("canonical_url and content are required")
        if command.source_type not in {
            "academic",
            "ai_generated",
            "reference",
            "publisher",
            "media",
            "web",
        }:
            raise ValueError("source_type is invalid")
        if (
            not command.source_classification_version
            or len(command.source_classification_version) > 100
        ):
            raise ValueError("source_classification_version is invalid")
        interaction_metrics, interaction_signal = (
            _normalize_interaction_metrics(command.interaction_metrics)
        )
        interaction_observed = interaction_metrics is not None
        host = (urlsplit(command.canonical_url).hostname or "").lower()
        if not host:
            raise ValueError("canonical_url host is required")
        registered_domain = registrable_site_key(host)
        self._serialize(
            f"source-command:{command.project_id}:{command.command_key}",
            f"source-revision:{command.project_id}:{command.canonical_url}",
        )
        content_digest = _sha256_text(command.content)
        digest = canonical_json_digest(
            {
                "research_job_id": str(command.research_job_id),
                "canonical_url": command.canonical_url,
                "content_digest": content_digest,
                "source_type": command.source_type,
                "source_classification_version": (
                    command.source_classification_version
                ),
                "registered_domain": registered_domain,
                "interaction_observed": interaction_observed,
                "interaction_signal": interaction_signal,
                "interaction_metrics": interaction_metrics,
                "interaction_normalization_version": (
                    _INTERACTION_NORMALIZATION_VERSION
                ),
                "search_hit_id": (
                    str(command.search_hit_id)
                    if command.search_hit_id is not None
                    else None
                ),
            }
        )
        replay = self.session.scalar(
            select(SourceDocumentRevisionRecord).where(
                SourceDocumentRevisionRecord.project_id == command.project_id,
                SourceDocumentRevisionRecord.command_idempotency_key
                == command.command_key,
            )
        )
        if replay is not None:
            if replay.digest != digest or replay.content != command.content:
                raise IdempotencyConflict(
                    "source command key belongs to different source bytes"
                )
            return self._source_revision(replay)

        self._require_job(command.project_id, command.research_job_id)
        if command.search_hit_id is not None:
            hit = self.session.scalar(
                select(SearchHitRecord)
                .join(
                    SearchQueryRecord,
                    SearchQueryRecord.id == SearchHitRecord.search_query_id,
                )
                .where(
                    SearchHitRecord.id == command.search_hit_id,
                    SearchHitRecord.project_id == command.project_id,
                    SearchQueryRecord.project_id == command.project_id,
                    SearchQueryRecord.research_job_id
                    == command.research_job_id,
                )
            )
            if hit is None:
                raise ValueError(
                    "search hit does not belong to project/research job"
                )
            if hit.canonical_url != command.canonical_url:
                raise ValueError("search hit URL does not match source URL")
            if hit.source_type != command.source_type:
                raise ValueError(
                    "search hit source type does not match source type"
                )
        revision = (
            self.session.scalar(
                select(func.max(SourceDocumentRevisionRecord.revision)).where(
                    SourceDocumentRevisionRecord.project_id
                    == command.project_id,
                    SourceDocumentRevisionRecord.canonical_url
                    == command.canonical_url,
                )
            )
            or 0
        ) + 1
        record = SourceDocumentRevisionRecord(
            project_id=command.project_id,
            research_job_id=command.research_job_id,
            canonical_url=command.canonical_url,
            source_type=command.source_type,
            source_classification_version=(
                command.source_classification_version
            ),
            registered_domain=registered_domain,
            search_hit_id=command.search_hit_id,
            revision=revision,
            content=command.content,
            content_digest=content_digest,
            interaction_observed=interaction_observed,
            interaction_signal=interaction_signal,
            interaction_metrics=interaction_metrics,
            interaction_normalization_version=(
                _INTERACTION_NORMALIZATION_VERSION
            ),
            digest=digest,
            command_idempotency_key=command.command_key,
        )
        self.session.add(record)
        self.session.flush()
        return self._source_revision(record)

    def append_evidence_claim(
        self, command: AppendEvidenceClaim
    ) -> EvidenceClaim:
        _require_key(command.command_key, "command_key")
        allowed_claim_types = {
            "plot_node",
            "emotional_reaction",
            "style_judgement",
            "reader_fit",
            "factual_context",
        }
        if command.claim_type not in allowed_claim_types:
            raise ValueError("claim_type is invalid")
        if (
            not command.normalized_claim
            or len(command.normalized_claim) > 1_000
        ):
            raise ValueError("normalized_claim is invalid")
        if (
            command.source_span_start < 0
            or command.source_span_end <= command.source_span_start
        ):
            raise ValueError("source span is invalid")
        if (
            len(command.excerpt_digest) != 64
            or any(character not in "0123456789abcdef" for character in command.excerpt_digest)
        ):
            raise ValueError("excerpt_digest is invalid")
        if command.spoiler_level not in {"none", "light", "moderate", "critical"}:
            raise ValueError("spoiler_level is invalid")
        if (
            isinstance(command.confidence, bool)
            or not math.isfinite(command.confidence)
            or not 0.0 <= command.confidence <= 1.0
        ):
            raise ValueError("confidence is invalid")
        if (command.conflict_group_key is None) != (
            command.conflict_severity is None
        ):
            raise ValueError("conflict key and severity must appear together")
        if command.conflict_group_key is not None and (
            not command.conflict_group_key
            or len(command.conflict_group_key) > 160
            or command.conflict_severity not in {"minor", "major", "critical"}
        ):
            raise ValueError("conflict metadata is invalid")

        self._serialize(
            f"evidence-command:{command.project_id}:{command.command_key}"
        )
        source = self.session.scalar(
            select(SourceDocumentRevisionRecord).where(
                SourceDocumentRevisionRecord.id
                == command.source_document_revision_id,
                SourceDocumentRevisionRecord.project_id == command.project_id,
                SourceDocumentRevisionRecord.research_job_id
                == command.research_job_id,
            )
        )
        if source is None:
            raise ValueError(
                "source document does not belong to project/research job"
            )
        self._require_job(command.project_id, command.research_job_id)
        source_span = {
            "start": command.source_span_start,
            "end": command.source_span_end,
        }
        payload = {
            "research_job_id": str(command.research_job_id),
            "source_document_revision_id": str(
                command.source_document_revision_id
            ),
            "claim_type": command.claim_type,
            "normalized_claim": command.normalized_claim,
            "source_span": source_span,
            "excerpt_digest": command.excerpt_digest,
            "is_direct_quote": command.is_direct_quote,
            "spoiler_level": command.spoiler_level,
            "confidence": command.confidence,
            "conflict_group_key": command.conflict_group_key,
            "conflict_severity": command.conflict_severity,
        }
        digest = canonical_json_digest(payload)
        replay = self.session.scalar(
            select(EvidenceClaimRecord).where(
                EvidenceClaimRecord.project_id == command.project_id,
                EvidenceClaimRecord.command_idempotency_key
                == command.command_key,
            )
        )
        if replay is not None:
            if replay.digest != digest:
                raise IdempotencyConflict(
                    "evidence command key belongs to different claim content"
                )
            return self._evidence_claim(replay)

        record = EvidenceClaimRecord(
            project_id=command.project_id,
            research_job_id=command.research_job_id,
            source_document_revision_id=command.source_document_revision_id,
            claim_type=command.claim_type,
            normalized_claim=command.normalized_claim,
            source_span=source_span,
            excerpt_digest=command.excerpt_digest,
            is_direct_quote=command.is_direct_quote,
            spoiler_level=command.spoiler_level,
            confidence=command.confidence,
            conflict_group_key=command.conflict_group_key,
            conflict_severity=command.conflict_severity,
            digest=digest,
            command_idempotency_key=command.command_key,
        )
        self.session.add(record)
        self.session.flush()
        return self._evidence_claim(record)

    def list_evidence_claims(
        self, research_job_id: UUID
    ) -> tuple[EvidenceClaim, ...]:
        records = self.session.scalars(
            select(EvidenceClaimRecord)
            .where(
                EvidenceClaimRecord.research_job_id == research_job_id
            )
            .order_by(EvidenceClaimRecord.created_at, EvidenceClaimRecord.id)
        ).all()
        return tuple(self._evidence_claim(record) for record in records)

    def store_conflict_adjudication(
        self, command: StoreConflictAdjudication
    ) -> EvidenceConflictAdjudicationRevision:
        _require_key(command.command_key, "command_key")
        evidence_ids = tuple(sorted(command.evidence_ids, key=str))
        if len(evidence_ids) > 256 or len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("adjudication evidence IDs must be unique")
        expected_set_digest = canonical_json_digest(
            {"evidence_ids": [str(item) for item in evidence_ids]}
        )
        if command.evidence_set_digest != expected_set_digest:
            raise ValueError("adjudication evidence-set digest mismatch")
        if (
            not command.adjudicator_version
            or len(command.adjudicator_version) > 100
        ):
            raise ValueError("adjudicator_version is invalid")
        decisions = self._validated_adjudication_decisions(
            command.decisions, set(evidence_ids)
        )
        self._serialize(
            _adjudication_semantic_lock_key(
                command.project_id,
                command.research_job_id,
                expected_set_digest,
                command.adjudicator_version,
            )
        )
        self._serialize(
            f"adjudication-command:{command.project_id}:{command.command_key}",
            f"adjudication-revision:{command.project_id}:{command.research_job_id}",
        )
        self._require_job(command.project_id, command.research_job_id)
        claims = self.session.scalars(
            select(EvidenceClaimRecord).where(
                EvidenceClaimRecord.project_id == command.project_id,
                EvidenceClaimRecord.research_job_id
                == command.research_job_id,
                EvidenceClaimRecord.id.in_(evidence_ids),
            )
        ).all()
        if {claim.id for claim in claims} != set(evidence_ids):
            raise ValueError(
                "adjudication evidence does not belong to project/research job"
            )
        digest = canonical_json_digest(
            {
                "research_job_id": str(command.research_job_id),
                "evidence_set_digest": expected_set_digest,
                "adjudicator_version": command.adjudicator_version,
                "decisions": decisions,
            }
        )
        semantic_replay = self.session.scalar(
            select(EvidenceConflictAdjudicationRevisionRecord).where(
                EvidenceConflictAdjudicationRevisionRecord.project_id
                == command.project_id,
                EvidenceConflictAdjudicationRevisionRecord.research_job_id
                == command.research_job_id,
                EvidenceConflictAdjudicationRevisionRecord.evidence_set_digest
                == expected_set_digest,
                EvidenceConflictAdjudicationRevisionRecord.adjudicator_version
                == command.adjudicator_version,
            )
        )
        if semantic_replay is not None:
            membership_ids = self._adjudication_membership_ids(
                semantic_replay.id,
                command.project_id,
                command.research_job_id,
            )
            if (
                semantic_replay.digest != digest
                or membership_ids != evidence_ids
                or tuple(semantic_replay.decisions) != decisions
            ):
                raise IdempotencyConflict(
                    "semantic adjudication already has a different result"
                )
            return self._conflict_adjudication(
                semantic_replay, membership_ids
            )
        replay = self.session.scalar(
            select(EvidenceConflictAdjudicationRevisionRecord).where(
                EvidenceConflictAdjudicationRevisionRecord.project_id
                == command.project_id,
                EvidenceConflictAdjudicationRevisionRecord.command_idempotency_key
                == command.command_key,
            )
        )
        if replay is not None:
            membership_ids = self._adjudication_membership_ids(
                replay.id, command.project_id, command.research_job_id
            )
            if (
                replay.digest != digest
                or membership_ids != evidence_ids
                or tuple(replay.decisions) != decisions
            ):
                raise IdempotencyConflict(
                    "adjudication command key belongs to different result"
                )
            return self._conflict_adjudication(replay, membership_ids)

        revision = (
            self.session.scalar(
                select(
                    func.max(
                        EvidenceConflictAdjudicationRevisionRecord.revision
                    )
                ).where(
                    EvidenceConflictAdjudicationRevisionRecord.project_id
                    == command.project_id,
                    EvidenceConflictAdjudicationRevisionRecord.research_job_id
                    == command.research_job_id,
                )
            )
            or 0
        ) + 1
        record = EvidenceConflictAdjudicationRevisionRecord(
            project_id=command.project_id,
            research_job_id=command.research_job_id,
            revision=revision,
            evidence_set_digest=expected_set_digest,
            adjudicator_version=command.adjudicator_version,
            decisions=list(decisions),
            digest=digest,
            command_idempotency_key=command.command_key,
        )
        self.session.add(record)
        self.session.flush()
        self.session.add_all(
            EvidenceConflictAdjudicationMembershipRecord(
                project_id=command.project_id,
                research_job_id=command.research_job_id,
                adjudication_revision_id=record.id,
                evidence_claim_id=evidence_id,
                ordinal=ordinal,
            )
            for ordinal, evidence_id in enumerate(evidence_ids, start=1)
        )
        self.session.flush()
        return self._conflict_adjudication(record, evidence_ids)

    def get_or_lock_conflict_adjudication(
        self,
        *,
        project_id: UUID,
        research_job_id: UUID,
        evidence_set_digest: str,
        adjudicator_version: str,
    ) -> EvidenceConflictAdjudicationRevision | None:
        if (
            len(evidence_set_digest) != 64
            or any(
                character not in "0123456789abcdef"
                for character in evidence_set_digest
            )
            or not adjudicator_version
            or len(adjudicator_version) > 100
        ):
            raise ValueError("adjudication semantic key is invalid")
        self._serialize(
            _adjudication_semantic_lock_key(
                project_id,
                research_job_id,
                evidence_set_digest,
                adjudicator_version,
            )
        )
        self._require_job(project_id, research_job_id)
        record = self.session.scalar(
            select(EvidenceConflictAdjudicationRevisionRecord).where(
                EvidenceConflictAdjudicationRevisionRecord.project_id
                == project_id,
                EvidenceConflictAdjudicationRevisionRecord.research_job_id
                == research_job_id,
                EvidenceConflictAdjudicationRevisionRecord.evidence_set_digest
                == evidence_set_digest,
                EvidenceConflictAdjudicationRevisionRecord.adjudicator_version
                == adjudicator_version,
            )
        )
        if record is None:
            return None
        membership_ids = self._adjudication_membership_ids(
            record.id, project_id, research_job_id
        )
        expected_set_digest = canonical_json_digest(
            {"evidence_ids": [str(item) for item in membership_ids]}
        )
        if expected_set_digest != evidence_set_digest:
            raise ValueError("cached adjudication membership digest mismatch")
        decisions = self._validated_adjudication_decisions(
            tuple(record.decisions), set(membership_ids)
        )
        expected_digest = canonical_json_digest(
            {
                "research_job_id": str(research_job_id),
                "evidence_set_digest": evidence_set_digest,
                "adjudicator_version": adjudicator_version,
                "decisions": decisions,
            }
        )
        if record.digest != expected_digest:
            raise ValueError("cached adjudication digest mismatch")
        return self._conflict_adjudication(record, membership_ids)

    def freeze_evidence_pack(
        self, command: FreezeEvidencePack
    ) -> EvidencePackRevision:
        _require_key(command.command_key, "command_key")
        evidence_ids = tuple(command.evidence_ids)
        if len(evidence_ids) > 256 or len(set(evidence_ids)) != len(evidence_ids):
            raise ValueError("evidence_ids must be unique")
        self._serialize(
            f"pack-command:{command.project_id}:{command.command_key}",
            f"pack-revision:{command.project_id}:{command.research_job_id}",
        )
        self._require_job(command.project_id, command.research_job_id)
        preliminary_claims = self._load_exact_claim_records(
            command.project_id, command.research_job_id, evidence_ids
        )
        preliminary_sources = self._load_exact_source_records(
            command.project_id,
            command.research_job_id,
            preliminary_claims,
        )
        # This is the exact advisory-lock namespace used by
        # store_source_revision. We only trust rows re-read after it is held.
        self._serialize(
            *(
                f"source-revision:{command.project_id}:{source.canonical_url}"
                for source in preliminary_sources.values()
            )
        )
        claims = self._load_exact_claim_records(
            command.project_id, command.research_job_id, evidence_ids
        )
        sources = self._load_exact_source_records(
            command.project_id, command.research_job_id, claims
        )
        self._validate_pack_source_lineage(
            command.project_id, sources, claims
        )
        adjudication = self.session.scalar(
            select(EvidenceConflictAdjudicationRevisionRecord).where(
                EvidenceConflictAdjudicationRevisionRecord.id
                == command.conflict_adjudication_revision_id,
                EvidenceConflictAdjudicationRevisionRecord.project_id
                == command.project_id,
                EvidenceConflictAdjudicationRevisionRecord.research_job_id
                == command.research_job_id,
            )
        )
        if adjudication is None:
            raise ValueError(
                "conflict adjudication does not belong to project/research job"
            )
        adjudication_ids = self._adjudication_membership_ids(
            adjudication.id, command.project_id, command.research_job_id
        )
        expected_set_ids = tuple(sorted(evidence_ids, key=str))
        if adjudication_ids != expected_set_ids:
            raise ValueError(
                "conflict adjudication does not cover exact evidence set"
            )
        expected_set_digest = canonical_json_digest(
            {"evidence_ids": [str(item) for item in expected_set_ids]}
        )
        if adjudication.evidence_set_digest != expected_set_digest:
            raise ValueError("conflict adjudication evidence digest mismatch")
        decisions = self._validated_adjudication_decisions(
            tuple(adjudication.decisions), set(evidence_ids)
        )
        conflicts = tuple(
            {
                "conflict_group_key": decision["conflict_group_key"],
                "severity": decision["severity"],
                "unresolved": decision["status"] == "unresolved",
                "evidence_ids": list(decision["member_evidence_ids"]),
            }
            for decision in decisions
        )
        coverage = self._derive_coverage(
            tuple(claims.values()), tuple(sources.values())
        )
        unresolved_critical = any(
            item["severity"] == "critical" and item["unresolved"]
            for item in conflicts
        )
        publishable = not unresolved_critical
        reason_codes = (
            ("critical_conflict_unresolved",)
            if unresolved_critical
            else ()
        )
        digest = canonical_json_digest(
            {
                "research_job_id": str(command.research_job_id),
                "evidence_ids": [str(item) for item in evidence_ids],
                "conflict_adjudication_revision_id": str(adjudication.id),
                "adjudicator_version": adjudication.adjudicator_version,
                "adjudication_digest": adjudication.digest,
                "conflicts": conflicts,
                "coverage": coverage,
                "publishable": publishable,
                "insufficiency_reason_codes": reason_codes,
            }
        )
        replay = self.session.scalar(
            select(EvidencePackRevisionRecord).where(
                EvidencePackRevisionRecord.project_id == command.project_id,
                EvidencePackRevisionRecord.command_idempotency_key
                == command.command_key,
            )
        )
        if replay is not None:
            stored_ids = self._membership_ids(replay.id, command.project_id)
            if (
                replay.digest != digest
                or stored_ids != evidence_ids
                or replay.conflict_adjudication_revision_id
                != adjudication.id
                or tuple(replay.conflict_metadata) != conflicts
                or dict(replay.coverage) != coverage
                or replay.publishable != publishable
                or tuple(replay.insufficiency_reason_codes) != reason_codes
            ):
                raise IdempotencyConflict(
                    "evidence-pack command key belongs to different evidence"
                )
            return self._evidence_pack(replay, stored_ids)

        revision = (
            self.session.scalar(
                select(func.max(EvidencePackRevisionRecord.revision)).where(
                    EvidencePackRevisionRecord.project_id == command.project_id,
                    EvidencePackRevisionRecord.research_job_id
                    == command.research_job_id,
                )
            )
            or 0
        ) + 1
        record = EvidencePackRevisionRecord(
            project_id=command.project_id,
            research_job_id=command.research_job_id,
            conflict_adjudication_revision_id=adjudication.id,
            adjudicator_version=adjudication.adjudicator_version,
            revision=revision,
            evidence_count=len(evidence_ids),
            conflict_metadata=list(conflicts),
            coverage=coverage,
            publishable=publishable,
            insufficiency_reason_codes=list(reason_codes),
            digest=digest,
            command_idempotency_key=command.command_key,
        )
        self.session.add(record)
        self.session.flush()
        self.session.add_all(
            EvidencePackMembershipRecord(
                project_id=command.project_id,
                research_job_id=command.research_job_id,
                evidence_pack_revision_id=record.id,
                evidence_claim_id=evidence_id,
                ordinal=ordinal,
            )
            for ordinal, evidence_id in enumerate(evidence_ids, start=1)
        )
        self.session.flush()
        return self._evidence_pack(record, evidence_ids)

    def _load_exact_claim_records(
        self,
        project_id: UUID,
        research_job_id: UUID,
        evidence_ids: tuple[UUID, ...],
    ) -> dict[UUID, EvidenceClaimRecord]:
        if not evidence_ids:
            return {}
        records = self.session.scalars(
            select(EvidenceClaimRecord).where(
                EvidenceClaimRecord.project_id == project_id,
                EvidenceClaimRecord.research_job_id == research_job_id,
                EvidenceClaimRecord.id.in_(evidence_ids),
            )
        ).all()
        by_id = {record.id: record for record in records}
        if set(by_id) != set(evidence_ids):
            raise ValueError(
                "evidence claim does not belong to project/research job"
            )
        return by_id

    def _load_exact_source_records(
        self,
        project_id: UUID,
        research_job_id: UUID,
        claims: dict[UUID, EvidenceClaimRecord],
    ) -> dict[UUID, SourceDocumentRevisionRecord]:
        source_ids = {
            claim.source_document_revision_id for claim in claims.values()
        }
        if not source_ids:
            return {}
        records = self.session.scalars(
            select(SourceDocumentRevisionRecord).where(
                SourceDocumentRevisionRecord.project_id == project_id,
                SourceDocumentRevisionRecord.research_job_id
                == research_job_id,
                SourceDocumentRevisionRecord.id.in_(source_ids),
            )
        ).all()
        by_id = {record.id: record for record in records}
        if set(by_id) != source_ids:
            raise ValueError("evidence source scope mismatch")
        return by_id

    def _validate_pack_source_lineage(
        self,
        project_id: UUID,
        sources: dict[UUID, SourceDocumentRevisionRecord],
        claims: dict[UUID, EvidenceClaimRecord],
    ) -> None:
        for source in sources.values():
            latest = self.session.scalar(
                select(func.max(SourceDocumentRevisionRecord.revision)).where(
                    SourceDocumentRevisionRecord.project_id == project_id,
                    SourceDocumentRevisionRecord.canonical_url
                    == source.canonical_url,
                )
            )
            if latest != source.revision:
                raise ValueError(
                    "evidence source is not the latest frozen revision"
                )
            if _sha256_text(source.content) != source.content_digest:
                raise ValueError("evidence source digest mismatch")
            expected_metrics, expected_signal = _normalize_interaction_metrics(
                dict(source.interaction_metrics)
                if source.interaction_metrics is not None
                else None
            )
            if (
                source.interaction_observed != (expected_metrics is not None)
                or source.interaction_signal != expected_signal
                or source.interaction_normalization_version
                != _INTERACTION_NORMALIZATION_VERSION
            ):
                raise ValueError("evidence source interaction signal mismatch")
        for claim in claims.values():
            source = sources[claim.source_document_revision_id]
            start = claim.source_span.get("start")
            end = claim.source_span.get("end")
            if (
                type(start) is not int
                or type(end) is not int
                or start < 0
                or end <= start
                or end > len(source.content)
                or _sha256_text(source.content[start:end])
                != claim.excerpt_digest
            ):
                raise ValueError("persisted evidence span mismatch")

    @staticmethod
    def _validated_adjudication_decisions(
        decisions: tuple[dict, ...], evidence_ids: set[UUID]
    ) -> tuple[dict[str, object], ...]:
        if len(decisions) > 16:
            raise ValueError("at most sixteen conflict decisions are allowed")
        canonical: list[dict[str, object]] = []
        group_keys: set[str] = set()
        for decision in decisions:
            if set(decision) != {
                "conflict_group_key",
                "member_evidence_ids",
                "severity",
                "status",
            }:
                raise ValueError("adjudication decision schema is invalid")
            raw_members = decision["member_evidence_ids"]
            if not isinstance(raw_members, (list, tuple)):
                raise ValueError("adjudication members are invalid")
            try:
                members = tuple(
                    sorted((UUID(str(item)) for item in raw_members), key=str)
                )
            except (TypeError, ValueError) as error:
                raise ValueError("adjudication evidence ID is invalid") from error
            if (
                len(members) < 2
                or len(members) > 32
                or len(members) != len(set(members))
                or not set(members).issubset(evidence_ids)
            ):
                raise ValueError("adjudication evidence IDs are not exact-scope")
            expected_group_key = "conflict:" + _sha256_text(
                "\x1f".join(str(member) for member in members)
            )
            if decision["conflict_group_key"] != expected_group_key:
                raise ValueError("adjudication conflict key is invalid")
            if expected_group_key in group_keys:
                raise ValueError("adjudication conflict group is duplicated")
            if decision["severity"] not in {"minor", "major", "critical"}:
                raise ValueError("adjudication severity is invalid")
            if decision["status"] not in {"resolved", "unresolved"}:
                raise ValueError("adjudication status is invalid")
            group_keys.add(expected_group_key)
            canonical.append(
                {
                    "conflict_group_key": expected_group_key,
                    "member_evidence_ids": [str(member) for member in members],
                    "severity": decision["severity"],
                    "status": decision["status"],
                }
            )
        return tuple(
            sorted(canonical, key=lambda item: str(item["conflict_group_key"]))
        )

    @staticmethod
    def _derive_coverage(
        claims: tuple[EvidenceClaimRecord, ...],
        sources: tuple[SourceDocumentRevisionRecord, ...],
    ) -> dict[str, object]:
        external_sources = tuple(
            source for source in sources
            if source.source_type != "ai_generated"
        )
        registered_domains = sorted(
            {source.registered_domain for source in external_sources}
        )
        source_type_counts = Counter(
            source.source_type for source in external_sources
        )
        original_text_source_count = sum(
            source.registered_domain in {"archive.org", "gutenberg.org"}
            for source in sources
        )
        ai_generated_source_count = sum(
            source.source_type == "ai_generated" for source in sources
        )
        claim_type_counts = Counter(claim.claim_type for claim in claims)
        classification_versions = sorted(
            {source.source_classification_version for source in sources}
        )
        gap_codes: list[str] = []
        if len(registered_domains) < 3:
            gap_codes.append("independent_sources_insufficient")
        if len(source_type_counts) < 2:
            gap_codes.append("source_types_insufficient")
        for claim_type, gap_code in (
            ("plot_node", "plot_node_missing"),
            ("emotional_reaction", "emotional_reaction_missing"),
            ("reader_fit", "reader_fit_missing"),
        ):
            if claim_type_counts[claim_type] == 0:
                gap_codes.append(gap_code)
        return {
            "content_mode": (
                "source_grounded"
                if original_text_source_count > 0
                else "ai_completed"
            ),
            "original_text_source_count": original_text_source_count,
            "ai_generated_source_count": ai_generated_source_count,
            "external_source_count": len(external_sources),
            "disclosure_required": original_text_source_count == 0,
            "validated_claim_count": len(claims),
            "source_document_count": len(sources),
            "independent_registered_domain_count": len(registered_domains),
            "registered_domains": registered_domains,
            "source_type_count": len(source_type_counts),
            "source_type_counts": dict(sorted(source_type_counts.items())),
            "source_classification_versions": classification_versions,
            "claim_type_count": len(claim_type_counts),
            "claim_type_counts": dict(sorted(claim_type_counts.items())),
            "gap_codes": gap_codes,
        }

    def load_resonance_context(
        self, evidence_pack_revision_id: UUID
    ) -> tuple[
        EvidencePackRevision,
        tuple[EvidenceClaim, ...],
        tuple[SourceDocumentRevision, ...],
    ]:
        pack_record = self.session.scalar(
            select(EvidencePackRevisionRecord).where(
                EvidencePackRevisionRecord.id == evidence_pack_revision_id
            )
        )
        if pack_record is None:
            raise ValueError("evidence pack does not exist")
        membership_ids = self._membership_ids(
            pack_record.id, pack_record.project_id
        )
        if (
            len(membership_ids) != pack_record.evidence_count
            or len(membership_ids) != len(set(membership_ids))
        ):
            raise ValueError("evidence pack membership is inconsistent")
        claims = self._load_exact_claim_records(
            pack_record.project_id,
            pack_record.research_job_id,
            membership_ids,
        )
        sources = self._load_exact_source_records(
            pack_record.project_id,
            pack_record.research_job_id,
            claims,
        )
        self._validate_pack_source_lineage(
            pack_record.project_id, sources, claims
        )
        pack = self._evidence_pack(pack_record, membership_ids)
        return (
            pack,
            tuple(self._evidence_claim(claims[item]) for item in membership_ids),
            tuple(
                self._source_revision(sources[item])
                for item in sorted(sources, key=str)
            ),
        )

    def list_directions_for_command(
        self, project_id: UUID, command_key: str
    ) -> tuple[ResonanceDirectionRevision, ...]:
        _require_key(command_key, "command_key")
        records = self.session.scalars(
            select(ResonanceDirectionRevisionRecord)
            .where(
                ResonanceDirectionRevisionRecord.project_id == project_id,
                ResonanceDirectionRevisionRecord.command_idempotency_key
                == command_key,
            )
            .order_by(ResonanceDirectionRevisionRecord.publication_ordinal)
        ).all()
        if not records:
            return ()
        if (
            len(records) > 4
            or tuple(item.publication_ordinal for item in records)
            != tuple(range(1, len(records) + 1))
            or len({item.evidence_pack_revision_id for item in records}) != 1
        ):
            raise ValueError("persisted direction publication is inconsistent")
        pack, claims, sources = self.load_resonance_context(
            records[0].evidence_pack_revision_id
        )
        from creative_hub.shidu.resonance_validator import (
            validate_persisted_direction_payload,
        )

        canonical_payloads = tuple(
            validate_persisted_direction_payload(
                item.direction_key,
                item.payload,
                pack=pack,
                claims_by_id={claim.id: claim for claim in claims},
                sources_by_id={source.id: source for source in sources},
            )
            for item in records
        )
        for record, payload in zip(records, canonical_payloads, strict=True):
            expected_digest = canonical_json_digest(
                {
                    "evidence_pack_revision_id": str(pack.id),
                    "direction_key": record.direction_key,
                    "payload": payload,
                }
            )
            if (
                record.digest != expected_digest
                or record.evidence_count != len(payload["evidence_ids"])
                or record.score != payload["score"]
                or record.score_version != payload["score_version"]
                or record.validator_version != payload["validator_version"]
            ):
                raise ValueError("persisted direction digest is inconsistent")
        if tuple(records) != tuple(
            sorted(
                records,
                key=lambda item: (-item.score, item.direction_key),
            )
        ):
            raise ValueError("persisted direction ordering is inconsistent")
        return tuple(self._direction(item) for item in records)

    def validate_direction_payload(
        self,
        evidence_pack_revision_id: UUID,
        direction_key: str,
        payload: dict,
    ) -> dict:
        from creative_hub.shidu.resonance_validator import (
            validate_persisted_direction_payload,
        )

        pack, claims, sources = self.load_resonance_context(
            evidence_pack_revision_id
        )
        return validate_persisted_direction_payload(
            direction_key,
            payload,
            pack=pack,
            claims_by_id={item.id: item for item in claims},
            sources_by_id={item.id: item for item in sources},
        )

    def publish_directions(
        self, command: PublishDirections
    ) -> tuple[ResonanceDirectionRevision, ...]:
        _require_key(command.command_key, "command_key")
        directions = tuple(command.directions)
        if len(directions) > 4:
            raise ValueError("at most four resonance directions may be published")
        if len({item.direction_key for item in directions}) != len(directions):
            raise ValueError("direction_key values must be unique")
        if any(not item.direction_key for item in directions):
            raise ValueError("direction_key is required")
        self._serialize(
            f"direction-command:{command.project_id}:{command.command_key}",
            *(
                f"direction-revision:{command.project_id}:{item.direction_key}"
                for item in directions
            ),
        )
        pack = self.session.scalar(
            select(EvidencePackRevisionRecord).where(
                EvidencePackRevisionRecord.id
                == command.evidence_pack_revision_id,
                EvidencePackRevisionRecord.project_id == command.project_id,
            )
        )
        if pack is None:
            raise ValueError("evidence pack does not belong to project")
        if not pack.publishable:
            raise EvidencePackNotPublishable(
                "critical_conflict_unresolved"
            )
        context_pack, context_claims, context_sources = (
            self.load_resonance_context(pack.id)
        )
        from creative_hub.shidu.resonance_validator import (
            validate_persisted_direction_payload,
        )

        canonical_directions = tuple(
            DirectionDraft(
                direction_key=item.direction_key,
                payload=validate_persisted_direction_payload(
                    item.direction_key,
                    item.payload,
                    pack=context_pack,
                    claims_by_id={
                        claim.id: claim for claim in context_claims
                    },
                    sources_by_id={
                        source.id: source for source in context_sources
                    },
                ),
            )
            for item in directions
        )
        if canonical_directions != tuple(
            sorted(
                canonical_directions,
                key=lambda item: (
                    -float(item.payload["score"]),
                    item.direction_key,
                ),
            )
        ):
            raise ValueError(
                "directions must be ordered by descending score then key"
            )
        directions = canonical_directions
        replay = tuple(
            self.session.scalars(
                select(ResonanceDirectionRevisionRecord)
                .where(
                    ResonanceDirectionRevisionRecord.project_id
                    == command.project_id,
                    ResonanceDirectionRevisionRecord.command_idempotency_key
                    == command.command_key,
                )
                .order_by(
                    ResonanceDirectionRevisionRecord.publication_ordinal
                )
            ).all()
        )
        expected = tuple(
            (
                item.direction_key,
                canonical_json_digest(
                    {
                        "evidence_pack_revision_id": str(
                            command.evidence_pack_revision_id
                        ),
                        "direction_key": item.direction_key,
                        "payload": item.payload,
                    }
                ),
            )
            for item in directions
        )
        if replay:
            actual = tuple((item.direction_key, item.digest) for item in replay)
            if actual != expected:
                raise IdempotencyConflict(
                    "direction command key belongs to different directions"
                )
            return tuple(self._direction(item) for item in replay)
        if not directions:
            return ()

        records: list[ResonanceDirectionRevisionRecord] = []
        for ordinal, (draft, (_, digest)) in enumerate(
            zip(directions, expected, strict=True), start=1
        ):
            revision = (
                self.session.scalar(
                    select(
                        func.max(ResonanceDirectionRevisionRecord.revision)
                    ).where(
                        ResonanceDirectionRevisionRecord.project_id
                        == command.project_id,
                        ResonanceDirectionRevisionRecord.direction_key
                        == draft.direction_key,
                    )
                )
                or 0
            ) + 1
            records.append(
                ResonanceDirectionRevisionRecord(
                    project_id=command.project_id,
                    evidence_pack_revision_id=command.evidence_pack_revision_id,
                    direction_key=draft.direction_key,
                    revision=revision,
                    publication_ordinal=ordinal,
                    evidence_count=len(draft.payload["evidence_ids"]),
                    score=float(draft.payload["score"]),
                    score_version=str(draft.payload["score_version"]),
                    validator_version=str(draft.payload["validator_version"]),
                    payload=dict(draft.payload),
                    digest=digest,
                    command_idempotency_key=command.command_key,
                )
            )
        self.session.add_all(records)
        self.session.flush()
        return tuple(self._direction(item) for item in records)

    def freeze_trial_methodology(
        self, command: FreezeTrialMethodology
    ) -> TrialMethodologyRevision:
        from creative_hub.shidu.trial_methodology import (
            METHODOLOGY_KEY,
            METHODOLOGY_PROMPT_DIGEST,
            METHODOLOGY_VERSION,
            TRIAL_VALIDATOR_VERSION,
            methodology_v01_payload,
        )

        _require_key(command.command_key, "command_key")
        expected_payload = methodology_v01_payload()
        if (
            command.methodology_key != METHODOLOGY_KEY
            or command.methodology_version != METHODOLOGY_VERSION
            or command.prompt_digest != METHODOLOGY_PROMPT_DIGEST
            or command.validator_version != TRIAL_VALIDATOR_VERSION
            or canonical_json_digest(command.payload)
            != canonical_json_digest(expected_payload)
        ):
            raise ValueError("trial methodology v0.1 payload is invalid")
        self._serialize(
            f"trial-methodology-command:{command.project_id}:{command.command_key}",
            f"trial-methodology-revision:{command.project_id}:{command.methodology_key}",
        )
        expected_digest = canonical_json_digest(
            {
                "project_id": str(command.project_id),
                "methodology_key": command.methodology_key,
                "methodology_version": command.methodology_version,
                "prompt_digest": command.prompt_digest,
                "validator_version": command.validator_version,
                "payload": expected_payload,
            }
        )
        replay = self.session.scalar(
            select(TrialMethodologyRevisionRecord).where(
                TrialMethodologyRevisionRecord.project_id == command.project_id,
                TrialMethodologyRevisionRecord.command_idempotency_key
                == command.command_key,
            )
        )
        if replay is not None:
            if replay.digest != expected_digest:
                raise IdempotencyConflict(
                    "trial methodology command key belongs to different content"
                )
            return self._methodology(replay)
        existing = self.session.scalar(
            select(TrialMethodologyRevisionRecord).where(
                TrialMethodologyRevisionRecord.project_id == command.project_id,
                TrialMethodologyRevisionRecord.methodology_key
                == command.methodology_key,
                TrialMethodologyRevisionRecord.methodology_version
                == command.methodology_version,
            )
        )
        if existing is not None:
            if existing.digest != expected_digest:
                raise ValueError("persisted trial methodology v0.1 is inconsistent")
            return self._methodology(existing)
        if self.session.get(ProjectRecord, command.project_id) is None:
            raise ValueError("project does not exist")
        record = TrialMethodologyRevisionRecord(
            project_id=command.project_id,
            methodology_key=command.methodology_key,
            methodology_version=command.methodology_version,
            revision=1,
            prompt_digest=command.prompt_digest,
            validator_version=command.validator_version,
            payload=expected_payload,
            digest=expected_digest,
            command_idempotency_key=command.command_key,
        )
        self.session.add(record)
        self.session.flush()
        return self._methodology(record)

    def get_trial_methodology(
        self, methodology_revision_id: UUID
    ) -> TrialMethodologyRevision:
        from creative_hub.shidu.trial_methodology import (
            METHODOLOGY_KEY,
            METHODOLOGY_PROMPT_DIGEST,
            METHODOLOGY_VERSION,
            TRIAL_VALIDATOR_VERSION,
            methodology_v01_payload,
        )

        record = self.session.get(
            TrialMethodologyRevisionRecord, methodology_revision_id
        )
        if record is None:
            raise ValueError("trial methodology revision does not exist")
        expected_digest = canonical_json_digest(
            {
                "project_id": str(record.project_id),
                "methodology_key": METHODOLOGY_KEY,
                "methodology_version": METHODOLOGY_VERSION,
                "prompt_digest": METHODOLOGY_PROMPT_DIGEST,
                "validator_version": TRIAL_VALIDATOR_VERSION,
                "payload": methodology_v01_payload(),
            }
        )
        if (
            record.methodology_key != METHODOLOGY_KEY
            or record.methodology_version != METHODOLOGY_VERSION
            or record.prompt_digest != METHODOLOGY_PROMPT_DIGEST
            or record.validator_version != TRIAL_VALIDATOR_VERSION
            or record.revision != 1
            or record.digest != expected_digest
            or canonical_json_digest(record.payload)
            != canonical_json_digest(methodology_v01_payload())
        ):
            raise ValueError("persisted trial methodology v0.1 is inconsistent")
        return self._methodology(record)

    def load_direction_context(
        self, direction_revision_id: UUID
    ) -> tuple[
        ResonanceDirectionRevision,
        EvidencePackRevision,
        tuple[EvidenceClaim, ...],
        tuple[SourceDocumentRevision, ...],
        UUID,
    ]:
        record = self.session.get(
            ResonanceDirectionRevisionRecord, direction_revision_id
        )
        if record is None:
            raise ValueError("resonance direction revision does not exist")
        pack, claims, sources = self.load_resonance_context(
            record.evidence_pack_revision_id
        )
        canonical = self.validate_direction_payload(
            pack.id, record.direction_key, record.payload
        )
        expected_digest = canonical_json_digest(
            {
                "evidence_pack_revision_id": str(pack.id),
                "direction_key": record.direction_key,
                "payload": canonical,
            }
        )
        if (
            record.project_id != pack.project_id
            or record.digest != expected_digest
            or record.evidence_count != len(canonical["evidence_ids"])
            or record.score != canonical["score"]
            or record.validator_version != canonical["validator_version"]
        ):
            raise ValueError("persisted resonance direction is inconsistent")
        job = self._require_job(pack.project_id, pack.research_job_id)
        return self._direction(record), pack, claims, sources, job.book_id

    def get_trial_script_for_command(
        self, project_id: UUID, command_key: str
    ) -> TrialScriptRevision | None:
        _require_key(command_key, "command_key")
        record = self.session.scalar(
            select(TrialScriptRevisionRecord).where(
                TrialScriptRevisionRecord.project_id == project_id,
                TrialScriptRevisionRecord.command_idempotency_key == command_key,
            )
        )
        return None if record is None else self._validated_trial_script(record)

    def get_trial_script(self, script_revision_id: UUID) -> TrialScriptRevision:
        record = self.session.get(TrialScriptRevisionRecord, script_revision_id)
        if record is None:
            raise ValueError("trial script revision does not exist")
        return self._validated_trial_script(record)

    def store_trial_script(
        self, command: StoreTrialScript
    ) -> TrialScriptRevision:
        from creative_hub.shidu.trial_script_validator import (
            TRIAL_VALIDATOR_VERSION,
            TrialScriptValidator,
        )

        _require_key(command.command_key, "command_key")
        self._serialize(
            f"trial-script-command:{command.project_id}:{command.command_key}",
            f"trial-script-revision:{command.project_id}:{command.book_id}",
        )
        self._require_book(command.project_id, command.book_id)
        direction, pack, claims, sources, direction_book_id = (
            self.load_direction_context(command.resonance_direction_revision_id)
        )
        methodology = self.get_trial_methodology(command.methodology_revision_id)
        if (
            direction.project_id != command.project_id
            or methodology.project_id != command.project_id
            or pack.id != command.evidence_pack_revision_id
            or direction_book_id != command.book_id
        ):
            raise ValueError("trial script frozen revision lineage is invalid")
        canonical = TrialScriptValidator(
            methodology=methodology,
            direction=direction,
            pack=pack,
            claims=claims,
            sources=sources,
            book_id=command.book_id,
        ).validate(command.payload)
        if canonical.get("safety_rewrite_provenance") is None:
            canonical.pop("safety_rewrite_provenance", None)
        source_record = self._validate_trial_script_rewrite_lineage(
            project_id=command.project_id,
            book_id=command.book_id,
            evidence_pack_revision_id=pack.id,
            resonance_direction_revision_id=direction.id,
            methodology_revision_id=methodology.id,
            payload=canonical,
            source_trial_script_revision_id=(
                command.source_trial_script_revision_id
            ),
            source_safety_decision_digest=(
                command.source_safety_decision_digest
            ),
        )
        digest = canonical_json_digest(
            self._trial_script_digest_material(
                book_id=command.book_id,
                evidence_pack_revision_id=pack.id,
                resonance_direction_revision_id=direction.id,
                methodology_revision_id=methodology.id,
                payload=canonical,
                source_trial_script_revision_id=(
                    command.source_trial_script_revision_id
                ),
                source_safety_decision_digest=(
                    command.source_safety_decision_digest
                ),
            )
        )
        replay = self.session.scalar(
            select(TrialScriptRevisionRecord).where(
                TrialScriptRevisionRecord.project_id == command.project_id,
                TrialScriptRevisionRecord.command_idempotency_key
                == command.command_key,
            )
        )
        if replay is not None:
            if replay.digest != digest:
                raise IdempotencyConflict(
                    "trial script command key belongs to different content"
                )
            return self._validated_trial_script(replay)
        revision = (
            self.session.scalar(
                select(func.max(TrialScriptRevisionRecord.revision)).where(
                    TrialScriptRevisionRecord.project_id == command.project_id,
                    TrialScriptRevisionRecord.book_id == command.book_id,
                )
            )
            or 0
        ) + 1
        if source_record is not None and source_record.revision >= revision:
            raise ValueError(
                "safety rewrite source must precede the new trial script revision"
            )
        record = TrialScriptRevisionRecord(
            project_id=command.project_id,
            book_id=command.book_id,
            evidence_pack_revision_id=pack.id,
            resonance_direction_revision_id=direction.id,
            methodology_revision_id=methodology.id,
            revision=revision,
            validator_version=TRIAL_VALIDATOR_VERSION,
            payload=canonical,
            digest=digest,
            source_trial_script_revision_id=(
                command.source_trial_script_revision_id
            ),
            source_safety_decision_digest=(
                command.source_safety_decision_digest
            ),
            command_idempotency_key=command.command_key,
        )
        self.session.add(record)
        self.session.flush()
        return self._trial_script(record)

    def load_trial_script_context(
        self, script_revision_id: UUID
    ) -> tuple[
        TrialScriptRevision,
        TrialMethodologyRevision,
        ResonanceDirectionRevision,
        EvidencePackRevision,
        tuple[EvidenceClaim, ...],
        tuple[SourceDocumentRevision, ...],
    ]:
        script = self.get_trial_script(script_revision_id)
        methodology = self.get_trial_methodology(script.methodology_revision_id)
        direction, pack, claims, sources, book_id = self.load_direction_context(
            script.resonance_direction_revision_id
        )
        if book_id != script.book_id:
            raise ValueError("trial script book lineage is inconsistent")
        return script, methodology, direction, pack, claims, sources

    def _validated_trial_script(
        self, record: TrialScriptRevisionRecord
    ) -> TrialScriptRevision:
        from creative_hub.shidu.trial_script_validator import TrialScriptValidator

        direction, pack, claims, sources, book_id = self.load_direction_context(
            record.resonance_direction_revision_id
        )
        methodology = self.get_trial_methodology(record.methodology_revision_id)
        if (
            record.project_id != direction.project_id
            or record.project_id != methodology.project_id
            or record.book_id != book_id
            or record.evidence_pack_revision_id != pack.id
        ):
            raise ValueError("persisted trial script lineage is inconsistent")
        canonical = TrialScriptValidator(
            methodology=methodology,
            direction=direction,
            pack=pack,
            claims=claims,
            sources=sources,
            book_id=book_id,
        ).validate(record.payload)
        if canonical.get("safety_rewrite_provenance") is None:
            canonical.pop("safety_rewrite_provenance", None)
        self._validate_trial_script_rewrite_lineage(
            project_id=record.project_id,
            book_id=record.book_id,
            evidence_pack_revision_id=record.evidence_pack_revision_id,
            resonance_direction_revision_id=(
                record.resonance_direction_revision_id
            ),
            methodology_revision_id=record.methodology_revision_id,
            payload=canonical,
            source_trial_script_revision_id=(
                record.source_trial_script_revision_id
            ),
            source_safety_decision_digest=(
                record.source_safety_decision_digest
            ),
            target_trial_script_revision_id=record.id,
            target_revision=record.revision,
        )
        expected_digest = canonical_json_digest(
            self._trial_script_digest_material(
                book_id=record.book_id,
                evidence_pack_revision_id=pack.id,
                resonance_direction_revision_id=direction.id,
                methodology_revision_id=methodology.id,
                payload=canonical,
                source_trial_script_revision_id=(
                    record.source_trial_script_revision_id
                ),
                source_safety_decision_digest=(
                    record.source_safety_decision_digest
                ),
            )
        )
        if record.validator_version != canonical["validator_version"] or record.digest != expected_digest:
            raise ValueError("persisted trial script digest is inconsistent")
        return self._trial_script(record)

    @staticmethod
    def _trial_script_digest_material(
        *,
        book_id: UUID,
        evidence_pack_revision_id: UUID,
        resonance_direction_revision_id: UUID,
        methodology_revision_id: UUID,
        payload: dict,
        source_trial_script_revision_id: UUID | None,
        source_safety_decision_digest: str | None,
    ) -> dict:
        material = {
            "book_id": str(book_id),
            "evidence_pack_revision_id": str(evidence_pack_revision_id),
            "resonance_direction_revision_id": str(
                resonance_direction_revision_id
            ),
            "methodology_revision_id": str(methodology_revision_id),
            "payload": payload,
        }
        if source_trial_script_revision_id is not None:
            material["source_trial_script_revision_id"] = str(
                source_trial_script_revision_id
            )
            material["source_safety_decision_digest"] = (
                source_safety_decision_digest
            )
        return material

    def _validate_trial_script_rewrite_lineage(
        self,
        *,
        project_id: UUID,
        book_id: UUID,
        evidence_pack_revision_id: UUID,
        resonance_direction_revision_id: UUID,
        methodology_revision_id: UUID,
        payload: dict,
        source_trial_script_revision_id: UUID | None,
        source_safety_decision_digest: str | None,
        target_trial_script_revision_id: UUID | None = None,
        target_revision: int | None = None,
    ) -> TrialScriptRevisionRecord | None:
        if (source_trial_script_revision_id is None) != (
            source_safety_decision_digest is None
        ):
            raise ValueError("safety rewrite lineage fields must be paired")
        provenance = payload.get("safety_rewrite_provenance")
        if source_trial_script_revision_id is None:
            if provenance is not None:
                raise ValueError(
                    "safety rewrite provenance requires durable source lineage"
                )
            return None
        if (
            not isinstance(source_safety_decision_digest, str)
            or len(source_safety_decision_digest) != 64
            or any(
                item not in "0123456789abcdef"
                for item in source_safety_decision_digest
            )
        ):
            raise ValueError("source safety decision digest is invalid")
        if source_trial_script_revision_id == target_trial_script_revision_id:
            raise ValueError("a trial script rewrite cannot source itself")
        source_record = self.session.get(
            TrialScriptRevisionRecord, source_trial_script_revision_id
        )
        if source_record is None:
            raise ValueError("safety rewrite source trial script does not exist")
        if (
            source_record.project_id != project_id
            or source_record.book_id != book_id
            or source_record.evidence_pack_revision_id
            != evidence_pack_revision_id
            or source_record.resonance_direction_revision_id
            != resonance_direction_revision_id
            or source_record.methodology_revision_id != methodology_revision_id
        ):
            raise ValueError(
                "safety rewrite source must use the same frozen context"
            )
        if target_revision is not None and source_record.revision >= target_revision:
            raise ValueError(
                "safety rewrite source must precede the new trial script revision"
            )
        source = self._validated_trial_script(source_record)
        from creative_hub.shidu.trial_safety import TrialScriptSafety

        try:
            source_safety = TrialScriptSafety.model_validate(
                source.payload.get("safety_gate")
            )
        except (AttributeError, TypeError, ValueError) as exc:
            raise ValueError(
                "safety rewrite source decision is invalid"
            ) from exc
        if (
            source_safety.post_compile.release_decision_digest
            != source_safety_decision_digest
        ):
            raise ValueError(
                "safety rewrite provenance source decision digest is not exact"
            )
        if (
            not source_safety.post_compile.blocked_reason_codes
            or not source_safety.post_compile.rewrite_requirements
            or not source_safety.post_compile.required_human_review
        ):
            raise ValueError(
                "safety rewrite source decision does not authorize a rewrite"
            )
        expected_provenance = {
            "source_trial_script_revision_id": str(source.id),
            "source_trial_script_digest": source.digest,
            "source_safety_decision_digest": source_safety_decision_digest,
        }
        if provenance != expected_provenance:
            raise ValueError(
                "safety rewrite provenance does not match durable source lineage"
            )
        return source_record

    def store_voice_preset_revision(
        self, command: StoreVoicePresetRevision
    ) -> VoicePresetRevision:
        _require_key(command.command_key, "command_key")
        _require_key(command.preset_key, "preset_key")
        self._validate_voice_preset_command(command)
        self._serialize(
            f"voice-preset-command:{command.project_id}:{command.command_key}",
            f"voice-preset-revision:{command.project_id}:{command.preset_key}",
        )
        if self.session.get(ProjectRecord, command.project_id) is None:
            raise ValueError("project does not exist")
        replay = self.session.scalar(
            select(VoicePresetRevisionRecord).where(
                VoicePresetRevisionRecord.project_id == command.project_id,
                VoicePresetRevisionRecord.command_idempotency_key
                == command.command_key,
            )
        )
        if replay is not None:
            expected_payload = self._voice_preset_payload(command)
            expected_digest = self._voice_preset_digest(
                command, revision=replay.revision, payload=expected_payload
            )
            if replay.digest != expected_digest:
                raise IdempotencyConflict(
                    "voice preset command key belongs to different content"
                )
            return self._validated_voice_preset(replay)

        revision = (
            self.session.scalar(
                select(func.max(VoicePresetRevisionRecord.revision)).where(
                    VoicePresetRevisionRecord.project_id == command.project_id,
                    VoicePresetRevisionRecord.preset_key == command.preset_key,
                )
            )
            or 0
        ) + 1
        payload = self._voice_preset_payload(command)
        instruction_digest = _sha256_text(command.instruction or "")
        digest = self._voice_preset_digest(
            command, revision=revision, payload=payload
        )
        record = VoicePresetRevisionRecord(
            project_id=command.project_id,
            preset_key=command.preset_key,
            revision=revision,
            provider=command.provider,
            model_id=command.model_id,
            model_digest=command.model_digest,
            speaker=command.speaker,
            language=command.language,
            instruction_digest=instruction_digest,
            enabled=command.enabled,
            discovery_service_version=command.discovery_service_version,
            discovery_tool_name=command.discovery_tool_name,
            discovery_schema_digest=command.discovery_schema_digest,
            payload=payload,
            digest=digest,
            command_idempotency_key=command.command_key,
        )
        self.session.add(record)
        self.session.flush()
        return self._validated_voice_preset(record)

    def get_voice_preset_revision(
        self, voice_preset_revision_id: UUID
    ) -> VoicePresetRevision:
        record = self.session.get(
            VoicePresetRevisionRecord, voice_preset_revision_id
        )
        if record is None:
            raise ValueError("voice preset revision does not exist")
        return self._validated_voice_preset(record)

    @staticmethod
    def _validate_voice_preset_command(
        command: StoreVoicePresetRevision,
    ) -> None:
        if command.provider != _QWEN_TTS_PROVIDER:
            raise ValueError("voice preset provider must be Qwen CustomVoice MCP")
        if command.model_id != _QWEN_TTS_MODEL:
            raise ValueError("voice preset model must be the locked CustomVoice model")
        if len(command.model_digest) != 64 or any(
            item not in "0123456789abcdef" for item in command.model_digest
        ):
            raise ValueError("voice preset model digest is invalid")
        if command.language != "Chinese":
            raise ValueError("voice preset language must be Chinese")
        if command.discovery_tool_name != _QWEN_TTS_TOOL:
            raise ValueError("voice preset discovery tool is invalid")
        if command.discovery_schema_digest != _QWEN_TTS_SCHEMA:
            raise ValueError("voice preset discovery schema is invalid")
        if (
            not command.discovery_service_version.strip()
            or len(command.discovery_service_version) > 100
        ):
            raise ValueError("voice preset discovery service version is invalid")
        discovered = tuple(command.discovered_speakers)
        policy = tuple(command.policy_allowed_speakers)
        if (
            any(not item.strip() for item in discovered)
            or len(set(discovered)) != len(discovered)
            or not _DEFAULT_TTS_SPEAKERS.issubset(discovered)
        ):
            raise ValueError("voice preset discovered speaker snapshot is invalid")
        if (
            any(not item.strip() for item in policy)
            or len(set(policy)) != len(policy)
            or not _DEFAULT_TTS_SPEAKERS.issubset(policy)
            or not set(policy).issubset(_TTS_SPEAKERS)
        ):
            raise ValueError("voice preset speaker policy is invalid")
        if command.speaker not in discovered:
            raise ValueError("voice preset speaker was not discovered")
        if command.speaker not in policy:
            raise ValueError("voice preset speaker is not allowed by policy")
        if command.speaker not in _TTS_SPEAKERS:
            raise ValueError("voice preset speaker is outside Phase 2 policy")
        if not isinstance(command.enabled, bool):
            raise ValueError("voice preset enabled flag is invalid")
        if command.default_gender not in {"female", "male", "neutral"}:
            raise ValueError("voice preset default gender is invalid")
        categories = tuple(command.applicable_book_categories)
        if (
            len(categories) > 32
            or any(not item.strip() or len(item) > 100 for item in categories)
            or len(set(categories)) != len(categories)
        ):
            raise ValueError("voice preset book categories are invalid")
        instruction = command.instruction
        if instruction is not None:
            if not instruction.strip() or len(instruction) > 300:
                raise ValueError("voice preset instruction is invalid")
            folded = instruction.casefold()
            if any(term in folded for term in _VOICE_CLONE_TERMS):
                raise ValueError(
                    "voice preset instruction cannot request cloning or reference audio"
                )

    @staticmethod
    def _voice_preset_payload(command: StoreVoicePresetRevision) -> dict:
        return {
            "schema_version": "shidu-voice-preset.v1",
            "instruction": command.instruction,
            "applicable_book_categories": list(
                command.applicable_book_categories
            ),
            "default_gender": command.default_gender,
            "discovered_speakers": list(command.discovered_speakers),
            "policy_allowed_speakers": list(command.policy_allowed_speakers),
        }

    @staticmethod
    def _voice_preset_digest(
        command: StoreVoicePresetRevision,
        *,
        revision: int,
        payload: dict,
    ) -> str:
        return canonical_json_digest(
            {
                "project_id": str(command.project_id),
                "preset_key": command.preset_key,
                "revision": revision,
                "provider": command.provider,
                "model_id": command.model_id,
                "model_digest": command.model_digest,
                "speaker": command.speaker,
                "language": command.language,
                "instruction_digest": _sha256_text(command.instruction or ""),
                "enabled": command.enabled,
                "discovery_service_version": command.discovery_service_version,
                "discovery_tool_name": command.discovery_tool_name,
                "discovery_schema_digest": command.discovery_schema_digest,
                "payload": payload,
            }
        )

    def _validated_voice_preset(
        self, record: VoicePresetRevisionRecord
    ) -> VoicePresetRevision:
        payload = dict(record.payload)
        expected_keys = {
            "schema_version",
            "instruction",
            "applicable_book_categories",
            "default_gender",
            "discovered_speakers",
            "policy_allowed_speakers",
        }
        if set(payload) != expected_keys:
            raise ValueError("persisted voice preset payload is inconsistent")
        command = StoreVoicePresetRevision(
            project_id=record.project_id,
            preset_key=record.preset_key,
            provider=record.provider,
            model_id=record.model_id,
            model_digest=record.model_digest,
            speaker=record.speaker,
            language=record.language,
            instruction=payload["instruction"],
            applicable_book_categories=tuple(
                payload["applicable_book_categories"]
            ),
            default_gender=payload["default_gender"],
            enabled=record.enabled,
            discovery_service_version=record.discovery_service_version,
            discovery_tool_name=record.discovery_tool_name,
            discovery_schema_digest=record.discovery_schema_digest,
            discovered_speakers=tuple(payload["discovered_speakers"]),
            policy_allowed_speakers=tuple(payload["policy_allowed_speakers"]),
            command_key=record.command_idempotency_key,
        )
        self._validate_voice_preset_command(command)
        expected_digest = self._voice_preset_digest(
            command, revision=record.revision, payload=payload
        )
        if (
            payload["schema_version"] != "shidu-voice-preset.v1"
            or record.instruction_digest
            != _sha256_text(command.instruction or "")
            or record.digest != expected_digest
        ):
            raise ValueError("persisted voice preset digest is inconsistent")
        return self._voice_preset(record)

    def record_tts_take(self, command: RecordTTSTake) -> TTSTake:
        _require_key(command.command_key, "command_key")
        _require_key(command.cue_key, "cue_key")
        self._serialize(
            f"tts-take-command:{command.project_id}:{command.command_key}"
        )
        script = self.session.scalar(
            select(TrialScriptRevisionRecord).where(
                TrialScriptRevisionRecord.id
                == command.trial_script_revision_id,
                TrialScriptRevisionRecord.project_id == command.project_id,
            )
        )
        if script is None:
            raise ValueError("TTS trial script revision does not exist")
        preset_record = self.session.scalar(
            select(VoicePresetRevisionRecord).where(
                VoicePresetRevisionRecord.id
                == command.voice_preset_revision_id,
                VoicePresetRevisionRecord.project_id == command.project_id,
            )
        )
        if preset_record is None:
            raise ValueError("TTS voice preset revision does not exist")
        preset = self._validated_voice_preset(preset_record)
        self._validate_tts_take_command(command, script, preset)
        metadata = self._tts_take_metadata(command)
        digest = canonical_json_digest(
            {
                "project_id": str(command.project_id),
                "trial_script_revision_id": str(command.trial_script_revision_id),
                "voice_preset_revision_id": str(command.voice_preset_revision_id),
                "cue_key": command.cue_key,
                "audio_digest": command.audio_digest,
                "metadata": metadata,
            }
        )
        replay = self.session.scalar(
            select(TTSTakeRecord).where(
                TTSTakeRecord.project_id == command.project_id,
                TTSTakeRecord.command_idempotency_key == command.command_key,
            )
        )
        if replay is not None:
            if replay.digest != digest:
                raise IdempotencyConflict(
                    "TTS take command key belongs to different content"
                )
            return self._validated_tts_take(replay)
        record = TTSTakeRecord(
            project_id=command.project_id,
            trial_script_revision_id=command.trial_script_revision_id,
            voice_preset_revision_id=command.voice_preset_revision_id,
            cue_key=command.cue_key,
            requested_provider=command.requested_provider,
            requested_model_id=command.requested_model_id,
            actual_provider=command.actual_provider,
            actual_model_id=command.actual_model_id,
            actual_service_version=command.actual_service_version,
            actual_tool_name=command.actual_tool_name,
            actual_schema_digest=command.actual_schema_digest,
            speaker=command.speaker,
            language=command.language,
            instruction_digest=command.instruction_digest,
            audio_artifact_id=command.audio_artifact_id,
            audio_digest=command.audio_digest,
            audio_byte_size=command.audio_byte_size,
            sample_rate_hz=command.sample_rate_hz,
            channels=command.channels,
            pcm_sample_width_bytes=command.pcm_sample_width_bytes,
            duration_seconds=command.duration_seconds,
            peak_amplitude=command.peak_amplitude,
            clipping_ratio=command.clipping_ratio,
            silence_ratio=command.silence_ratio,
            leading_silence_seconds=command.leading_silence_seconds,
            trailing_silence_seconds=command.trailing_silence_seconds,
            qc_accepted=command.qc_accepted,
            retry_count=command.retry_count,
            error_classification=command.error_classification,
            lipsync_required=command.lipsync_required,
            metadata_payload=metadata,
            digest=digest,
            command_idempotency_key=command.command_key,
        )
        self.session.add(record)
        self.session.flush()
        return self._validated_tts_take(record)

    def get_tts_take(self, tts_take_id: UUID) -> TTSTake:
        record = self.session.get(TTSTakeRecord, tts_take_id)
        if record is None:
            raise ValueError("TTS take does not exist")
        return self._validated_tts_take(record)

    @staticmethod
    def _validate_tts_take_command(
        command: RecordTTSTake,
        script: TrialScriptRevisionRecord,
        preset: VoicePresetRevision,
    ) -> None:
        cues = script.payload.get("narration_cues")
        if not isinstance(cues, list):
            raise ValueError("TTS script cue payload is invalid")
        matches = [
            item
            for item in cues
            if isinstance(item, dict) and item.get("cue_key") == command.cue_key
        ]
        if len(matches) != 1 or not isinstance(matches[0].get("text"), str):
            raise ValueError("TTS cue does not exist exactly once")
        if command.cue_text_digest != _sha256_text(matches[0]["text"]):
            raise ValueError("TTS cue text digest is inconsistent")
        if (
            command.requested_provider != preset.provider
            or command.actual_provider != preset.provider
        ):
            raise ValueError("TTS provider identity is inconsistent")
        if (
            command.requested_model_id != preset.model_id
            or command.actual_model_id != preset.model_id
        ):
            raise ValueError("TTS model identity is inconsistent")
        if command.actual_service_version != preset.discovery_service_version:
            raise ValueError("TTS service version is inconsistent")
        if command.actual_tool_name != preset.discovery_tool_name:
            raise ValueError("TTS tool identity is inconsistent")
        if command.actual_schema_digest != preset.discovery_schema_digest:
            raise ValueError("TTS schema identity is inconsistent")
        if command.speaker != preset.speaker:
            raise ValueError("TTS speaker is inconsistent")
        if command.language != preset.language:
            raise ValueError("TTS language is inconsistent")
        if command.instruction_digest != preset.instruction_digest:
            raise ValueError("TTS instruction digest is inconsistent")
        for value, label in (
            (command.cue_text_digest, "cue text"),
            (command.instruction_digest, "instruction"),
            (command.audio_digest, "audio"),
            (command.actual_schema_digest, "schema"),
        ):
            if len(value) != 64 or any(
                item not in "0123456789abcdef" for item in value
            ):
                raise ValueError(f"TTS {label} digest is invalid")
        if command.audio_byte_size <= 44 or command.audio_mime != "audio/wav":
            raise ValueError("TTS audio artifact is invalid")
        if command.sample_rate_hz != 24_000:
            raise ValueError("TTS sample rate must be 24 kHz")
        if command.channels != 1:
            raise ValueError("TTS channel count must be mono")
        if command.pcm_sample_width_bytes != 2:
            raise ValueError("TTS PCM sample width must be 16-bit")
        numeric = {
            "duration_seconds": command.duration_seconds,
            "peak_amplitude": command.peak_amplitude,
            "clipping_ratio": command.clipping_ratio,
            "silence_ratio": command.silence_ratio,
            "leading_silence_seconds": command.leading_silence_seconds,
            "trailing_silence_seconds": command.trailing_silence_seconds,
        }
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            for value in numeric.values()
        ):
            raise ValueError("TTS QC metrics must be finite")
        if not 0 < command.duration_seconds <= 300:
            raise ValueError("TTS duration is invalid")
        if any(
            not 0 <= value <= 1
            for value in (
                command.peak_amplitude,
                command.clipping_ratio,
                command.silence_ratio,
            )
        ) or min(
            command.leading_silence_seconds,
            command.trailing_silence_seconds,
        ) < 0:
            raise ValueError("TTS QC metrics are outside valid bounds")
        if not command.qc_accepted or command.qc_defect_codes:
            raise ValueError("TTS QC must be accepted without defects")
        if (
            isinstance(command.retry_count, bool)
            or not isinstance(command.retry_count, int)
            or not 0 <= command.retry_count <= 3
        ):
            raise ValueError("TTS retry count is invalid")
        if command.error_classification is not None:
            raise ValueError("successful TTS take cannot carry an error classification")
        if command.lipsync_required:
            raise ValueError("Shidu TTS take must not require lipsync")

    @staticmethod
    def _tts_take_metadata(command: RecordTTSTake) -> dict:
        return {
            "schema_version": "shidu-tts-take.v1",
            "cue_text_digest": command.cue_text_digest,
            "requested": {
                "provider": command.requested_provider,
                "model_id": command.requested_model_id,
            },
            "actual": {
                "provider": command.actual_provider,
                "model_id": command.actual_model_id,
                "service_version": command.actual_service_version,
                "tool_name": command.actual_tool_name,
                "schema_digest": command.actual_schema_digest,
                "speaker": command.speaker,
                "language": command.language,
            },
            "instruction_digest": command.instruction_digest,
            "audio_artifact": {
                "artifact_id": str(command.audio_artifact_id),
                "sha256": command.audio_digest,
                "byte_size": command.audio_byte_size,
                "mime": command.audio_mime,
            },
            "quality": {
                "accepted": command.qc_accepted,
                "defect_codes": list(command.qc_defect_codes),
                "sample_rate_hz": command.sample_rate_hz,
                "channels": command.channels,
                "pcm_sample_width_bytes": command.pcm_sample_width_bytes,
                "duration_seconds": command.duration_seconds,
                "peak_amplitude": command.peak_amplitude,
                "clipping_ratio": command.clipping_ratio,
                "silence_ratio": command.silence_ratio,
                "leading_silence_seconds": command.leading_silence_seconds,
                "trailing_silence_seconds": command.trailing_silence_seconds,
            },
            "retry_count": command.retry_count,
            "error_classification": command.error_classification,
            "lipsync_required": command.lipsync_required,
        }

    def _validated_tts_take(self, record: TTSTakeRecord) -> TTSTake:
        script = self.session.scalar(
            select(TrialScriptRevisionRecord).where(
                TrialScriptRevisionRecord.id == record.trial_script_revision_id,
                TrialScriptRevisionRecord.project_id == record.project_id,
            )
        )
        preset_record = self.session.scalar(
            select(VoicePresetRevisionRecord).where(
                VoicePresetRevisionRecord.id == record.voice_preset_revision_id,
                VoicePresetRevisionRecord.project_id == record.project_id,
            )
        )
        if script is None or preset_record is None:
            raise ValueError("persisted TTS take lineage is inconsistent")
        preset = self._validated_voice_preset(preset_record)
        metadata = dict(record.metadata_payload)
        quality = metadata.get("quality")
        artifact = metadata.get("audio_artifact")
        if not isinstance(quality, dict) or not isinstance(artifact, dict):
            raise ValueError("persisted TTS take metadata is inconsistent")
        command = RecordTTSTake(
            project_id=record.project_id,
            trial_script_revision_id=record.trial_script_revision_id,
            voice_preset_revision_id=record.voice_preset_revision_id,
            cue_key=record.cue_key,
            cue_text_digest=metadata.get("cue_text_digest", ""),
            requested_provider=record.requested_provider,
            requested_model_id=record.requested_model_id,
            actual_provider=record.actual_provider,
            actual_model_id=record.actual_model_id,
            actual_service_version=record.actual_service_version,
            actual_tool_name=record.actual_tool_name,
            actual_schema_digest=record.actual_schema_digest,
            speaker=record.speaker,
            language=record.language,
            instruction_digest=record.instruction_digest,
            audio_artifact_id=record.audio_artifact_id,
            audio_digest=record.audio_digest,
            audio_byte_size=record.audio_byte_size,
            audio_mime=artifact.get("mime", ""),
            sample_rate_hz=record.sample_rate_hz,
            channels=record.channels,
            pcm_sample_width_bytes=record.pcm_sample_width_bytes,
            duration_seconds=record.duration_seconds,
            peak_amplitude=record.peak_amplitude,
            clipping_ratio=record.clipping_ratio,
            silence_ratio=record.silence_ratio,
            leading_silence_seconds=record.leading_silence_seconds,
            trailing_silence_seconds=record.trailing_silence_seconds,
            qc_accepted=record.qc_accepted,
            qc_defect_codes=tuple(quality.get("defect_codes", ())),
            retry_count=record.retry_count,
            error_classification=record.error_classification,
            lipsync_required=record.lipsync_required,
            command_key=record.command_idempotency_key,
        )
        self._validate_tts_take_command(command, script, preset)
        expected_metadata = self._tts_take_metadata(command)
        expected_digest = canonical_json_digest(
            {
                "project_id": str(record.project_id),
                "trial_script_revision_id": str(record.trial_script_revision_id),
                "voice_preset_revision_id": str(record.voice_preset_revision_id),
                "cue_key": record.cue_key,
                "audio_digest": record.audio_digest,
                "metadata": expected_metadata,
            }
        )
        if (
            canonical_json_digest(metadata)
            != canonical_json_digest(expected_metadata)
            or record.digest != expected_digest
        ):
            raise ValueError("persisted TTS take digest is inconsistent")
        return self._tts_take(record)

    def _membership_ids(
        self, pack_id: UUID, project_id: UUID
    ) -> tuple[UUID, ...]:
        return tuple(
            self.session.scalars(
                select(EvidencePackMembershipRecord.evidence_claim_id)
                .where(
                    EvidencePackMembershipRecord.evidence_pack_revision_id
                    == pack_id,
                    EvidencePackMembershipRecord.project_id == project_id,
                )
                .order_by(EvidencePackMembershipRecord.ordinal)
            ).all()
        )

    def _adjudication_membership_ids(
        self,
        adjudication_id: UUID,
        project_id: UUID,
        research_job_id: UUID,
    ) -> tuple[UUID, ...]:
        return tuple(
            self.session.scalars(
                select(
                    EvidenceConflictAdjudicationMembershipRecord.evidence_claim_id
                )
                .where(
                    EvidenceConflictAdjudicationMembershipRecord.adjudication_revision_id
                    == adjudication_id,
                    EvidenceConflictAdjudicationMembershipRecord.project_id
                    == project_id,
                    EvidenceConflictAdjudicationMembershipRecord.research_job_id
                    == research_job_id,
                )
                .order_by(
                    EvidenceConflictAdjudicationMembershipRecord.ordinal
                )
            ).all()
        )

    @staticmethod
    def _book(record: BookRecord) -> Book:
        return Book(
            id=record.id,
            project_id=record.project_id,
            identity_digest=record.identity_digest,
            title=record.title,
            author=record.author,
            language=record.language,
            edition=record.edition,
            translator=record.translator,
            created_at=record.created_at,
        )

    @staticmethod
    def _book_discovery_candidate(
        record: BookDiscoveryCandidateRecord,
    ) -> BookDiscoveryCandidate:
        return BookDiscoveryCandidate(
            id=record.id,
            project_id=record.project_id,
            input_resolution_id=record.input_resolution_id,
            ordinal=record.ordinal,
            title=record.title,
            author=record.author,
            language=record.language,
            edition=record.edition,
            translator=record.translator,
            identity_digest=record.identity_digest,
            canonical_url=record.canonical_url,
            reader_content_digest=record.reader_content_digest,
            search_provider=record.search_provider,
            search_schema_digest=record.search_schema_digest,
            reader_provider=record.reader_provider,
            reader_schema_digest=record.reader_schema_digest,
            created_at=record.created_at,
        )

    def _book_discovery_resolution(
        self,
        record: InputResolutionRecord,
        *,
        records: Iterable[BookDiscoveryCandidateRecord] | None = None,
    ) -> BookDiscoveryResolution:
        candidates = (
            tuple(records)
            if records is not None
            else tuple(
                self.session.scalars(
                    select(BookDiscoveryCandidateRecord)
                    .where(
                        BookDiscoveryCandidateRecord.project_id
                        == record.project_id,
                        BookDiscoveryCandidateRecord.input_resolution_id
                        == record.id,
                    )
                    .order_by(
                        BookDiscoveryCandidateRecord.ordinal,
                        BookDiscoveryCandidateRecord.id,
                    )
                ).all()
            )
        )
        selection = self.session.scalar(
            select(BookDiscoverySelectionRecord).where(
                BookDiscoverySelectionRecord.project_id == record.project_id,
                BookDiscoverySelectionRecord.input_resolution_id == record.id,
            )
        )
        return BookDiscoveryResolution(
            id=record.id,
            project_id=record.project_id,
            raw_input=record.raw_input,
            status="RESOLVED" if selection is not None else record.status,
            selected_book_id=(selection.book_id if selection is not None else None),
            candidates=tuple(
                self._book_discovery_candidate(candidate)
                for candidate in candidates
            ),
            digest=record.digest,
            created_at=record.created_at,
        )

    @staticmethod
    def _book_merge(record: BookMergeRecord) -> BookMerge:
        return BookMerge(
            id=record.id,
            project_id=record.project_id,
            source_book_id=record.source_book_id,
            target_book_id=record.target_book_id,
            reason=record.reason,
            command_key=record.command_idempotency_key,
            created_at=record.created_at,
        )

    @staticmethod
    def _video_binding(record: VideoBookBindingRecord) -> VideoBookBinding:
        return VideoBookBinding(
            id=record.id,
            project_id=record.project_id,
            video_id=record.video_id,
            book_id=record.book_id,
            command_key=record.command_idempotency_key,
            created_at=record.created_at,
        )

    @staticmethod
    def _research_job(record: ResearchJobRecord) -> ResearchJob:
        return ResearchJob(
            id=record.id,
            project_id=record.project_id,
            book_id=record.book_id,
            provider_version=record.provider_version,
            status=record.status,
            query_budget=record.query_budget,
            reader_budget=record.reader_budget,
            retry_budget=record.retry_budget,
            digest=record.digest,
            command_key=record.command_idempotency_key,
            created_at=record.created_at,
        )

    @staticmethod
    def _search_query(record: SearchQueryRecord) -> SearchQuery:
        return SearchQuery(
            id=record.id,
            project_id=record.project_id,
            research_job_id=record.research_job_id,
            ordinal=record.ordinal,
            query=record.query,
            provider=record.provider,
            provider_version=record.provider_version,
            digest=record.digest,
        )

    @staticmethod
    def _search_hit(record: SearchHitRecord) -> SearchHit:
        return SearchHit(
            id=record.id,
            project_id=record.project_id,
            research_job_id=record.research_job_id,
            search_query_id=record.search_query_id,
            ordinal=record.ordinal,
            canonical_url=record.canonical_url,
            title=record.title,
            snippet=record.snippet,
            source_type=record.source_type,
            digest=record.digest,
        )

    @staticmethod
    def _source_failure(record: SourceFailureRecord) -> SourceFailure:
        return SourceFailure(
            id=record.id,
            project_id=record.project_id,
            research_job_id=record.research_job_id,
            stage=record.stage,
            canonical_url=record.canonical_url,
            reason_code=record.reason_code,
            attempts=record.attempts,
            command_key=record.command_idempotency_key,
            created_at=record.created_at,
        )

    @staticmethod
    def _source_revision(
        record: SourceDocumentRevisionRecord,
    ) -> SourceDocumentRevision:
        return SourceDocumentRevision(
            id=record.id,
            project_id=record.project_id,
            research_job_id=record.research_job_id,
            canonical_url=record.canonical_url,
            source_type=record.source_type,
            source_classification_version=record.source_classification_version,
            registered_domain=record.registered_domain,
            search_hit_id=record.search_hit_id,
            revision=record.revision,
            content=record.content,
            content_digest=record.content_digest,
            interaction_observed=record.interaction_observed,
            interaction_signal=record.interaction_signal,
            interaction_metrics=(
                dict(record.interaction_metrics)
                if record.interaction_metrics is not None
                else None
            ),
            interaction_normalization_version=(
                record.interaction_normalization_version
            ),
            digest=record.digest,
            command_key=record.command_idempotency_key,
            created_at=record.created_at,
        )

    @staticmethod
    def _evidence_claim(record: EvidenceClaimRecord) -> EvidenceClaim:
        return EvidenceClaim(
            id=record.id,
            project_id=record.project_id,
            research_job_id=record.research_job_id,
            source_document_revision_id=record.source_document_revision_id,
            claim_type=record.claim_type,
            normalized_claim=record.normalized_claim,
            source_span=dict(record.source_span),
            excerpt_digest=record.excerpt_digest,
            is_direct_quote=record.is_direct_quote,
            spoiler_level=record.spoiler_level,
            confidence=record.confidence,
            conflict_group_key=record.conflict_group_key,
            conflict_severity=record.conflict_severity,
            digest=record.digest,
            command_key=record.command_idempotency_key,
            created_at=record.created_at,
        )

    @staticmethod
    def _conflict_adjudication(
        record: EvidenceConflictAdjudicationRevisionRecord,
        evidence_ids: Iterable[UUID],
    ) -> EvidenceConflictAdjudicationRevision:
        return EvidenceConflictAdjudicationRevision(
            id=record.id,
            project_id=record.project_id,
            research_job_id=record.research_job_id,
            revision=record.revision,
            evidence_ids=tuple(evidence_ids),
            evidence_set_digest=record.evidence_set_digest,
            adjudicator_version=record.adjudicator_version,
            decisions=tuple(dict(item) for item in record.decisions),
            digest=record.digest,
            command_key=record.command_idempotency_key,
            created_at=record.created_at,
        )

    @staticmethod
    def _evidence_pack(
        record: EvidencePackRevisionRecord,
        evidence_ids: Iterable[UUID],
    ) -> EvidencePackRevision:
        return EvidencePackRevision(
            id=record.id,
            project_id=record.project_id,
            research_job_id=record.research_job_id,
            revision=record.revision,
            evidence_ids=tuple(evidence_ids),
            conflict_adjudication_revision_id=(
                record.conflict_adjudication_revision_id
            ),
            adjudicator_version=record.adjudicator_version,
            conflicts=tuple(dict(item) for item in record.conflict_metadata),
            coverage=dict(record.coverage),
            publishable=record.publishable,
            insufficiency_reason_codes=tuple(
                record.insufficiency_reason_codes
            ),
            digest=record.digest,
            command_key=record.command_idempotency_key,
            created_at=record.created_at,
        )

    @staticmethod
    def _direction(
        record: ResonanceDirectionRevisionRecord,
    ) -> ResonanceDirectionRevision:
        return ResonanceDirectionRevision(
            id=record.id,
            project_id=record.project_id,
            evidence_pack_revision_id=record.evidence_pack_revision_id,
            direction_key=record.direction_key,
            revision=record.revision,
            publication_ordinal=record.publication_ordinal,
            evidence_count=record.evidence_count,
            score=record.score,
            score_version=record.score_version,
            validator_version=record.validator_version,
            payload=dict(record.payload),
            digest=record.digest,
            command_key=record.command_idempotency_key,
            created_at=record.created_at,
        )

    @staticmethod
    def _methodology(
        record: TrialMethodologyRevisionRecord,
    ) -> TrialMethodologyRevision:
        return TrialMethodologyRevision(
            id=record.id,
            project_id=record.project_id,
            methodology_key=record.methodology_key,
            methodology_version=record.methodology_version,
            revision=record.revision,
            prompt_digest=record.prompt_digest,
            validator_version=record.validator_version,
            payload=dict(record.payload),
            digest=record.digest,
            command_key=record.command_idempotency_key,
            created_at=record.created_at,
        )

    @staticmethod
    def _trial_script(record: TrialScriptRevisionRecord) -> TrialScriptRevision:
        return TrialScriptRevision(
            id=record.id,
            project_id=record.project_id,
            book_id=record.book_id,
            evidence_pack_revision_id=record.evidence_pack_revision_id,
            resonance_direction_revision_id=(
                record.resonance_direction_revision_id
            ),
            methodology_revision_id=record.methodology_revision_id,
            revision=record.revision,
            validator_version=record.validator_version,
            payload=dict(record.payload),
            digest=record.digest,
            command_key=record.command_idempotency_key,
            created_at=record.created_at,
            source_trial_script_revision_id=(
                record.source_trial_script_revision_id
            ),
            source_safety_decision_digest=(
                record.source_safety_decision_digest
            ),
        )

    @staticmethod
    def _voice_preset(
        record: VoicePresetRevisionRecord,
    ) -> VoicePresetRevision:
        return VoicePresetRevision(
            id=record.id,
            project_id=record.project_id,
            preset_key=record.preset_key,
            revision=record.revision,
            provider=record.provider,
            model_id=record.model_id,
            model_digest=record.model_digest,
            speaker=record.speaker,
            language=record.language,
            instruction_digest=record.instruction_digest,
            enabled=record.enabled,
            discovery_service_version=record.discovery_service_version,
            discovery_tool_name=record.discovery_tool_name,
            discovery_schema_digest=record.discovery_schema_digest,
            payload=dict(record.payload),
            digest=record.digest,
            command_key=record.command_idempotency_key,
            created_at=record.created_at,
        )

    @staticmethod
    def _tts_take(record: TTSTakeRecord) -> TTSTake:
        return TTSTake(
            id=record.id,
            project_id=record.project_id,
            trial_script_revision_id=record.trial_script_revision_id,
            voice_preset_revision_id=record.voice_preset_revision_id,
            cue_key=record.cue_key,
            requested_provider=record.requested_provider,
            requested_model_id=record.requested_model_id,
            actual_provider=record.actual_provider,
            actual_model_id=record.actual_model_id,
            actual_service_version=record.actual_service_version,
            actual_tool_name=record.actual_tool_name,
            actual_schema_digest=record.actual_schema_digest,
            speaker=record.speaker,
            language=record.language,
            instruction_digest=record.instruction_digest,
            audio_artifact_id=record.audio_artifact_id,
            audio_digest=record.audio_digest,
            qc_accepted=record.qc_accepted,
            retry_count=record.retry_count,
            error_classification=record.error_classification,
            lipsync_required=record.lipsync_required,
            metadata=dict(record.metadata_payload),
            digest=record.digest,
            command_key=record.command_idempotency_key,
            created_at=record.created_at,
        )
