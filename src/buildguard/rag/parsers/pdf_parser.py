"""PDF parser with page metadata and no implicit OCR."""

from __future__ import annotations

import logging
import re
from collections import Counter
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from buildguard.rag.parsers.base import (
    DocumentParser,
    extract_article,
    extract_chapter,
    extract_effective_date,
    file_checksum,
)
from buildguard.rag.schemas import ParsedDocument, ParsedSection

LOGGER = logging.getLogger(__name__)
_TABLE_SEPARATOR = re.compile(r"(?:\t+|\s{3,})")


def _extract_page_text(page: Any) -> str:
    """Prefer pypdf's positional layout while supporting older pypdf versions."""
    try:
        return str(page.extract_text(extraction_mode="layout") or "")
    except (KeyError, TypeError):
        return str(page.extract_text() or "")


def _table_cells(line: str) -> list[str] | None:
    cells = [cell.strip() for cell in _TABLE_SEPARATOR.split(line.strip())]
    cells = [cell for cell in cells if cell]
    return cells if len(cells) >= 2 else None


def split_layout_blocks(lines: list[str]) -> list[tuple[bool, list[str]]]:
    """Split page text into prose and tabular blocks without inventing table cells.

    A table needs at least two consecutive rows separated by tabs or positional
    whitespace. Isolated aligned text remains prose to avoid false positives.
    """
    classified = [(_table_cells(line), line.strip()) for line in lines if line.strip()]
    blocks: list[tuple[bool, list[str]]] = []
    index = 0
    while index < len(classified):
        cells, _ = classified[index]
        end = index + 1
        while end < len(classified) and (classified[end][0] is not None) == (
            cells is not None
        ):
            end += 1
        run = classified[index:end]
        is_table = cells is not None and len(run) >= 2
        rendered = [
            " | ".join(row_cells) if is_table and row_cells is not None else text
            for row_cells, text in run
        ]
        if blocks and not is_table and not blocks[-1][0]:
            blocks[-1][1].extend(rendered)
        else:
            blocks.append((is_table, rendered))
        index = end
    return blocks


class PdfParser(DocumentParser):
    extensions = frozenset({".pdf"})

    def parse(self, path: Path) -> ParsedDocument:
        source = self.validate_path(path)
        checksum = file_checksum(source)
        reader = PdfReader(source)
        pages = [_extract_page_text(page).strip() for page in reader.pages]
        first_lines = Counter(
            text.splitlines()[0].strip() for text in pages if text and text.splitlines()
        )
        last_lines = Counter(
            text.splitlines()[-1].strip() for text in pages if text and text.splitlines()
        )
        repeated = {
            line
            for line, count in (*first_lines.items(), *last_lines.items())
            if line and count > 1
        }
        effective_date = extract_effective_date("\n".join(pages))
        sections: list[ParsedSection] = []
        warnings: list[str] = []
        for page_number, raw_text in enumerate(pages, start=1):
            if not raw_text:
                warning = f"Page {page_number} contains no extractable text; OCR was not run"
                warnings.append(warning)
                LOGGER.warning("%s: %s", source, warning)
                continue
            lines = [line for line in raw_text.splitlines() if line.strip()]
            filtered = [line for line in lines if line.strip() not in repeated]
            for is_table, block_lines in split_layout_blocks(filtered):
                content = "\n".join(block_lines).strip()
                if not content:
                    continue
                sections.append(
                    ParsedSection(
                        document_name=source.name,
                        source_path=source,
                        page=page_number,
                        chapter=extract_chapter(content),
                        article=extract_article(content),
                        content=content,
                        effective_date=effective_date,
                        checksum=checksum,
                        is_table=is_table,
                        table_header=block_lines[0] if is_table else None,
                    )
                )
        return ParsedDocument(
            document_name=source.name,
            source_path=source,
            checksum=checksum,
            sections=sections,
            warnings=warnings,
        )
