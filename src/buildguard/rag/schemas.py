"""RAG domain schemas."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from buildguard.schemas.common import StrictSchema


class ParsedSection(StrictSchema):
    document_name: str = Field(min_length=1)
    source_path: Path
    page: int | None = Field(default=None, ge=1)
    chapter: str | None = None
    article: str | None = None
    title: str | None = None
    content: str = Field(min_length=1)
    effective_date: date | None = None
    checksum: str = Field(min_length=64, max_length=64)
    is_table: bool = False
    table_header: str | None = None


class ParsedDocument(StrictSchema):
    document_name: str
    source_path: Path
    checksum: str
    sections: list[ParsedSection] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class DocumentChunk(StrictSchema):
    chunk_id: str = Field(min_length=64, max_length=64)
    document_name: str
    source_path: Path
    document_checksum: str
    page: int | None = None
    chapter: str | None = None
    article: str | None = None
    title: str | None = None
    content: str = Field(min_length=1)
    effective_date: date | None = None
    project: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ScoredChunk(StrictSchema):
    chunk: DocumentChunk
    score: float
    rank: int = Field(ge=1)
    source: Literal["bm25", "dense", "fusion", "reranker"]


class CitationRecord(StrictSchema):
    chunk_id: str
    label: str
    source_path: Path
    page: int | None = None
    article: str | None = None


class RagSearchInput(StrictSchema):
    query: str = Field(min_length=1, max_length=4000)
    top_k: int = Field(default=5, ge=1, le=50)
    document_filters: list[str] = Field(default_factory=list)
    project_filter: str | None = None


class RagSearchOutput(StrictSchema):
    chunks: list[DocumentChunk]
    retrieved_chunk_ids: list[str] = Field(default_factory=list)
    reranked_chunk_ids: list[str] = Field(default_factory=list)
    scores: list[float]
    citations: list[CitationRecord]
    evidence_status: Literal["sufficient", "insufficient_evidence"]
    retrieval_latency_ms: float = Field(ge=0)
    stage_latency_ms: dict[str, float] = Field(default_factory=dict)


class IngestResult(StrictSchema):
    source_path: Path
    status: Literal["indexed", "unchanged", "removed", "failed"]
    chunk_count: int = Field(ge=0)
    checksum: str | None = None
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None


class RagStatus(StrictSchema):
    document_count: int = Field(ge=0)
    chunk_count: int = Field(ge=0)
    index_dir: Path
    embedding_backend: str
    reranker_backend: str


class QAExample(StrictSchema):
    question: str = Field(min_length=1)
    relevant_chunk_ids: list[str] = Field(min_length=1)


class EvaluationMetrics(StrictSchema):
    recall_at_5: float = Field(ge=0, le=1)
    recall_at_10: float = Field(ge=0, le=1)
    mrr: float = Field(ge=0, le=1)
    ndcg_at_10: float = Field(ge=0, le=1)
    evaluated_questions: int = Field(ge=0)
