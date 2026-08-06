"""Multi-format document parser: PDF / Word / HTML / TXT / MD + tables + images.

Reference the docling architecture of lesson 8 RAG-Challenge-2:
- PDF: prefer docling (table structure recognition + OCR), fallback to pymupdf / pdfplumber
- Word (.docx): python-docx, extract paragraphs + tables (converted to markdown)
- HTML (.html/.htm): BeautifulSoup, extract body + tables (converted to markdown)
- TXT/MD: read directly

Output unified ParsedDocument structure:
    {
        "title": str,
        "source": str,          # file name
        "source_path": str,     # full path
        "format": str,          # pdf/docx/html/txt/md
        "sections": [
            {
                "type": "text" | "table" | "image",
                "content": str,     # text / markdown table / image description
                "page": int,        # page number (PDF) or 0
                "section_title": str,  # the most recent preceding heading
            }
        ]
    }
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class Section:
    """A document section unit."""
    type: str           # "text" | "table" | "image"
    content: str        # text content / markdown table / image description
    page: int = 0       # page number (for PDF, 0 otherwise)
    section_title: str = ""  # the heading it belongs to


@dataclass
class ParsedDocument:
    """A parsed document."""
    title: str
    source: str             # file name (without path)
    source_path: str        # full path
    format: str             # pdf/docx/html/txt/md
    sections: list[Section] = field(default_factory=list)

    def to_plain_text(self) -> str:
        """Merge all sections into plain text (for fallback chunking)."""
        parts = []
        for s in self.sections:
            if s.type == "text":
                parts.append(s.content)
            elif s.type == "table":
                parts.append(s.content)  # markdown tables are also text
            elif s.type == "image":
                parts.append(f"[image: {s.content}]")
        return "\n\n".join(parts)


def parse_document(file_path: Path) -> ParsedDocument | None:
    """Automatically select a parser based on the file extension.

    Args:
        file_path: the document file path

    Returns:
        ParsedDocument or None (parse failed)
    """
    suffix = file_path.suffix.lower()
    parsers = {
        ".pdf": _parse_pdf,
        ".docx": _parse_docx,
        ".doc": _parse_doc_legacy,
        ".html": _parse_html,
        ".htm": _parse_html,
        ".txt": _parse_text,
        ".md": _parse_text,
    }

    parser = parsers.get(suffix)
    if not parser:
        logger.warning("unsupported file format: %s", suffix)
        return None

    try:
        doc = parser(file_path)
        if doc:
            logger.info(
                "parsed %s: %d sections (format=%s, title='%s')",
                file_path.name, len(doc.sections), doc.format, doc.title,
            )
        return doc
    except Exception as e:
        logger.error("parsing %s failed: %s", file_path.name, e)
        return None


# ── PDF parsing ──

def _parse_pdf(pdf_path: Path) -> ParsedDocument | None:
    """PDF parsing: prefer docling (tables + OCR), fallback to pymupdf / pdfplumber.

    Reference pdf_parsing.py of lesson 8; docling can recognize table structures and convert to markdown.
    """
    # method 1: docling (best, supports table structure recognition + OCR)
    try:
        return _parse_pdf_with_docling(pdf_path)
    except ImportError:
        logger.debug("docling not installed, trying pymupdf")
    except Exception as e:
        logger.warning("docling failed to parse PDF, falling back to pymupdf: %s", e)

    # method 2: pymupdf (fast, plain text + basic tables)
    try:
        return _parse_pdf_with_pymupdf(pdf_path)
    except ImportError:
        logger.debug("pymupdf not installed, trying pdfplumber")
    except Exception as e:
        logger.warning("pymupdf failed to parse PDF, falling back to pdfplumber: %s", e)

    # method 3: pdfplumber (better table recognition)
    try:
        return _parse_pdf_with_pdfplumber(pdf_path)
    except ImportError:
        logger.warning(
            "skipped PDF %s: docling / pymupdf / pdfplumber not installed. "
            "Recommend pip install pymupdf (basic) or pip install docling (tables+OCR)",
            pdf_path.name,
        )
        return None


def _parse_pdf_with_docling(pdf_path: Path) -> ParsedDocument:
    """Parse a PDF with docling, supporting table structure recognition and OCR.

    Reference DoclingParseV2DocumentBackend + TableFormerMode.ACCURATE in lesson 8 pdf_parsing.py.
    """
    from docling.document_converter import DocumentConverter, FormatOption
    from docling.datamodel.pipeline_options import PdfPipelineOptions, TableFormerMode, EasyOcrOptions
    from docling.datamodel.base_models import InputFormat
    from docling.pipeline.standard_pdf_pipeline import StandardPdfPipeline
    from docling.backend.docling_parse_v2_backend import DoclingParseV2DocumentBackend

    pipeline_options = PdfPipelineOptions()
    pipeline_options.do_ocr = True
    pipeline_options.ocr_options = EasyOcrOptions(lang=['ch_sim', 'en'], force_full_page_ocr=False)
    pipeline_options.do_table_structure = True
    pipeline_options.table_structure_options.do_cell_matching = True
    pipeline_options.table_structure_options.mode = TableFormerMode.ACCURATE

    format_options = {
        InputFormat.PDF: FormatOption(
            pipeline_cls=StandardPdfPipeline,
            pipeline_options=pipeline_options,
            backend=DoclingParseV2DocumentBackend,
        )
    }

    converter = DocumentConverter(format_options=format_options)
    conv_result = converter.convert(pdf_path)

    sections: list[Section] = []
    title = pdf_path.stem

    # export to markdown (including tables)
    md_text = conv_result.document.export_to_markdown()
    if md_text:
        # split by double newline into paragraphs
        for para in md_text.split("\n\n"):
            para = para.strip()
            if not para:
                continue
            # determine whether it is a table (markdown tables start with |)
            if para.startswith("|") and "|" in para:
                sections.append(Section(type="table", content=para, page=0))
            else:
                sections.append(Section(type="text", content=para, page=0))

    # extract tables (if there is separate table data)
    for table in conv_result.document.tables:
        try:
            table_md = table.export_to_markdown()
            if table_md and table_md.strip():
                # avoid duplicates (markdown export may already contain them)
                existing = [s for s in sections if s.type == "table" and s.content == table_md]
                if not existing:
                    sections.append(Section(type="table", content=table_md, page=0))
        except Exception:
            pass

    # extract image descriptions
    for picture in conv_result.document.pictures:
        try:
            # docling can provide image captions
            caption = ""
            if hasattr(picture, "caption") and picture.caption:
                caption = picture.caption
            if not caption:
                caption = f"PDF image (page {getattr(picture, 'page_no', 0)})"
            sections.append(Section(type="image", content=caption, page=getattr(picture, 'page_no', 0)))
        except Exception:
            pass

    if not sections:
        # docling export is empty, try plain text
        text = conv_result.document.export_to_text()
        if text:
            sections.append(Section(type="text", content=text, page=0))

    # try to extract a title
    for s in sections:
        if s.type == "text" and len(s.content) < 100 and not s.content.startswith("|"):
            title = s.content.strip()
            break

    return ParsedDocument(
        title=title,
        source=pdf_path.name,
        source_path=str(pdf_path),
        format="pdf",
        sections=sections,
    )


def _parse_pdf_with_pymupdf(pdf_path: Path) -> ParsedDocument:
    """Parse a PDF with pymupdf (fitz), supporting plain text and basic tables."""
    import fitz  # type: ignore

    doc = fitz.open(str(pdf_path))
    sections: list[Section] = []
    title = pdf_path.stem

    for page_num, page in enumerate(doc, start=1):
        # extract text
        text = page.get_text("text")
        if text and text.strip():
            for para in text.split("\n\n"):
                para = para.strip()
                if para:
                    sections.append(Section(type="text", content=para, page=page_num))

        # extract tables (pymupdf supports find_tables)
        try:
            tables = page.find_tables()
            for table in tables:
                # convert to markdown table
                table_data = table.extract()
                if table_data and len(table_data) > 1:
                    md = _table_to_markdown(table_data)
                    sections.append(Section(type="table", content=md, page=page_num))
        except Exception:
            pass

        # extract image information
        try:
            images = page.get_images(full=True)
            for img_idx, img in enumerate(images):
                sections.append(Section(
                    type="image",
                    content=f"PDF image (page {page_num}, img {img_idx + 1})",
                    page=page_num,
                ))
        except Exception:
            pass

    doc.close()

    if not sections:
        logger.warning("PDF %s extracted no content (may be a scanned document, requires OCR)", pdf_path.name)

    # try to extract a title from the first text section
    if sections and sections[0].type == "text" and len(sections[0].content) < 100:
        title = sections[0].content.strip()

    return ParsedDocument(
        title=title,
        source=pdf_path.name,
        source_path=str(pdf_path),
        format="pdf",
        sections=sections,
    )


def _parse_pdf_with_pdfplumber(pdf_path: Path) -> ParsedDocument:
    """Parse a PDF with pdfplumber, which has good table recognition."""
    import pdfplumber  # type: ignore

    sections: list[Section] = []
    title = pdf_path.stem

    with pdfplumber.open(str(pdf_path)) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            # text
            text = page.extract_text() or ""
            if text.strip():
                for para in text.split("\n\n"):
                    para = para.strip()
                    if para:
                        sections.append(Section(type="text", content=para, page=page_num))

            # tables
            try:
                tables = page.extract_tables()
                for table_data in tables:
                    if table_data and len(table_data) > 1:
                        md = _table_to_markdown(table_data)
                        sections.append(Section(type="table", content=md, page=page_num))
            except Exception:
                pass

            # images
            try:
                for img_idx, img in enumerate(page.images):
                    sections.append(Section(
                        type="image",
                        content=f"PDF image (page {page_num}, img {img_idx + 1})",
                        page=page_num,
                    ))
            except Exception:
                pass

    if sections and sections[0].type == "text" and len(sections[0].content) < 100:
        title = sections[0].content.strip()

    return ParsedDocument(
        title=title,
        source=pdf_path.name,
        source_path=str(pdf_path),
        format="pdf",
        sections=sections,
    )


# ── Word parsing ──

def _parse_docx(docx_path: Path) -> ParsedDocument | None:
    """Parse a Word document with python-docx, extracting paragraphs and tables."""
    try:
        from docx import Document  # type: ignore
    except ImportError:
        logger.warning("skipped Word %s: python-docx not installed. pip install python-docx", docx_path.name)
        return None

    doc = Document(str(docx_path))
    sections: list[Section] = []
    title = docx_path.stem
    current_heading = ""

    for element in doc.element.body:
        tag = element.tag.split("}")[-1] if "}" in element.tag else element.tag

        if tag == "p":
            # paragraph
            from docx.text.paragraph import Paragraph  # type: ignore
            para = Paragraph(element, doc)
            text = para.text.strip()
            if not text:
                continue

            # determine whether it is a heading
            if para.style and para.style.name and "Heading" in para.style.name:
                current_heading = text
                sections.append(Section(type="text", content=f"## {text}", section_title=text))
                if not title or title == docx_path.stem:
                    title = text
            else:
                sections.append(Section(type="text", content=text, section_title=current_heading))

        elif tag == "tbl":
            # table
            from docx.table import Table  # type: ignore
            table = Table(element, doc)
            table_data = []
            for row in table.rows:
                row_data = [cell.text.strip() for cell in row.cells]
                table_data.append(row_data)
            if table_data:
                md = _table_to_markdown(table_data)
                sections.append(Section(type="table", content=md, section_title=current_heading))

    # extract images (python-docx does not directly support image extraction, but embedded relationships can be checked)
    try:
        for rel in doc.part.rels.values():
            if "image" in rel.reltype:
                sections.append(Section(
                    type="image",
                    content=f"Word embedded image (ref: {rel.target_ref})",
                ))
    except Exception:
        pass

    return ParsedDocument(
        title=title,
        source=docx_path.name,
        source_path=str(docx_path),
        format="docx",
        sections=sections,
    )


def _parse_doc_legacy(doc_path: Path) -> ParsedDocument | None:
    """Legacy .doc format; try antiword or skip."""
    logger.warning("legacy .doc format support is limited, recommend converting to .docx: %s", doc_path.name)
    return None


# ── HTML parsing ──

def _parse_html(html_path: Path) -> ParsedDocument | None:
    """Parse HTML with BeautifulSoup, extracting body and tables."""
    try:
        from bs4 import BeautifulSoup  # type: ignore
    except ImportError:
        logger.warning("skipped HTML %s: beautifulsoup4 not installed. pip install beautifulsoup4", html_path.name)
        return None

    content = html_path.read_text(encoding="utf-8", errors="ignore")
    soup = BeautifulSoup(content, "html.parser")

    # extract title
    title = html_path.stem
    if soup.title and soup.title.string:
        title = soup.title.string.strip()

    sections: list[Section] = []
    current_heading = ""

    # remove script/style
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()

    # iterate over all elements
    for element in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "table", "img", "li"]):
        tag_name = element.name

        if tag_name in ("h1", "h2", "h3", "h4", "h5", "h6"):
            current_heading = element.get_text(strip=True)
            sections.append(Section(
                type="text",
                content=f"{'#' * int(tag_name[1])} {current_heading}",
                section_title=current_heading,
            ))
        elif tag_name == "p":
            text = element.get_text(strip=True)
            if text:
                sections.append(Section(type="text", content=text, section_title=current_heading))
        elif tag_name == "li":
            text = element.get_text(strip=True)
            if text:
                sections.append(Section(type="text", content=f"- {text}", section_title=current_heading))
        elif tag_name == "table":
            # HTML table to markdown
            table_data = []
            for tr in element.find_all("tr"):
                row = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
                if row:
                    table_data.append(row)
            if table_data:
                md = _table_to_markdown(table_data)
                sections.append(Section(type="table", content=md, section_title=current_heading))
        elif tag_name == "img":
            alt = element.get("alt", "").strip()
            src = element.get("src", "")
            desc = alt if alt else f"HTML image: {src}"
            sections.append(Section(type="image", content=desc, section_title=current_heading))

    return ParsedDocument(
        title=title,
        source=html_path.name,
        source_path=str(html_path),
        format="html",
        sections=sections,
    )


# ── TXT / MD parsing ──

def _parse_text(text_path: Path) -> ParsedDocument:
    """Parse a plain-text / Markdown file."""
    content = text_path.read_text(encoding="utf-8")
    sections: list[Section] = []
    title = text_path.stem
    current_heading = ""

    # if it is Markdown, split by headings
    if text_path.suffix.lower() == ".md":
        for line in content.split("\n"):
            line = line.rstrip()
            if not line:
                continue
            if line.startswith("#"):
                current_heading = line.lstrip("#").strip()
                sections.append(Section(type="text", content=line, section_title=current_heading))
                if not title or title == text_path.stem:
                    title = current_heading
            elif line.startswith("|") and "|" in line:
                # Markdown table row (collect consecutive table rows)
                if sections and sections[-1].type == "table":
                    sections[-1].content += "\n" + line
                else:
                    sections.append(Section(type="table", content=line, section_title=current_heading))
            else:
                sections.append(Section(type="text", content=line, section_title=current_heading))
    else:
        # plain text split by paragraphs
        for para in content.split("\n\n"):
            para = para.strip()
            if para:
                sections.append(Section(type="text", content=para))

    return ParsedDocument(
        title=title,
        source=text_path.name,
        source_path=str(text_path),
        format=text_path.suffix.lstrip(".").lower(),
        sections=sections,
    )


# ── utility functions ──

def _table_to_markdown(table_data: list[list[str]]) -> str:
    """Convert a 2D array to a markdown table.

    Reference the _table_to_md method of lesson 8 tables_serialization.py.
    """
    if not table_data:
        return ""

    # first row as header
    headers = table_data[0]
    rows = table_data[1:] if len(table_data) > 1 else []

    # build the markdown table
    lines = []
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("| " + " | ".join(["---"] * len(headers)) + " |")
    for row in rows:
        # pad columns
        while len(row) < len(headers):
            row.append("")
        lines.append("| " + " | ".join(row[:len(headers)]) + " |")

    return "\n".join(lines)


def collect_all_documents(docs_dir: Path) -> list[ParsedDocument]:
    """Collect all supported document formats in a directory and parse them.

    Supported: .pdf, .docx, .html, .htm, .txt, .md
    """
    documents: list[ParsedDocument] = []
    supported_patterns = ("*.pdf", "*.docx", "*.html", "*.htm", "*.txt", "*.md")

    for pattern in supported_patterns:
        for f in sorted(docs_dir.glob(pattern)):
            doc = parse_document(f)
            if doc and doc.sections:
                documents.append(doc)
                logger.info(
                    "loaded %s: %d sections (format=%s)",
                    f.name, len(doc.sections), doc.format,
                )

    return documents