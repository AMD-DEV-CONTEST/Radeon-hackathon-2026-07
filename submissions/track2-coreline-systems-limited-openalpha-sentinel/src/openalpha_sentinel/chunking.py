from __future__ import annotations

from .schemas import Chunk
from .utils import new_id, sha256_text


def chunk_document(
    text: str,
    document_id: str,
    revision_id: str,
    *,
    max_chars: int = 1400,
    overlap_lines: int = 2,
    line_offset: int = 0,
) -> list[Chunk]:
    if line_offset < 0:
        raise ValueError("line_offset must not be negative")

    lines = text.splitlines() or [text]
    chunks: list[Chunk] = []
    start = 0

    while start < len(lines):
        end = start
        size = 0
        while end < len(lines):
            next_size = len(lines[end]) + 1
            if end > start and size + next_size > max_chars:
                break
            size += next_size
            end += 1
        if end == start:
            end += 1

        chunk_text = "\n".join(lines[start:end]).strip()
        if chunk_text:
            ordinal = len(chunks)
            digest = sha256_text(chunk_text)
            chunks.append(
                Chunk(
                    id=new_id("chk", f"{document_id}:{ordinal}:{digest}"),
                    document_id=document_id,
                    revision_id=revision_id,
                    ordinal=ordinal,
                    start_line=start + 1 + line_offset,
                    end_line=end + line_offset,
                    text=chunk_text,
                    content_sha256=digest,
                )
            )

        if end >= len(lines):
            break
        start = max(start + 1, end - overlap_lines)

    return chunks

