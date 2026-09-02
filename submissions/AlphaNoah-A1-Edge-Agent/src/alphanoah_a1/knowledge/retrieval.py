"""Stable contracts for bounded knowledge retrieval."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence

from .models import KnowledgeDocument


@dataclass(frozen=True, slots=True)
class KnowledgeQuery:
    """Structured, bounded query built from stable Event fields."""

    event_type: str = ""
    asset_id: str = ""
    asset_type: str = ""
    location: str = ""
    keywords: tuple[str, ...] = ()
    limit: int = 5

    def __post_init__(self) -> None:
        for field_name in (
            "event_type",
            "asset_id",
            "asset_type",
            "location",
        ):
            value = getattr(self, field_name)
            if (
                not isinstance(value, str)
                or value != value.strip()
                or "\x00" in value
                or len(value) > 300
            ):
                raise ValueError(
                    f"{field_name} must be a trimmed string "
                    "of at most 300 characters"
                )
        if isinstance(self.keywords, (str, bytes)):
            raise ValueError("keywords must be an iterable of strings")
        normalized_keywords: list[str] = []
        for keyword in self.keywords:
            if not isinstance(keyword, str):
                raise ValueError("keywords must contain only strings")
            folded = keyword.strip().casefold()
            if "\x00" in folded or len(folded) > 100:
                raise ValueError(
                    "knowledge query keywords must be at most 100 characters"
                )
            if len(folded) >= 2 and folded not in normalized_keywords:
                normalized_keywords.append(folded)
            if len(normalized_keywords) >= 30:
                break
        if (
            isinstance(self.limit, bool)
            or not isinstance(self.limit, int)
            or not 1 <= self.limit <= 20
        ):
            raise ValueError("query limit must be an integer between 1 and 20")
        object.__setattr__(self, "keywords", tuple(normalized_keywords))


@dataclass(frozen=True, slots=True)
class KnowledgeMatch:
    """One deterministic result with explainable matching evidence."""

    document: KnowledgeDocument
    score: int
    matched_fields: tuple[str, ...] = ()
    matched_keywords: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.document, KnowledgeDocument):
            raise TypeError("knowledge match document is invalid")
        if (
            isinstance(self.score, bool)
            or not isinstance(self.score, int)
            or self.score <= 0
        ):
            raise ValueError("knowledge match score must be a positive integer")
        for values, field_name in (
            (self.matched_fields, "matched_fields"),
            (self.matched_keywords, "matched_keywords"),
        ):
            if isinstance(values, (str, bytes)):
                raise ValueError(
                    f"knowledge match {field_name} must contain strings"
                )
            normalized_values = tuple(values)
            if any(
                not isinstance(value, str) or not value
                for value in normalized_values
            ):
                raise ValueError(
                    f"knowledge match {field_name} must contain strings"
                )
            object.__setattr__(self, field_name, normalized_values)


class KnowledgeRetriever(Protocol):
    """Replaceable retrieval boundary consumed by ContextBuilder."""

    def retrieve(
        self,
        query: KnowledgeQuery,
    ) -> Sequence[KnowledgeMatch]:
        """Return bounded matches in deterministic order."""

        ...
