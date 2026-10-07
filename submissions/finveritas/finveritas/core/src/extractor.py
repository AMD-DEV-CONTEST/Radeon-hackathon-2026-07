"""
PDF text and table extraction using *pdfplumber*.

Handles text-based PDFs natively.  For scanned/image-based PDFs the module
logs a warning — OCR integration (e.g. Tesseract) can be added later without
changing the public API.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pdfplumber

logger = logging.getLogger(__name__)


@dataclass
class PageData:
    """Extracted content from a single PDF page."""

    page_number: int
    text: str = ""
    tables: list[list[list[str | None]]] = field(default_factory=list)


@dataclass
class PDFContent:
    """Aggregated content from an entire PDF file."""

    path: Path
    pages: list[PageData] = field(default_factory=list)

    @property
    def full_text(self) -> str:
        return "\n".join(p.text for p in self.pages)

    @property
    def all_tables(self) -> list[list[list[str | None]]]:
        tables: list[list[list[str | None]]] = []
        for p in self.pages:
            tables.extend(p.tables)
        return tables


# ── pdfplumber table-extraction settings tuned for Bloomberg layouts ─────
_TABLE_SETTINGS: dict[str, Any] = {
    "vertical_strategy": "lines",
    "horizontal_strategy": "lines",
    "snap_x_tolerance": 5,
    "snap_y_tolerance": 5,
    "join_x_tolerance": 5,
    "join_y_tolerance": 5,
}

# Fallback: more permissive strategy when strict line-based extraction
# yields no tables (common with Bloomberg exports that use spacing instead
# of drawn lines).
_TABLE_SETTINGS_FALLBACK: dict[str, Any] = {
    "vertical_strategy": "text",
    "horizontal_strategy": "text",
    "snap_x_tolerance": 5,
    "snap_y_tolerance": 5,
    "min_words_vertical": 2,
    "min_words_horizontal": 2,
}


def extract_pdf(path: Path) -> PDFContent:
    """Extract text and tables from *path* using pdfplumber.

    Parameters
    ----------
    path:
        Path to the PDF file.

    Returns
    -------
    PDFContent
        Structured extraction result.
    """
    content = PDFContent(path=path)

    try:
        with pdfplumber.open(path) as pdf:
            for idx, page in enumerate(pdf.pages):
                page_data = PageData(page_number=idx + 1)

                # --- text extraction ---
                text = page.extract_text() or ""
                page_data.text = text

                if not text.strip():
                    logger.warning(
                        "Page %d of %s has no extractable text — "
                        "PDF may be scanned/image-based.",
                        idx + 1,
                        path.name,
                    )

                # --- table extraction ---
                tables = page.extract_tables(table_settings=_TABLE_SETTINGS)
                if not tables:
                    tables = page.extract_tables(
                        table_settings=_TABLE_SETTINGS_FALLBACK
                    )
                page_data.tables = tables or []

                content.pages.append(page_data)

    except Exception:
        logger.exception("Failed to open/extract PDF: %s", path)

    return content
