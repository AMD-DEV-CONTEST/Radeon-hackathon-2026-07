"""Markdown parser preserving heading hierarchy."""

from __future__ import annotations

import re
from pathlib import Path

from buildguard.rag.parsers.base import (
    DocumentParser,
    extract_article,
    extract_chapter,
    extract_effective_date,
    file_checksum,
)
from buildguard.rag.schemas import ParsedDocument, ParsedSection

HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


class MarkdownParser(DocumentParser):
    extensions = frozenset({".md", ".markdown"})

    def parse(self, path: Path) -> ParsedDocument:
        source = self.validate_path(path)
        checksum = file_checksum(source)
        text = source.read_text(encoding="utf-8")
        effective_date = extract_effective_date(text)
        headings: dict[int, str] = {}
        sections: list[ParsedSection] = []
        buffer: list[str] = []

        def emit() -> None:
            content = "\n".join(buffer).strip()
            if not content:
                return
            title = headings[max(headings)] if headings else None
            chapter = next(
                (
                    extract_chapter(headings[level])
                    for level in sorted(headings)
                    if extract_chapter(headings[level])
                ),
                None,
            )
            sections.append(
                ParsedSection(
                    document_name=source.name,
                    source_path=source,
                    chapter=chapter or extract_chapter(content),
                    article=extract_article(content),
                    title=title,
                    content=content,
                    effective_date=effective_date,
                    checksum=checksum,
                )
            )

        for line in text.splitlines():
            match = HEADING.match(line)
            if match:
                emit()
                buffer.clear()
                level = len(match.group(1))
                headings = {key: value for key, value in headings.items() if key < level}
                headings[level] = match.group(2).strip()
            elif line.strip():
                buffer.append(line.strip())
            elif buffer:
                emit()
                buffer.clear()
        emit()
        return ParsedDocument(
            document_name=source.name,
            source_path=source,
            checksum=checksum,
            sections=sections,
            warnings=[] if sections else ["Markdown document contains no content"],
        )
