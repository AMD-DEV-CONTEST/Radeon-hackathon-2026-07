"""Resolve human Book input without collapsing ambiguous titles."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from .book_identity import normalize_book_identity, normalize_book_title
from .schemas import Book


_KEY_VALUE = re.compile(
    r"(?:^|[;,；])\s*(title|author|language|edition|translator)\s*[:=：]\s*([^;,；]*)",
    re.IGNORECASE,
)


class BookLookup(Protocol):
    def find_books_by_title(
        self,
        normalized_title: str,
        *,
        project_id: UUID | None = None,
    ) -> tuple[Book, ...]: ...


@dataclass(frozen=True)
class InputResolutionDraft:
    raw_input: str
    title: str
    author: str | None
    language: str | None
    edition: str | None
    translator: str | None
    candidate_book_ids: tuple[UUID, ...]
    book_id: UUID | None
    identity_digest: str | None
    requires_confirmation: bool


class InputResolver:
    def __init__(
        self,
        books: BookLookup | Iterable[Book] | None = None,
        *,
        book_lookup: Callable[[str], Iterable[Book]] | None = None,
        project_id: UUID | None = None,
    ) -> None:
        if books is not None and book_lookup is not None:
            raise ValueError("provide books or book_lookup, not both")
        if book_lookup is not None:
            self._lookup = lambda title: tuple(book_lookup(title))
        elif books is not None and hasattr(books, "find_books_by_title"):
            if project_id is None:
                raise ValueError(
                    "project_id is required for repository Book lookup"
                )
            self._lookup = lambda title: books.find_books_by_title(
                title, project_id=project_id
            )
        else:
            snapshot = tuple(books or ())
            self._lookup = lambda title: tuple(
                book
                for book in snapshot
                if normalize_book_title(book.title) == title
            )

    @staticmethod
    def _parse(
        raw_input: str,
    ) -> tuple[str, str | None, str | None, str | None, str | None, bool]:
        value = raw_input.strip()
        keyed = {
            key.casefold(): item.strip()
            for key, item in _KEY_VALUE.findall(value)
        }
        required_keys = {"title", "author", "language", "edition", "translator"}
        if required_keys <= keyed.keys():
            return (
                keyed["title"],
                keyed["author"],
                keyed["language"],
                keyed["edition"],
                keyed["translator"],
                True,
            )

        parts = [item.strip() for item in value.replace("｜", "|").split("|")]
        if len(parts) == 5:
            return (*parts, True)
        return value, None, None, None, None, False

    def resolve(self, raw_input: str) -> InputResolutionDraft:
        if not isinstance(raw_input, str):
            raise TypeError("raw_input must be a string")
        if not raw_input.strip():
            raise ValueError("raw_input is required")
        title, author, language, edition, translator, complete = self._parse(
            raw_input
        )
        normalized_title = normalize_book_title(title)
        if not normalized_title:
            raise ValueError("title is required")
        candidates = tuple(self._lookup(normalized_title))

        if not complete:
            return InputResolutionDraft(
                raw_input=raw_input,
                title=normalized_title,
                author=None,
                language=None,
                edition=None,
                translator=None,
                candidate_book_ids=tuple(book.id for book in candidates),
                book_id=None,
                identity_digest=None,
                requires_confirmation=True,
            )

        identity = normalize_book_identity(
            title, author, language, edition, translator
        )
        exact = tuple(
            book for book in candidates if book.identity_digest == identity.digest
        )
        if len(exact) > 1:
            raise RuntimeError("duplicate Book identity records")
        return InputResolutionDraft(
            raw_input=raw_input,
            title=identity.title,
            author=identity.author,
            language=identity.language,
            edition=identity.edition,
            translator=identity.translator,
            candidate_book_ids=tuple(book.id for book in (exact or candidates)),
            book_id=exact[0].id if exact else None,
            identity_digest=identity.digest,
            requires_confirmation=False,
        )


__all__ = ["BookLookup", "InputResolutionDraft", "InputResolver"]
