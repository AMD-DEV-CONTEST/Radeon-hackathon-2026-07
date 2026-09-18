"""Persistent local RAG service."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import orjson

from buildguard.config import RagConfig, Settings
from buildguard.exceptions import ConfigurationError
from buildguard.logging_system.jsonl_writer import atomic_write_json
from buildguard.rag.bm25_index import BM25Index
from buildguard.rag.chunker import ChunkingOptions, StructureAwareChunker
from buildguard.rag.dense_index import DenseIndex
from buildguard.rag.embedding_backend import (
    EmbeddingBackend,
    MockEmbeddingBackend,
    TransformersEmbeddingBackend,
)
from buildguard.rag.index_manifest import expected_manifest, load_manifest
from buildguard.rag.parsers import DocxParser, MarkdownParser, PdfParser, TextParser
from buildguard.rag.parsers.base import DocumentParser, file_checksum
from buildguard.rag.reranker import MockReranker, Reranker, TransformersReranker
from buildguard.rag.retriever import HybridRetriever
from buildguard.rag.schemas import (
    DocumentChunk,
    EvaluationMetrics,
    IngestResult,
    QAExample,
    RagSearchInput,
    RagSearchOutput,
    RagStatus,
)


class RagService:
    """Coordinate parsing, incremental rebuilds, search, and evaluation."""

    def __init__(
        self,
        config: RagConfig,
        embedding: EmbeddingBackend,
        reranker: Reranker,
    ) -> None:
        self.config = config
        self.index_dir = config.index_dir.resolve()
        self.index_dir.mkdir(parents=True, exist_ok=True)
        self.embedding = embedding
        self.reranker = reranker
        self.bm25 = BM25Index(self.index_dir)
        self.dense = DenseIndex(self.index_dir, embedding)
        self.retriever = HybridRetriever(self.bm25, self.dense, reranker, config)
        self.manifest_path = self.index_dir / "corpus_manifest.json"
        self.index_manifest_path = self.index_dir / "index_manifest.json"
        self.documents: dict[str, dict[str, Any]] = {}
        self.index_validation_error: str | None = None
        self.parsers: dict[str, DocumentParser] = {}
        for parser in (PdfParser(), DocxParser(), MarkdownParser(), TextParser()):
            for extension in parser.extensions:
                self.parsers[extension] = parser
        self._load()

    def _load(self) -> None:
        if self.manifest_path.is_file():
            payload = orjson.loads(self.manifest_path.read_bytes())
            self.documents = {
                str(key): dict(value) for key, value in payload.get("documents", {}).items()
            }
        bm25_loaded = self.bm25.load()
        dense_loaded = self.dense.load()
        if bm25_loaded and dense_loaded:
            if not self.index_manifest_path.is_file():
                self.index_validation_error = (
                    "RAG index manifest is missing; rebuild required"
                )
            else:
                stored = load_manifest(self.index_manifest_path)
                expected = expected_manifest(
                    self.config,
                    self.embedding,
                    self.manifest_path,
                    document_count=len(self.documents),
                    chunk_count=len(self.bm25.chunks),
                )
                if stored.identity() != expected.identity():
                    self.index_validation_error = (
                        "RAG index identity changed; rebuild required"
                    )
        if bm25_loaded and (
            not dense_loaded or self.dense.checksum != self.bm25.checksum
        ):
            self.dense.build(self.bm25.chunks)
            self.dense.save()

    def _save(self) -> None:
        self.bm25.save()
        self.dense.save()
        atomic_write_json(self.manifest_path, {"documents": self.documents})
        manifest = expected_manifest(
            self.config,
            self.embedding,
            self.manifest_path,
            document_count=len(self.documents),
            chunk_count=len(self.bm25.chunks),
        )
        atomic_write_json(
            self.index_manifest_path, manifest.model_dump(mode="json")
        )

    def _rebuild(self, chunks: list[DocumentChunk]) -> None:
        self.bm25.build(chunks)
        self.dense.build(chunks)
        self._save()

    def ingest(self, source_path: Path, project: str | None = None) -> IngestResult:
        source = source_path.resolve()
        try:
            parser = self.parsers.get(source.suffix.lower())
            if parser is None:
                raise ValueError(f"Unsupported document extension: {source.suffix}")
            checksum = file_checksum(source)
            source_key = str(source)
            current = self.documents.get(source_key)
            if current and current.get("checksum") == checksum:
                return IngestResult(
                    source_path=source,
                    status="unchanged",
                    chunk_count=int(current.get("chunk_count", 0)),
                    checksum=checksum,
                )
            duplicate = next(
                (
                    metadata
                    for path, metadata in self.documents.items()
                    if path != source_key and metadata.get("checksum") == checksum
                ),
                None,
            )
            if duplicate is not None:
                return IngestResult(
                    source_path=source,
                    status="unchanged",
                    chunk_count=int(duplicate.get("chunk_count", 0)),
                    checksum=checksum,
                    warnings=["Duplicate document checksum; no duplicate chunks were added"],
                )
            document = parser.parse(source)
            chunker = StructureAwareChunker(
                ChunkingOptions(
                    min_chars=self.config.chunk_min_chars,
                    max_chars=self.config.chunk_max_chars,
                    overlap_chars=self.config.chunk_overlap_chars,
                )
            )
            new_chunks = chunker.chunk(document, project)
            retained = [
                chunk
                for chunk in self.bm25.chunks
                if str(chunk.source_path.resolve()) != source_key
            ]
            self.documents[source_key] = {
                "checksum": checksum,
                "chunk_count": len(new_chunks),
                "project": project,
                "document_name": source.name,
            }
            self._rebuild([*retained, *new_chunks])
            return IngestResult(
                source_path=source,
                status="indexed",
                chunk_count=len(new_chunks),
                checksum=checksum,
                warnings=document.warnings,
            )
        except Exception as exc:
            return IngestResult(
                source_path=source,
                status="failed",
                chunk_count=0,
                error=str(exc),
            )

    def ingest_path(self, path: Path, project: str | None = None) -> list[IngestResult]:
        source = path.resolve()
        if source.is_file():
            return [self.ingest(source, project)]
        if not source.is_dir():
            return [
                IngestResult(
                    source_path=source,
                    status="failed",
                    chunk_count=0,
                    error="Source path does not exist",
                )
            ]
        supported = sorted(
            item
            for item in source.rglob("*")
            if item.is_file() and item.suffix.lower() in self.parsers
        )
        return [self.ingest(item, project) for item in supported]

    def remove(self, source_path: Path) -> IngestResult:
        source = source_path.resolve()
        source_key = str(source)
        if source_key not in self.documents:
            return IngestResult(
                source_path=source,
                status="unchanged",
                chunk_count=0,
                warnings=["Document was not indexed"],
            )
        removed_count = sum(
            1 for chunk in self.bm25.chunks if str(chunk.source_path.resolve()) == source_key
        )
        retained = [
            chunk
            for chunk in self.bm25.chunks
            if str(chunk.source_path.resolve()) != source_key
        ]
        del self.documents[source_key]
        self._rebuild(retained)
        return IngestResult(
            source_path=source,
            status="removed",
            chunk_count=removed_count,
        )

    def search(self, request: RagSearchInput) -> RagSearchOutput:
        if self.index_validation_error is not None:
            raise ConfigurationError(self.index_validation_error)
        return self.retriever.search(request)

    def validate_index(self) -> dict[str, object]:
        return {
            "valid": self.index_validation_error is None,
            "reason": self.index_validation_error,
            "manifest_path": str(self.index_manifest_path),
            "document_count": len(self.documents),
            "chunk_count": len(self.bm25.chunks),
        }

    def rebuild(self) -> dict[str, object]:
        self._rebuild(list(self.bm25.chunks))
        self.index_validation_error = None
        return self.validate_index()

    def status(self) -> RagStatus:
        return RagStatus(
            document_count=len(self.documents),
            chunk_count=len(self.bm25.chunks),
            index_dir=self.index_dir,
            embedding_backend=type(self.embedding).__name__,
            reranker_backend=type(self.reranker).__name__,
        )

    def evaluate(self, examples: list[QAExample]) -> EvaluationMetrics:
        if not examples:
            return EvaluationMetrics(
                recall_at_5=0,
                recall_at_10=0,
                mrr=0,
                ndcg_at_10=0,
                evaluated_questions=0,
            )
        recall_5 = 0.0
        recall_10 = 0.0
        reciprocal_ranks = 0.0
        ndcg = 0.0
        for example in examples:
            ranked = self.retriever.rank(
                RagSearchInput(query=example.question, top_k=10),
                10,
            )
            ids = [item.chunk.chunk_id for item in ranked]
            relevant = set(example.relevant_chunk_ids)
            recall_5 += len(relevant & set(ids[:5])) / len(relevant)
            recall_10 += len(relevant & set(ids[:10])) / len(relevant)
            first = next((index for index, value in enumerate(ids, start=1) if value in relevant), None)
            reciprocal_ranks += 1.0 / first if first else 0.0
            dcg = sum(
                1.0 / math.log2(rank + 1)
                for rank, value in enumerate(ids[:10], start=1)
                if value in relevant
            )
            ideal_count = min(len(relevant), 10)
            ideal = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_count + 1))
            ndcg += dcg / ideal if ideal else 0.0
        count = len(examples)
        return EvaluationMetrics(
            recall_at_5=recall_5 / count,
            recall_at_10=recall_10 / count,
            mrr=reciprocal_ranks / count,
            ndcg_at_10=ndcg / count,
            evaluated_questions=count,
        )


def create_rag_service(settings: Settings) -> RagService:
    """Construct configured local-only retrieval adapters."""
    workspace = settings.app.workspace_dir.resolve()
    index_dir = settings.rag.index_dir.resolve()
    try:
        index_dir.relative_to(workspace)
    except ValueError as exc:
        raise ConfigurationError("RAG index_dir must remain inside workspace") from exc
    config = settings.rag.model_copy(update={"index_dir": index_dir})
    if config.embedding_mode == "mock":
        embedding: EmbeddingBackend = MockEmbeddingBackend(
            config.embedding_dimension, settings.app.seed
        )
    else:
        if config.embedding_model_path is None:
            raise ConfigurationError("embedding_model_path is required")
        embedding = TransformersEmbeddingBackend(
            config.embedding_model_path,
            device=config.embedding_device,
            batch_size=config.embedding_batch_size,
            normalize=config.embedding_normalize,
            query_instruction=config.embedding_query_instruction,
            revision=(
                None
                if config.embedding_model_revision == "unreported"
                else config.embedding_model_revision
            ),
            tokenizer_revision=(
                None
                if config.embedding_tokenizer_revision == "unreported"
                else config.embedding_tokenizer_revision
            ),
        )
    if config.reranker_mode == "mock":
        reranker: Reranker = MockReranker(config.reranker_enabled)
    else:
        if config.reranker_model_path is None:
            raise ConfigurationError("reranker_model_path is required")
        reranker = TransformersReranker(
            config.reranker_model_path,
            device=config.reranker_device,
            batch_size=config.reranker_batch_size,
            enabled=config.reranker_enabled,
            architecture=config.reranker_architecture,
            revision=(
                None
                if config.reranker_model_revision == "unreported"
                else config.reranker_model_revision
            ),
        )
    return RagService(config, embedding, reranker)
