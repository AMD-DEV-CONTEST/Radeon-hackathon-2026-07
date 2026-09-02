"""Title-priority chunk merging for RAG.

Merges Phase‑A small chunks (paragraph / heading / page level) into
RAG‑ready chunks of 500–1000 Chinese characters with 100–150 char overlap.

Strategy
--------
- MD / DOCX : group by heading sections, fill each section to target size
- TXT       : coalesce consecutive paragraphs
- PDF       : coalesce by page, split oversized pages
- XLSX      : pass‑through (rows stay independent — tables preserved)
"""

from __future__ import annotations

from app.rag.manifest import ContentChunk, ParsedDocument

CHUNK_MIN = 500
CHUNK_MAX = 1000
OVERLAP = 125  # characters


def split_document(doc: ParsedDocument) -> list[ContentChunk]:
    """Split a parsed document into RAG‑ready chunks."""

    if doc.format == "xlsx":
        # XLSX rows are atomic — re‑index and return
        return _reindex(doc.chunks)

    # Group by heading boundaries (no-op for TXT/PDF which have no headings)
    sections = _group_sections(doc)

    merged: list[ContentChunk] = []
    for section in sections:
        merged.extend(_merge_section(section, doc))

    return _reindex(merged)


# ── internal helpers ──────────────────────────────────────────────────


def _reindex(chunks: list[ContentChunk]) -> list[ContentChunk]:
    for i, c in enumerate(chunks):
        c.chunk_index = i
    return chunks


def _group_sections(doc: ParsedDocument) -> list[list[ContentChunk]]:
    """Split chunk list at heading boundaries.

    A new section starts whenever we encounter a chunk whose heading_path
    differs from the previous one.  For TXT and PDF (no headings),
    the whole document is one section.
    """
    if not doc.chunks:
        return []

    # TXT / PDF → single section
    if doc.format in ("txt", "pdf"):
        return [list(doc.chunks)]

    sections: list[list[ContentChunk]] = []
    cur: list[ContentChunk] = [doc.chunks[0]]
    prev_path = doc.chunks[0].heading_path or ""

    for ch in doc.chunks[1:]:
        path = ch.heading_path or ""

        # Heading boundary: new heading different from prev
        if path and path != prev_path:
            sections.append(cur)
            cur = []
            prev_path = path

        cur.append(ch)

    if cur:
        sections.append(cur)

    return sections if sections else [list(doc.chunks)]


def _merge_section(
    section: list[ContentChunk], doc: ParsedDocument
) -> list[ContentChunk]:
    """Merge a section's chunks into 500–1000 char chunks with overlap."""

    full = "\n\n".join(c.content for c in section).strip()
    if not full:
        return []

    # Small enough — return as single chunk
    if len(full) <= CHUNK_MAX:
        merged = _build_chunk(
            content=full,
            source_chunks=section,
            relative_path=doc.relative_path,
        )
        return [merged]

    # Split by paragraphs, then merge to target size
    paragraphs = _split_paragraphs(full)
    merged_paras, _ = _fill_to_target(paragraphs)

    chunks: list[ContentChunk] = []
    for text in merged_paras:
        chunks.append(
            _build_chunk(
                content=text,
                source_chunks=section,
                relative_path=doc.relative_path,
            )
        )
    return chunks


def _split_paragraphs(text: str) -> list[str]:
    """Split text into paragraphs, filtering out blanks."""
    return [p.strip() for p in text.split("\n\n") if p.strip()]


def _fill_to_target(
    paragraphs: list[str],
) -> tuple[list[str], list[str]]:
    """Fill chunks 500–1000 chars, sliding with 125‑char overlap.

    Returns (merged_texts, overlap_buffers).
    """
    merged: list[str] = []
    i = 0
    while i < len(paragraphs):
        buf = paragraphs[i]
        j = i + 1
        while j < len(paragraphs) and len(buf) + len(paragraphs[j]) + 2 <= CHUNK_MAX:
            buf += "\n\n" + paragraphs[j]
            j += 1

        if len(buf) >= CHUNK_MIN or j == len(paragraphs):
            merged.append(buf)

        # Advance with overlap
        if j == len(paragraphs):
            break

        # Slide window: take last ~OVERLAP chars from current buffer
        overlap_start = max(0, len(buf) - OVERLAP)
        overlap_text = buf[overlap_start:]
        # Start next chunk from overlap area
        i = max(i + 1, j - _count_paras_in_text(overlap_text, paragraphs, i))
        i = max(i, j - 1)  # ensure forward progress
    return merged, []


def _count_paras_in_text(
    text: str, paragraphs: list[str], start: int
) -> int:
    """Count how many paragraphs from start are covered by text."""
    count = 0
    remaining = text
    for p in paragraphs[start:]:
        if not remaining:
            break
        if p in remaining:
            remaining = remaining.replace(p, "", 1)
            count += 1
        else:
            break
    return count


def _build_chunk(
    content: str,
    source_chunks: list[ContentChunk],
    relative_path: str,
) -> ContentChunk:
    """Build a ContentChunk from merged source chunks."""
    first = source_chunks[0]
    last = source_chunks[-1]

    return ContentChunk(
        chunk_index=0,
        content=content,
        line_start=first.line_start,
        line_end=last.line_end,
        relative_path=relative_path,
        heading_path=first.heading_path,
        section_title=first.section_title,
        heading_level=first.heading_level,
        page_number=first.page_number,
        sheet_name=first.sheet_name,
        header_columns=first.header_columns,
        cell_range=first.cell_range,
    )
