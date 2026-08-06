"""Stable source citations."""

from buildguard.rag.schemas import CitationRecord, DocumentChunk


def make_citation(chunk: DocumentChunk) -> CitationRecord:
    parts = [chunk.document_name]
    if chunk.page is not None:
        parts.append(f"p.{chunk.page}")
    if chunk.chapter:
        parts.append(chunk.chapter)
    if chunk.article:
        parts.append(chunk.article)
    return CitationRecord(
        chunk_id=chunk.chunk_id,
        label=" · ".join(parts),
        source_path=chunk.source_path,
        page=chunk.page,
        article=chunk.article,
    )

