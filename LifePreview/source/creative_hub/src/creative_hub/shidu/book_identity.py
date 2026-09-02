"""Deterministic Book identity normalization."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass


_WHITESPACE = re.compile(r"\s+")
_TITLE_WRAPPERS = (("《", "》"), ("〈", "〉"), ('"', '"'), ("'", "'"))


@dataclass(frozen=True)
class BookIdentity:
    title: str
    author: str
    language: str
    edition: str
    translator: str
    identity_digest: str

    @property
    def digest(self) -> str:
        return self.identity_digest


def _normalize_text(value: str, field: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string")
    return _WHITESPACE.sub(" ", unicodedata.normalize("NFKC", value)).strip()


def normalize_book_title(value: str) -> str:
    title = _normalize_text(value, "title")
    for opening, closing in _TITLE_WRAPPERS:
        if title.startswith(opening) and title.endswith(closing):
            title = title[len(opening) : -len(closing)].strip()
            break
    return title.casefold()


def normalize_book_identity(
    title: str,
    author: str,
    language: str,
    edition: str,
    translator: str,
) -> BookIdentity:
    """Normalize all five identity dimensions and digest the complete tuple."""

    normalized_title = normalize_book_title(title)
    normalized_author = _normalize_text(author, "author").casefold()
    normalized_language = (
        _normalize_text(language, "language").replace("_", "-").casefold()
    )
    normalized_edition = _normalize_text(edition, "edition").casefold()
    normalized_translator = _normalize_text(translator, "translator").casefold()
    if not normalized_title:
        raise ValueError("title is required")
    if not normalized_author:
        raise ValueError("author is required")
    if not normalized_language:
        raise ValueError("language is required")

    payload = {
        "author": normalized_author,
        "edition": normalized_edition,
        "language": normalized_language,
        "title": normalized_title,
        "translator": normalized_translator,
    }
    digest = hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    return BookIdentity(
        title=normalized_title,
        author=normalized_author,
        language=normalized_language,
        edition=normalized_edition,
        translator=normalized_translator,
        identity_digest=digest,
    )


__all__ = ["BookIdentity", "normalize_book_identity", "normalize_book_title"]

