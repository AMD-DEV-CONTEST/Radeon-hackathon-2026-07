"""Document parser contract and metadata helpers."""

from __future__ import annotations

import hashlib
import re
from abc import ABC, abstractmethod
from datetime import date
from pathlib import Path

from buildguard.rag.schemas import ParsedDocument

DATE_PATTERN = re.compile(r"(20\d{2})[年\-/](\d{1,2})[月\-/](\d{1,2})日?")
ARTICLE_PATTERN = re.compile(r"第[一二三四五六七八九十百千万零〇\d]+条")
CHAPTER_PATTERN = re.compile(r"第[一二三四五六七八九十百千万零〇\d]+章")


def file_checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def extract_effective_date(text: str) -> date | None:
    match = DATE_PATTERN.search(text)
    if not match:
        return None
    try:
        return date(*(int(value) for value in match.groups()))
    except ValueError:
        return None


def extract_article(text: str) -> str | None:
    match = ARTICLE_PATTERN.search(text)
    return match.group(0) if match else None


def extract_chapter(text: str) -> str | None:
    match = CHAPTER_PATTERN.search(text)
    return match.group(0) if match else None


class DocumentParser(ABC):
    extensions: frozenset[str]

    @abstractmethod
    def parse(self, path: Path) -> ParsedDocument:
        """Parse a local document without downloading or OCR."""

    def validate_path(self, path: Path) -> Path:
        resolved = path.resolve()
        if not resolved.is_file():
            raise FileNotFoundError(f"Document does not exist: {resolved}")
        if resolved.suffix.lower() not in self.extensions:
            raise ValueError(f"Unsupported extension for {type(self).__name__}: {resolved.suffix}")
        return resolved

