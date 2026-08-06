"""Document ingestion — the front door for text, PDFs, and structured files.

Every document that enters VEIL passes through here and is decomposed into:
  1. plain text (for prompt construction)
  2. a set of located Spans (so findings can cite offsets and pages)
  3. optionally, a set of corpus chunks (for the auxiliary RAG store)

PDFs and .docx are natively supported. Everything else is converted to text
via markitdown and treated as a single body span with page=None.
"""
from __future__ import annotations

import re
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from veil.types import Span


def load_pdf(path: str) -> tuple[str, list[Span]]:
    import pdfplumber

    parts: list[str] = []
    spans: list[Span] = []
    offset = 0

    with pdfplumber.open(path) as pdf:
        for pno, page in enumerate(pdf.pages, start=1):
            text = (page.extract_text() or "").strip()
            if text:
                parts.append(text)
                spans.append(
                    Span(
                        start=offset,
                        end=offset + len(text),
                        text=text,
                        page=pno,
                        source="body",
                    )
                )
                offset += len(text) + 1
                parts.append("\n")
                offset += 1

    return "".join(parts).strip(), spans


def load_docx(path: str) -> tuple[str, list[Span]]:
    with zipfile.ZipFile(path) as z:
        root = ElementTree.fromstring(z.read("word/document.xml"))

    parts: list[str] = []
    for el in root.iter():
        if el.tag.endswith("}t") and el.text:
            parts.append(el.text)
        elif el.tag.endswith("}br"):
            parts.append("\n")

    text = "".join(parts).strip()
    spans = [Span(start=0, end=len(text), text=text, page=None, source="body")]
    return text, spans


def load_text(path: str) -> tuple[str, list[Span]]:
    """Fallback for .txt, .md, or anything else plain."""
    text = Path(path).read_text(encoding="utf-8", errors="replace").strip()
    spans = [Span(start=0, end=len(text), text=text, page=None, source="body")]
    return text, spans


def load_document(path: str) -> dict[str, Any]:
    """The unified loader. Returns everything downstream needs."""
    lower = path.lower()
    try:
        if lower.endswith(".pdf"):
            text, spans = load_pdf(path)
        elif lower.endswith((".docx", ".dotx")):
            text, spans = load_docx(path)
        elif lower.endswith((".txt", ".md")):
            text, spans = load_text(path)
        else:
            # markitdown fallback for .html, .xlsx, .pptx, etc.
            try:
                from markitdown import MarkItDown

                md = MarkItDown()
                result = md.convert(path)
                text = result.text_content.strip()
                spans = [Span(start=0, end=len(text), text=text, page=None, source="body")]
            except Exception:
                text, spans = load_text(path)
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    return {
        "ok": True,
        "path": path,
        "text": text,
        "char_count": len(text),
        "word_count": len(re.findall(r"\b\w+\b", text)),
        "spans": spans,
        "span_count": len(spans),
    }
