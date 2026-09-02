"""Deterministic metadata and lexical knowledge retrieval."""

from __future__ import annotations

from typing import Any, Mapping

from .models import KnowledgeDocument, KnowledgeDocumentStatus
from .repository import KnowledgeRepository
from .retrieval import KnowledgeMatch, KnowledgeQuery


class DeterministicKnowledgeRetriever:
    """Filter explicit conflicts, score matches and apply a stable Top-K."""

    def __init__(self, repository: KnowledgeRepository):
        self.repository = repository

    def retrieve(self, query: KnowledgeQuery) -> list[KnowledgeMatch]:
        if not isinstance(query, KnowledgeQuery):
            raise TypeError("query must be a KnowledgeQuery")
        matches: list[KnowledgeMatch] = []
        for document in self.repository.list_documents():
            if document.status is not KnowledgeDocumentStatus.ACTIVE:
                continue
            if self._has_structured_conflict(document, query):
                continue
            score, fields, keywords = self._score(document, query)
            if score > 0:
                matches.append(
                    KnowledgeMatch(
                        document=document,
                        score=score,
                        matched_fields=fields,
                        matched_keywords=keywords,
                    )
                )
        matches.sort(key=lambda match: (-match.score, match.document.id))
        return matches[: query.limit]

    @staticmethod
    def _score(
        document: KnowledgeDocument,
        query: KnowledgeQuery,
    ) -> tuple[int, tuple[str, ...], tuple[str, ...]]:
        metadata = document.metadata
        score = 0
        matched_fields: list[str] = []
        structured_scores = (
            ("event_type", "event_types", query.event_type, 100, False),
            ("asset_id", "asset_ids", query.asset_id, 120, True),
            ("asset_type", "asset_types", query.asset_type, 80, False),
            ("location", "locations", query.location, 60, False),
        )
        for (
            field_name,
            metadata_field,
            query_value,
            field_score,
            case_sensitive,
        ) in structured_scores:
            if (
                query_value
                and DeterministicKnowledgeRetriever._metadata_contains(
                    metadata,
                    metadata_field,
                    query_value,
                    case_sensitive=case_sensitive,
                )
            ):
                score += field_score
                matched_fields.append(field_name)

        title = document.title.casefold()
        content = document.content.casefold()
        metadata_keywords = {
            value.casefold()
            for value in DeterministicKnowledgeRetriever._metadata_strings(
                metadata,
                "keywords",
            )
        }
        matched_keywords: list[str] = []
        for keyword in query.keywords:
            keyword_score = 0
            if keyword in metadata_keywords:
                keyword_score += 30
            if keyword in title:
                keyword_score += 10
            if keyword in content:
                keyword_score += 2
            if keyword_score:
                score += keyword_score
                matched_keywords.append(keyword)
        return score, tuple(matched_fields), tuple(matched_keywords)

    @staticmethod
    def _has_structured_conflict(
        document: KnowledgeDocument,
        query: KnowledgeQuery,
    ) -> bool:
        checks = (
            ("event_types", query.event_type, False),
            ("asset_ids", query.asset_id, True),
            ("asset_types", query.asset_type, False),
            ("locations", query.location, False),
        )
        for metadata_field, query_value, case_sensitive in checks:
            declared_values = (
                DeterministicKnowledgeRetriever._metadata_strings(
                    document.metadata,
                    metadata_field,
                )
            )
            if (
                query_value
                and declared_values
                and not DeterministicKnowledgeRetriever._value_in(
                    declared_values,
                    query_value,
                    case_sensitive=case_sensitive,
                )
            ):
                return True
        return False

    @staticmethod
    def _metadata_contains(
        metadata: Mapping[str, Any],
        field_name: str,
        expected: str,
        *,
        case_sensitive: bool,
    ) -> bool:
        values = DeterministicKnowledgeRetriever._metadata_strings(
            metadata,
            field_name,
        )
        return DeterministicKnowledgeRetriever._value_in(
            values,
            expected,
            case_sensitive=case_sensitive,
        )

    @staticmethod
    def _value_in(
        values: tuple[str, ...],
        expected: str,
        *,
        case_sensitive: bool,
    ) -> bool:
        if case_sensitive:
            return expected in values
        expected_folded = expected.casefold()
        return any(value.casefold() == expected_folded for value in values)

    @staticmethod
    def _metadata_strings(
        metadata: Mapping[str, Any],
        field_name: str,
    ) -> tuple[str, ...]:
        value = metadata.get(field_name)
        if not isinstance(value, list):
            return ()
        return tuple(item for item in value if isinstance(item, str) and item)
