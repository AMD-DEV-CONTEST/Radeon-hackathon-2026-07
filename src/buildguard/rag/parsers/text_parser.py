"""Plain-text standards parser."""

from pathlib import Path

from buildguard.rag.parsers.base import (
    DocumentParser,
    extract_article,
    extract_chapter,
    extract_effective_date,
    file_checksum,
)
from buildguard.rag.schemas import ParsedDocument, ParsedSection


class TextParser(DocumentParser):
    extensions = frozenset({".txt"})

    def parse(self, path: Path) -> ParsedDocument:
        source = self.validate_path(path)
        checksum = file_checksum(source)
        text = source.read_text(encoding="utf-8")
        paragraphs = [item.strip() for item in text.split("\n\n") if item.strip()]
        effective_date = extract_effective_date(text)
        sections = [
            ParsedSection(
                document_name=source.name,
                source_path=source,
                chapter=extract_chapter(paragraph),
                article=extract_article(paragraph),
                content=paragraph,
                effective_date=effective_date,
                checksum=checksum,
            )
            for paragraph in paragraphs
        ]
        return ParsedDocument(
            document_name=source.name,
            source_path=source,
            checksum=checksum,
            sections=sections,
            warnings=[] if sections else ["Document contains no non-empty paragraphs"],
        )

