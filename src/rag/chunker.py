"""Document chunking: sliding window + 20% overlap + source-data storage.

Improvements:
- Sliding-window chunking: window=512, overlap=100 (about 20%)
- Source-data storage: each chunk carries source (file name), title (document title), section_title (section title)
- Supports both ParsedDocument (with text/table/image sections) and plain-text input
- Table sections are kept whole, not cut by the sliding window
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class Chunk:
    """A document chunk unit."""
    chunk_id: str
    doc_ref: str               # Workspace File ref / document identifier
    chunk_text: str             # chunk text
    chunk_summary: str          # summary (first 80 chars)
    start_char: int             # start character position
    end_char: int               # end character position
    meta: dict = field(default_factory=dict)  # extended metadata


def chunk_document(
    content: str,
    doc_ref: str,
    chunk_size: int = 512,
    chunk_overlap: int = 100,
    source: str = "",
    title: str = "",
) -> list[Chunk]:
    """Chunk by sliding window + overlap.

    Args:
        content: document content (plain text)
        doc_ref: Workspace File ref / document identifier
        chunk_size: number of characters per chunk (default 512)
        chunk_overlap: number of overlapping characters between adjacent chunks (default 100, about 20%)
        source: source file name (e.g. "insurance_policy.pdf")
        title: document title (e.g. "Employer Liability Insurance Terms")

    Returns:
        A list of Chunk objects; each chunk's meta contains source, title, char_range
    """
    chunks: list[Chunk] = []
    start = 0
    idx = 0

    # ensure overlap does not exceed half of chunk_size
    chunk_overlap = min(chunk_overlap, chunk_size // 2)

    while start < len(content):
        end = min(start + chunk_size, len(content))
        chunk_text = content[start:end]

        chunks.append(Chunk(
            chunk_id=f"{doc_ref}_chunk_{idx:03d}",
            doc_ref=doc_ref,
            chunk_text=chunk_text,
            chunk_summary=chunk_text[:80],
            start_char=start,
            end_char=end,
            meta={
                "char_range": f"{start}-{end}",
                "source": source or doc_ref,
                "title": title or doc_ref,
                "chunk_index": idx,
            },
        ))
        start += chunk_size - chunk_overlap
        idx += 1

    logger.info(
        "document %s chunked: %d chunks (window=%d, overlap=%d, 20%%=%d)",
        doc_ref, len(chunks), chunk_size, chunk_overlap, int(chunk_size * 0.2),
    )
    return chunks


def chunk_parsed_document(
    doc: Any,
    chunk_size: int = 512,
    chunk_overlap: int = 100,
) -> list[Chunk]:
    """Chunk a ParsedDocument, preserving section type and source data.

    Strategy:
    - text sections: merged and chunked by sliding window
    - table sections: kept whole as one chunk (not cut)
    - image sections: kept whole as one chunk (image description)

    Args:
        doc: a ParsedDocument instance (from src.rag.parser)
        chunk_size: text chunk window size
        chunk_overlap: text chunk overlap (default 100, about 20%)

    Returns:
        A list of Chunk objects; each chunk's meta contains:
        - source: source file name
        - title: document title
        - section_title: section title
        - section_type: text / table / image
        - page: page number (PDF)
    """
    from src.rag.parser import ParsedDocument

    chunks: list[Chunk] = []
    doc_ref = doc.source.rsplit(".", 1)[0] if "." in doc.source else doc.source
    idx = 0

    # separate different section types
    text_parts: list[str] = []
    text_section_titles: list[str] = []
    non_text_sections = []

    for section in doc.sections:
        if section.type == "text":
            text_parts.append(section.content)
            text_section_titles.append(section.section_title)
        else:
            # table and image are kept whole
            non_text_sections.append(section)

    # merge text sections and chunk by sliding window
    if text_parts:
        combined_text = "\n\n".join(text_parts)
        text_chunks = chunk_document(
            content=combined_text,
            doc_ref=doc_ref,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            source=doc.source,
            title=doc.title,
        )

        # add section info to each text chunk
        for chunk in text_chunks:
            # find the section_title for this chunk (approximate match based on char position)
            char_offset = 0
            matched_title = ""
            for i, part in enumerate(text_parts):
                part_end = char_offset + len(part)
                if chunk.start_char < part_end:
                    matched_title = text_section_titles[i] if i < len(text_section_titles) else ""
                    break
                char_offset = part_end + 2  # +2 for "\n\n"

            chunk.meta.update({
                "section_title": matched_title,
                "section_type": "text",
                "page": 0,
            })
            chunks.append(chunk)
            idx = len(chunks)

    # table sections: keep the whole section as one chunk
    for section in non_text_sections:
        chunk_id = f"{doc_ref}_chunk_{idx:03d}"
        chunks.append(Chunk(
            chunk_id=chunk_id,
            doc_ref=doc_ref,
            chunk_text=section.content,
            chunk_summary=section.content[:80],
            start_char=0,
            end_char=len(section.content),
            meta={
                "char_range": f"0-{len(section.content)}",
                "source": doc.source,
                "title": doc.title,
                "section_title": section.section_title,
                "section_type": section.type,  # "table" or "image"
                "page": section.page,
                "chunk_index": idx,
            },
        ))
        idx += 1

    logger.info(
        "ParsedDocument %s chunked: %d chunks (text=%d, table/image=%d, window=%d, overlap=%d)",
        doc.source, len(chunks),
        len(chunks) - len(non_text_sections), len(non_text_sections),
        chunk_size, chunk_overlap,
    )
    return chunks
