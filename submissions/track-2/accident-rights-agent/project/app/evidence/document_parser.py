"""PDF text/layout extraction with page-level provenance."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from app.evidence.errors import DependencyUnavailable, UnsupportedEvidence
from app.schemas.evidence import EvidenceNode, SourceFile


@dataclass(frozen=True)
class ParsedDocument:
    nodes: tuple[EvidenceNode, ...]
    page_images: tuple[Path, ...]
    page_count: int
    scanned_page_count: int


def parse_pdf(
    source: SourceFile,
    path: Path,
    derived_dir: Path,
    *,
    max_pages: int = 100,
    min_text_characters: int = 40,
    render_all_pages: bool = False,
) -> ParsedDocument:
    try:
        import fitz
    except ImportError as exc:
        raise DependencyUnavailable(
            "PyMuPDF is required for PDF text/layout extraction. "
            "Install the project 'evidence' extra."
        ) from exc

    page_dir = derived_dir / "pdf" / source.source_id
    page_dir.mkdir(parents=True, exist_ok=True)
    nodes: list[EvidenceNode] = []
    images: list[Path] = []
    scanned_pages = 0

    try:
        document = fitz.open(path)
    except Exception as exc:
        raise UnsupportedEvidence(f"PDF decoder rejected {path.name}: {exc}") from exc

    try:
        if document.needs_pass:
            raise UnsupportedEvidence("Password-protected PDFs are not accepted.")
        if document.page_count > max_pages:
            raise UnsupportedEvidence(
                f"PDF has {document.page_count} pages; limit is {max_pages}."
            )
        for page_index in range(document.page_count):
            page = document.load_page(page_index)
            text = page.get_text("text", sort=True).strip()
            blocks = page.get_text("blocks", sort=True)
            is_scanned = len(text) < min_text_characters
            if is_scanned:
                scanned_pages += 1

            rendered: Path | None = None
            if render_all_pages or is_scanned:
                rendered = page_dir / f"page_{page_index + 1:04d}.png"
                pixmap = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
                pixmap.save(rendered)
                images.append(rendered)

            content_digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
            nodes.append(
                EvidenceNode(
                    node_id=f"NODE-{source.source_id[4:]}-P{page_index + 1:04d}",
                    case_id=source.case_id,
                    source_id=source.source_id,
                    node_type="pdf_page",
                    locator={
                        "source_path": source.stored_path,
                        "page": page_index + 1,
                        "rendered_path": (
                            rendered.relative_to(derived_dir.parent).as_posix()
                            if rendered
                            else None
                        ),
                    },
                    content=text or None,
                    content_sha256=content_digest,
                    confidence=1.0 if text else 0.0,
                    extraction_method="pymupdf_text",
                    metadata={
                        "is_scanned": is_scanned,
                        "width": page.rect.width,
                        "height": page.rect.height,
                        "text_block_count": len(blocks),
                    },
                )
            )
    finally:
        document.close()

    return ParsedDocument(
        nodes=tuple(nodes),
        page_images=tuple(images),
        page_count=len(nodes),
        scanned_page_count=scanned_pages,
    )
