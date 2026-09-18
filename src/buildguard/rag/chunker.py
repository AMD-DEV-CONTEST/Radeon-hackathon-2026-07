"""Structure-aware deterministic document chunking."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from buildguard.rag.parsers.base import ARTICLE_PATTERN
from buildguard.rag.schemas import DocumentChunk, ParsedDocument, ParsedSection

SENTENCE_BOUNDARY = re.compile(r"(?<=[。！？；\n])")


@dataclass(frozen=True)
class ChunkingOptions:
    min_chars: int = 300
    max_chars: int = 700
    overlap_chars: int = 60

    def __post_init__(self) -> None:
        if self.min_chars <= 0 or self.max_chars < self.min_chars:
            raise ValueError("Invalid chunk size range")
        if not 0 <= self.overlap_chars < self.min_chars:
            raise ValueError("Overlap must be non-negative and smaller than min_chars")


def _article_sections(section: ParsedSection) -> list[ParsedSection]:
    matches = list(ARTICLE_PATTERN.finditer(section.content))
    if len(matches) <= 1:
        return [section]
    parts: list[ParsedSection] = []
    if matches[0].start() > 0:
        preamble = section.content[: matches[0].start()].strip()
        if preamble:
            parts.append(section.model_copy(update={"content": preamble, "article": None}))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(section.content)
        content = section.content[match.start() : end].strip()
        if content:
            parts.append(section.model_copy(update={"content": content, "article": match.group(0)}))
    return parts


def _split_long(text: str, maximum: int, overlap: int, header: str | None) -> list[str]:
    prefix = f"{header}\n" if header else ""
    available = maximum - len(prefix)
    if available <= 0:
        raise ValueError("Table header is longer than maximum chunk size")
    sentences = [item for item in SENTENCE_BOUNDARY.split(text) if item]
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        while len(sentence) > available:
            if current:
                chunks.append(prefix + current.strip())
                current = ""
            chunks.append(prefix + sentence[:available].strip())
            sentence = sentence[max(1, available - overlap) :]
        if len(current) + len(sentence) > available and current:
            chunks.append(prefix + current.strip())
            tail = current[-overlap:] if overlap else ""
            current = tail + sentence
        else:
            current += sentence
    if current.strip():
        chunks.append(prefix + current.strip())
    return chunks


def _stable_id(section: ParsedSection, content: str, ordinal: int) -> str:
    material = "|".join(
        [
            section.checksum,
            str(section.page or ""),
            section.chapter or "",
            section.article or "",
            section.title or "",
            str(ordinal),
            content,
        ]
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


class StructureAwareChunker:
    def __init__(self, options: ChunkingOptions) -> None:
        self.options = options

    def chunk(self, document: ParsedDocument, project: str | None = None) -> list[DocumentChunk]:
        expanded = [
            part
            for section in document.sections
            for part in _article_sections(section)
        ]
        chunks: list[DocumentChunk] = []
        pending: ParsedSection | None = None
        pending_content = ""

        def emit(section: ParsedSection, content: str) -> None:
            pieces = _split_long(
                content,
                self.options.max_chars,
                self.options.overlap_chars,
                section.table_header if section.is_table else None,
            )
            for piece in pieces:
                ordinal = len(chunks)
                chunks.append(
                    DocumentChunk(
                        chunk_id=_stable_id(section, piece, ordinal),
                        document_name=section.document_name,
                        source_path=section.source_path,
                        document_checksum=section.checksum,
                        page=section.page,
                        chapter=section.chapter,
                        article=section.article,
                        title=section.title,
                        content=piece,
                        effective_date=section.effective_date,
                        project=project,
                        metadata={"is_table": section.is_table},
                    )
                )

        for section in expanded:
            structural_key = (
                section.page,
                section.chapter,
                section.article,
                section.title,
                section.is_table,
            )
            pending_key = (
                pending.page,
                pending.chapter,
                pending.article,
                pending.title,
                pending.is_table,
            ) if pending else None
            addition = section.content if not pending_content else f"\n{section.content}"
            if (
                pending is not None
                and structural_key == pending_key
                and len(pending_content) + len(addition) <= self.options.max_chars
            ):
                pending_content += addition
                continue
            if pending is not None:
                emit(pending, pending_content)
            pending = section
            pending_content = section.content
        if pending is not None:
            emit(pending, pending_content)
        return chunks

