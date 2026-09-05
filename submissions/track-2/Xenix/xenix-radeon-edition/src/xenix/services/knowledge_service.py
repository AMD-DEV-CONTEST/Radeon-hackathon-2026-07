from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable, Protocol

import jieba
from sqlalchemy.orm import sessionmaker

from ..exceptions import ValidationError
from .storage.models import KnowledgeDocumentRow
from .storage.repositories.knowledge import KnowledgeRepository

MAX_KNOWLEDGE_QUERY_CHARS = 512
MAX_KNOWLEDGE_TOP_K = 8
MAX_KNOWLEDGE_QUOTE_CHARS = 1600
MAX_KNOWLEDGE_UNIT_CHARS = 8_000
KNOWLEDGE_LOOKUP_MODES = ("auto", "keyword", "semantic", "hybrid")
_HYBRID_RRF_K = 60
_MAX_RETRIEVAL_CANDIDATES = 32


@dataclass(frozen=True)
class KnowledgeUnitInput:
    text: str
    locator: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class KnowledgeDocumentSummary:
    document_id: str
    title: str
    source_format: str
    content_state: str
    imported_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class KnowledgeMatch:
    citation_id: str
    document_id: str
    document_generation_id: str
    source_artifact_id: str | None
    unit_id: str
    title: str
    locator: dict[str, Any]
    quote: str


@dataclass(frozen=True)
class KnowledgeRetrievalResult:
    mode: str
    matches: list[KnowledgeMatch]


@dataclass(frozen=True)
class KnowledgeSemanticCandidates:
    unit_ids: tuple[str, ...]
    corpus_fingerprint: str
    profile_fingerprint: str
    generation_id: str


class KnowledgeSemanticUnavailable(ValidationError):
    def __init__(self) -> None:
        super().__init__(
            "Knowledge semantic retrieval is unavailable.",
            error_code="knowledge_semantic_unavailable",
            retryable=True,
        )


class KnowledgeSemanticIntegrityError(ValidationError):
    def __init__(self) -> None:
        super().__init__(
            "Knowledge semantic retrieval failed an integrity check.",
            error_code="knowledge_semantic_integrity_failed",
            retryable=False,
        )


class KnowledgeRetrievalUnavailable(ValidationError):
    def __init__(self, *, requested_mode: str, available_modes: list[str]) -> None:
        super().__init__(
            f"The requested '{requested_mode}' Knowledge retrieval mode is not available.",
            error_code="knowledge_retrieval_mode_unavailable",
            error_details={
                "requested_mode": requested_mode,
                "available_modes": list(available_modes),
            },
            repair_hints=["Use 'auto' or 'keyword' for this lookup."],
            retryable=False,
        )
        self.requested_mode = requested_mode
        self.available_modes = list(available_modes)


class KnowledgeSemanticSearch(Protocol):
    def is_configured(self) -> bool: ...

    def search(
        self,
        query: str,
        *,
        library_id: str,
        limit: int,
    ) -> KnowledgeSemanticCandidates: ...

    def is_current(
        self,
        candidates: KnowledgeSemanticCandidates,
        *,
        library_id: str,
    ) -> bool: ...


