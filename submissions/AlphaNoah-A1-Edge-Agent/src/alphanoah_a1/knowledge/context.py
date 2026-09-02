"""Deterministic Event-to-KnowledgeContext construction."""

from __future__ import annotations

import re
from typing import Any

from ..models import Event
from ..skill import SkillContext
from .models import KnowledgeContext
from .retrieval import KnowledgeMatch, KnowledgeQuery, KnowledgeRetriever

_KEYWORD_PATTERN = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9_:-]{1,63}|[\u3400-\u9fff]{2,32}"
)
_IGNORED_KEYWORDS = frozenset(
    {
        "incident",
        "issue",
        "observation",
        "report",
        "signal",
        "synthetic",
    }
)


class ContextBuilder:
    """Select bounded knowledge by reviewed fields and lexical signals."""

    def __init__(
        self,
        retriever: KnowledgeRetriever,
        *,
        max_documents: int = 5,
        max_context_characters: int = 40_000,
    ):
        if (
            isinstance(max_documents, bool)
            or not isinstance(max_documents, int)
            or not 1 <= max_documents <= 10
        ):
            raise ValueError("max_documents must be between 1 and 10")
        if (
            isinstance(max_context_characters, bool)
            or not isinstance(max_context_characters, int)
            or not 1_000 <= max_context_characters <= 100_000
        ):
            raise ValueError(
                "max_context_characters must be between 1000 and 100000"
            )
        if not callable(getattr(retriever, "retrieve", None)):
            raise TypeError("retriever must implement retrieve")
        self.retriever = retriever
        self.max_documents = max_documents
        self.max_context_characters = max_context_characters

    def build(
        self,
        event: Event,
        *,
        skill_context: SkillContext | None = None,
    ) -> KnowledgeContext:
        """Build one context without mutating or persisting the Event."""

        if not isinstance(event, Event):
            raise TypeError("context builder requires an Event")
        if skill_context is not None and not isinstance(
            skill_context,
            SkillContext,
        ):
            raise TypeError("skill_context must be a SkillContext")
        asset_type = self._metadata_text(event.metadata, "asset_type")
        keywords = (
            list(skill_context.knowledge_query_hints)
            if skill_context is not None
            else []
        )
        keywords.extend(self._event_keywords(event))
        matches = self.retriever.retrieve(
            KnowledgeQuery(
                event_type=event.event_type,
                asset_id=event.asset_id,
                asset_type=asset_type,
                location=event.location,
                keywords=tuple(keywords),
                limit=self.max_documents,
            )
        )
        selected = []
        character_count = 0
        for match in matches:
            if len(selected) >= self.max_documents:
                break
            if not isinstance(match, KnowledgeMatch):
                raise TypeError(
                    "retriever must return KnowledgeMatch objects"
                )
            document = match.document
            projected_size = (
                len(document.title)
                + len(document.content)
                + len(document.source)
                + len(document.version)
            )
            if character_count + projected_size > self.max_context_characters:
                continue
            selected.append(document)
            character_count += projected_size
        return KnowledgeContext(documents=tuple(selected))

    @staticmethod
    def _event_keywords(event: Event) -> tuple[str, ...]:
        values = [
            event.event_type.replace("_", " "),
            event.description,
            event.location,
        ]
        explicit_keywords = event.metadata.get("keywords")
        if isinstance(explicit_keywords, list):
            values.extend(
                value for value in explicit_keywords if isinstance(value, str)
            )
        keywords: list[str] = []
        for value in values:
            for match in _KEYWORD_PATTERN.findall(value):
                for keyword in ContextBuilder._keyword_candidates(match):
                    if (
                        keyword not in _IGNORED_KEYWORDS
                        and keyword not in keywords
                    ):
                        keywords.append(keyword)
                    if len(keywords) >= 30:
                        return tuple(keywords)
        return tuple(keywords)

    @staticmethod
    def _keyword_candidates(match: str) -> tuple[str, ...]:
        folded = match.casefold()
        if not all("\u3400" <= character <= "\u9fff" for character in match):
            return (folded,)
        candidates = [folded]
        for size in range(2, min(4, len(match)) + 1):
            candidates.extend(
                match[index : index + size]
                for index in range(len(match) - size + 1)
            )
        return tuple(candidates)

    @staticmethod
    def _metadata_text(metadata: dict[str, Any], field_name: str) -> str:
        value = metadata.get(field_name)
        return value.strip() if isinstance(value, str) else ""