class KnowledgeService:
    """Own the current searchable Knowledge Unit corpus and bounded lookup."""

    def __init__(
        self,
        session_factory: sessionmaker,
        *,
        semantic_search: KnowledgeSemanticSearch | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._repository = KnowledgeRepository()
        self._semantic_search = semantic_search

    def get_document_by_source_sha256(
        self,
        source_sha256: str,
        *,
        library_id: str = "global",
    ) -> KnowledgeDocumentRow | None:
        with self._session_factory() as session:
            return self._repository.get_document_by_source_sha256(
                session,
                library_id=library_id,
                source_sha256=source_sha256,
            )

    def list_documents(
        self,
        *,
        library_id: str = "global",
    ) -> list[KnowledgeDocumentSummary]:
        with self._session_factory() as session:
            rows = self._repository.list_documents(
                session,
                library_id=library_id,
            )
        return [
            KnowledgeDocumentSummary(
                document_id=row.id,
                title=row.title,
                source_format=row.source_format or "unknown",
                content_state=_document_content_state(row.retrieval_status),
                imported_at=row.created_at,
                updated_at=row.updated_at,
            )
            for row in rows
        ]

    def lookup(
        self,
        query: str,
        *,
        document_ids: list[str] | None = None,
        top_k: int = 5,
        library_id: str = "global",
    ) -> list[KnowledgeMatch]:
        normalized_query, filters = _validated_lookup(
            query,
            document_ids=document_ids,
            top_k=top_k,
        )

        with self._session_factory() as session:
            unit_ids = self._repository.search_unit_ids(
                session,
                fts_query=_fts_query(normalized_query),
                library_id=library_id,
                document_ids=filters,
                limit=top_k,
            )
            return self._matches_for_unit_ids(
                session,
                unit_ids,
                library_id=library_id,
                document_ids=filters,
                limit=top_k,
                excerpt_query=normalized_query,
            )

    def retrieve(
        self,
        query: str,
        *,
        mode: str = "auto",
        document_ids: list[str] | None = None,
        top_k: int = 5,
        library_id: str = "global",
    ) -> KnowledgeRetrievalResult:
        normalized_query, filters = _validated_lookup(
            query,
            document_ids=document_ids,
            top_k=top_k,
        )
        normalized_mode = str(mode).strip().lower()
        if normalized_mode not in KNOWLEDGE_LOOKUP_MODES:
            raise ValidationError(
                "Knowledge retrieval mode must be auto, keyword, semantic, or hybrid."
            )
        def keyword_result() -> KnowledgeRetrievalResult:
            return KnowledgeRetrievalResult(
                mode="keyword",
                matches=self.lookup(
                    normalized_query,
                    document_ids=filters,
                    top_k=top_k,
                    library_id=library_id,
                ),
            )

        def unavailable_result(
            cause: BaseException | None = None,
        ) -> KnowledgeRetrievalResult:
            if normalized_mode == "auto":
                return keyword_result()
            failure = KnowledgeRetrievalUnavailable(
                requested_mode=normalized_mode,
                available_modes=["keyword"],
            )
            if cause is not None:
                raise failure from cause
            raise failure

        if normalized_mode == "keyword":
            return keyword_result()

        semantic = self._semantic_search
        semantic_ready = semantic is not None and semantic.is_configured()
        if not semantic_ready:
            return unavailable_result()

        candidate_k = min(
            _MAX_RETRIEVAL_CANDIDATES,
            max(20, top_k * 4),
        )
        try:
            assert semantic is not None
            semantic_candidates = semantic.search(
                normalized_query,
                library_id=library_id,
                limit=candidate_k,
            )
        except KnowledgeSemanticUnavailable as exc:
            return unavailable_result(exc)

        semantic_ids = list(semantic_candidates.unit_ids)

        if normalized_mode == "semantic":
            ranked_ids = list(dict.fromkeys(semantic_ids))
            resolved_mode = "semantic"
        else:
            keyword_ids = self._keyword_unit_ids(
                normalized_query,
                library_id=library_id,
                document_ids=filters,
                limit=candidate_k,
            )
            ranked_ids = _reciprocal_rank_fusion(
                keyword_ids,
                semantic_ids,
                limit=candidate_k,
            )
            resolved_mode = "hybrid"

        with self._session_factory() as session:
            matches = self._matches_for_unit_ids(
                session,
                ranked_ids,
                library_id=library_id,
                document_ids=filters,
                limit=top_k,
                excerpt_query=normalized_query,
            )
        try:
            semantic_current = semantic.is_current(
                semantic_candidates,
                library_id=library_id,
            )
        except KnowledgeSemanticUnavailable as exc:
            return unavailable_result(exc)
        if not semantic_current:
            return unavailable_result()
        return KnowledgeRetrievalResult(mode=resolved_mode, matches=matches)

    def _keyword_unit_ids(
        self,
        query: str,
        *,
        library_id: str,
        document_ids: list[str],
        limit: int,
    ) -> list[str]:
        with self._session_factory() as session:
            return self._repository.search_unit_ids(
                session,
                fts_query=_fts_query(query),
                library_id=library_id,
                document_ids=document_ids,
                limit=limit,
            )

    def _matches_for_unit_ids(
        self,
        session,
        unit_ids: list[str],
        *,
        library_id: str,
        document_ids: list[str],
        limit: int,
        excerpt_query: str,
    ) -> list[KnowledgeMatch]:
        units = self._repository.get_units(session, unit_ids)
        documents = self._repository.get_documents(
            session,
            [unit.document_id for unit in units],
        )
        allowed = set(document_ids)
        matches: list[KnowledgeMatch] = []
        for unit in units:
            document = documents.get(unit.document_id)
            if (
                document is None
                or not document.active
                or document.library_id != library_id
                or document.retrieval_status != "ready"
                or unit.canonical_generation_id != document.retrieval_generation_id
                or (allowed and document.id not in allowed)
            ):
                continue
            matches.append(
                KnowledgeMatch(
                    citation_id=f"knowledge:{unit.id}",
                    document_id=document.id,
                    document_generation_id=unit.canonical_generation_id,
                    source_artifact_id=document.source_artifact_id,
                    unit_id=unit.id,
                    title=document.title,
                    locator=dict(unit.locator_payload),
                    quote=_knowledge_excerpt(unit.text, excerpt_query),
                )
            )
            if len(matches) >= limit:
                break
        return matches


def _tokens(value: str) -> list[str]:
    tokens = [token.strip().lower() for token in jieba.cut_for_search(value) if token.strip()]
    return list(dict.fromkeys(tokens))


def _document_content_state(retrieval_status: str) -> str:
    if retrieval_status == "ready":
        return "ready"
    if retrieval_status == "unavailable":
        return "no_searchable_text"
    if retrieval_status in {"failed", "needs_attention"}:
        return "needs_attention"
    return "processing"


def prepare_knowledge_search_text(value: str) -> str:
    """Build the persisted CJK-aware FTS projection for a Knowledge Unit."""

    return " ".join(_tokens(value))


def _knowledge_excerpt(value: str, query: str) -> str:
    if len(value) <= MAX_KNOWLEDGE_QUOTE_CHARS:
        return value

    normalized_query = unicodedata.normalize("NFKC", query).strip().casefold()
    folded_value = value.casefold()
    match = folded_value.find(normalized_query) if normalized_query else -1
    match_length = len(normalized_query)
    if match < 0:
        token_matches = [
            (len(token), position)
            for token in _tokens(normalized_query)
            if (position := folded_value.find(token.casefold())) >= 0
        ]
        if token_matches:
            match_length, match = max(token_matches, key=lambda item: (item[0], -item[1]))
    if match < 0:
        return value[:MAX_KNOWLEDGE_QUOTE_CHARS]

    core_limit = MAX_KNOWLEDGE_QUOTE_CHARS - 2
    context_before = max(0, core_limit - match_length) // 3
    start = max(0, match - context_before)
    end = min(len(value), start + core_limit)
    if end == len(value):
        start = max(0, end - core_limit)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(value) else ""
    excerpt = prefix + value[start:end] + suffix
    return excerpt[:MAX_KNOWLEDGE_QUOTE_CHARS]


def bound_knowledge_units(units: Iterable[KnowledgeUnitInput]) -> list[KnowledgeUnitInput]:
    """Prepare and split retrievable projections without changing canonical content."""

    bounded: list[KnowledgeUnitInput] = []
    for unit in units:
        parts = _split_knowledge_unit_text(unit.text)
        part_count = len(parts)
        for index, part in enumerate(parts, start=1):
            locator = dict(unit.locator)
            if part_count > 1:
                locator["split_part"] = index
                locator["split_parts"] = part_count
            bounded.append(KnowledgeUnitInput(text=part, locator=locator))
    return bounded


def _split_knowledge_unit_text(value: str) -> list[str]:
    prepared = value.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not prepared:
        return []

    parts: list[str] = []
    remaining = prepared
    while remaining:
        raw_limit = _raw_prefix_with_normalized_budget(
            remaining,
            MAX_KNOWLEDGE_UNIT_CHARS,
        )
        if raw_limit >= len(remaining):
            parts.append(remaining)
            break
        boundary = _preferred_split_boundary(remaining, raw_limit)
        part = remaining[:boundary].strip()
        if part:
            parts.append(part)
        remaining = remaining[boundary:].strip()
    return parts


def _raw_prefix_with_normalized_budget(value: str, budget: int) -> int:
    """Conservatively bound the NFKC text sent by every embedding adapter."""

    normalized_characters = 0
    for index, character in enumerate(value):
        normalized_characters += len(unicodedata.normalize("NFKC", character))
        if normalized_characters > budget:
            return max(1, index)
    return len(value)


def _preferred_split_boundary(value: str, limit: int) -> int:
    lower_bound = max(1, limit // 2)
    window = value[:limit]
    for delimiter in ("\n\n", "\n", "。", "！", "？", ". ", "! ", "? ", "；", "; ", "，", ", ", " "):
        position = window.rfind(delimiter, lower_bound)
        if position >= 0:
            return min(limit, position + len(delimiter))
    return limit


def _fts_query(value: str) -> str:
    tokens = _tokens(value)
    if not tokens:
        raise ValidationError("Knowledge query has no searchable terms.")
    return " OR ".join('"' + token.replace('"', '""') + '"' for token in tokens)


def _validated_lookup(
    query: str,
    *,
    document_ids: list[str] | None,
    top_k: int,
) -> tuple[str, list[str]]:
    normalized_query = query.strip()
    if not normalized_query:
        raise ValidationError("Knowledge query is required.")
    if len(normalized_query) > MAX_KNOWLEDGE_QUERY_CHARS:
        raise ValidationError(
            f"Knowledge query must not exceed {MAX_KNOWLEDGE_QUERY_CHARS} characters."
        )
    if not 1 <= top_k <= MAX_KNOWLEDGE_TOP_K:
        raise ValidationError(f"top_k must be between 1 and {MAX_KNOWLEDGE_TOP_K}.")
    filters = list(dict.fromkeys(document_ids or ()))
    if len(filters) > 16:
        raise ValidationError("document_ids must contain at most 16 ids.")
    return normalized_query, filters


def _reciprocal_rank_fusion(
    keyword_ids: list[str],
    semantic_ids: list[str],
    *,
    limit: int,
) -> list[str]:
    scores: dict[str, float] = {}
    best_ranks: dict[str, int] = {}
    for ranking in (keyword_ids, semantic_ids):
        for rank, unit_id in enumerate(dict.fromkeys(ranking), start=1):
            scores[unit_id] = scores.get(unit_id, 0.0) + 1.0 / (_HYBRID_RRF_K + rank)
            best_ranks[unit_id] = min(best_ranks.get(unit_id, rank), rank)
    ordered = sorted(
        scores,
        key=lambda unit_id: (-scores[unit_id], best_ranks[unit_id], unit_id),
    )
    return ordered[:limit]
