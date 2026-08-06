"""At-most-once corrective retrieval over existing local indexes."""

from __future__ import annotations

import time
from typing import Literal

from pydantic import Field, model_validator

from buildguard.config import AdvancedRagConfig
from buildguard.llm.base import LocalLLMBackend
from buildguard.rag.advanced.quality_evaluator import (
    RetrievalQuality,
    RetrievalQualityEvaluator,
)
from buildguard.rag.advanced.query_rewriter import QueryRewriter
from buildguard.rag.advanced.retrieval_gate import (
    RetrievalGate,
    RetrievalGateDecision,
)
from buildguard.rag.citation import make_citation
from buildguard.rag.schemas import (
    CitationRecord,
    DocumentChunk,
    RagSearchInput,
    ScoredChunk,
)
from buildguard.rag.service import RagService
from buildguard.schemas.common import StrictSchema

AdvancedEvidenceStatus = Literal[
    "not_required",
    "local_source_required",
    "sufficient",
    "insufficient_evidence",
]


class AdvancedRetrievalResult(StrictSchema):
    query: str
    gate: RetrievalGateDecision
    rewritten_queries: list[str] = Field(default_factory=list, max_length=3)
    chunks: list[DocumentChunk] = Field(default_factory=list)
    scores: list[float] = Field(default_factory=list)
    citations: list[CitationRecord] = Field(default_factory=list)
    quality: RetrievalQuality | None = None
    evidence_status: AdvancedEvidenceStatus
    retrieval_attempts: int = Field(ge=0, le=2)
    correction_count: int = Field(ge=0, le=1)
    retrieval_latency_ms: float = Field(ge=0)
    internet_search_used: bool = False

    @model_validator(mode="after")
    def aligned_evidence(self) -> AdvancedRetrievalResult:
        if not (
            len(self.chunks) == len(self.scores) == len(self.citations)
        ):
            raise ValueError("advanced evidence arrays must have equal lengths")
        return self


def _matches_request(chunk: DocumentChunk, request: RagSearchInput) -> bool:
    filters = {item.lower() for item in request.document_filters}
    return (
        (
            not filters
            or chunk.document_name.lower() in filters
            or str(chunk.source_path).lower() in filters
        )
        and (
            request.project_filter is None
            or chunk.project == request.project_filter
        )
    )


class AdvancedRagPipeline:
    """Gate, score, correct once, and refuse without local evidence."""

    def __init__(
        self,
        service: RagService,
        gate: RetrievalGate,
        rewriter: QueryRewriter,
        quality: RetrievalQualityEvaluator,
        config: AdvancedRagConfig,
    ) -> None:
        self.service = service
        self.gate = gate
        self.rewriter = rewriter
        self.quality = quality
        self.config = config

    def _weighted_rank(
        self,
        request: RagSearchInput,
        queries: list[str],
        *,
        bm25_weight: float,
        dense_weight: float,
        limit: int,
    ) -> list[ScoredChunk]:
        aggregate: dict[str, float] = {}
        chunks: dict[str, DocumentChunk] = {}
        for query in queries:
            sources = (
                (
                    self.service.bm25.search(query, limit),
                    bm25_weight,
                ),
                (
                    self.service.dense.search(query, limit),
                    dense_weight,
                ),
            )
            for ranked, weight in sources:
                for item in ranked:
                    if not _matches_request(item.chunk, request):
                        continue
                    chunks[item.chunk.chunk_id] = item.chunk
                    aggregate[item.chunk.chunk_id] = (
                        aggregate.get(item.chunk.chunk_id, 0.0)
                        + weight / (self.service.config.rrf_k + item.rank)
                    )
        fused = [
            ScoredChunk(
                chunk=chunks[chunk_id],
                score=score / max(1, len(queries)),
                rank=rank,
                source="fusion",
            )
            for rank, (chunk_id, score) in enumerate(
                sorted(
                    aggregate.items(),
                    key=lambda item: (-item[1], item[0]),
                )[:limit],
                start=1,
            )
        ]
        return self.service.reranker.rerank(
            request.query,
            fused,
            limit,
        )

    @staticmethod
    def _result(
        *,
        request: RagSearchInput,
        gate: RetrievalGateDecision,
        rewritten_queries: list[str],
        ranked: list[ScoredChunk],
        quality: RetrievalQuality | None,
        status: AdvancedEvidenceStatus,
        attempts: int,
        corrections: int,
        started: float,
    ) -> AdvancedRetrievalResult:
        return AdvancedRetrievalResult(
            query=request.query,
            gate=gate,
            rewritten_queries=rewritten_queries,
            chunks=[item.chunk for item in ranked],
            scores=[item.score for item in ranked],
            citations=[make_citation(item.chunk) for item in ranked],
            quality=quality,
            evidence_status=status,
            retrieval_attempts=attempts,
            correction_count=corrections,
            retrieval_latency_ms=(time.perf_counter() - started) * 1000,
            internet_search_used=False,
        )

    def retrieve(self, request: RagSearchInput) -> AdvancedRetrievalResult:
        started = time.perf_counter()
        if not self.config.enabled:
            decision = RetrievalGateDecision(
                need_retrieval=True,
                query_type="standard",
                reason="Advanced RAG is disabled; using the standard local hybrid retriever.",
                requested_sources=["construction_standards"],
            )
            standard = self.service.search(request)
            ranked = [
                ScoredChunk(
                    chunk=chunk,
                    score=score,
                    rank=rank,
                    source="reranker",
                )
                for rank, (chunk, score) in enumerate(
                    zip(standard.chunks, standard.scores, strict=True),
                    start=1,
                )
            ]
            quality = self.quality.evaluate(
                request.query,
                standard.chunks,
                standard.scores,
            )
            return self._result(
                request=request,
                gate=decision,
                rewritten_queries=[request.query],
                ranked=ranked,
                quality=quality,
                status=standard.evidence_status,
                attempts=1,
                corrections=0,
                started=started,
            )
        decision = self.gate.decide(request.query)
        if not decision.need_retrieval:
            return self._result(
                request=request,
                gate=decision,
                rewritten_queries=[],
                ranked=[],
                quality=None,
                status="not_required",
                attempts=0,
                corrections=0,
                started=started,
            )
        if "construction_standards" not in decision.requested_sources:
            return self._result(
                request=request,
                gate=decision,
                rewritten_queries=[],
                ranked=[],
                quality=None,
                status="local_source_required",
                attempts=0,
                corrections=0,
                started=started,
            )
        initial_limit = max(request.top_k, self.config.initial_top_k)
        initial = self._weighted_rank(
            request,
            [request.query],
            bm25_weight=self.config.initial_bm25_weight,
            dense_weight=self.config.initial_dense_weight,
            limit=initial_limit,
        )
        initial_quality = self.quality.evaluate(
            request.query,
            [item.chunk for item in initial],
            [item.score for item in initial],
        )
        if initial_quality.action == "generate":
            return self._result(
                request=request,
                gate=decision,
                rewritten_queries=[request.query],
                ranked=initial,
                quality=initial_quality,
                status="sufficient",
                attempts=1,
                corrections=0,
                started=started,
            )
        if (
            initial_quality.action == "refuse"
            or self.config.max_corrections == 0
        ):
            return self._result(
                request=request,
                gate=decision,
                rewritten_queries=[request.query],
                ranked=initial,
                quality=initial_quality,
                status="insufficient_evidence",
                attempts=1,
                corrections=0,
                started=started,
            )
        rewrites = self.rewriter.rewrite(request.query)
        corrected = self._weighted_rank(
            request,
            rewrites.queries,
            bm25_weight=self.config.corrective_bm25_weight,
            dense_weight=self.config.corrective_dense_weight,
            limit=max(request.top_k, self.config.corrective_top_k),
        )
        corrected_quality = self.quality.evaluate(
            request.query,
            [item.chunk for item in corrected],
            [item.score for item in corrected],
        )
        return self._result(
            request=request,
            gate=decision,
            rewritten_queries=rewrites.queries,
            ranked=corrected,
            quality=corrected_quality,
            status=(
                "sufficient"
                if corrected_quality.action == "generate"
                else "insufficient_evidence"
            ),
            attempts=2,
            corrections=1,
            started=started,
        )


def create_advanced_rag_pipeline(
    service: RagService,
    backend: LocalLLMBackend | None = None,
) -> AdvancedRagPipeline:
    config = service.config.advanced
    return AdvancedRagPipeline(
        service,
        RetrievalGate(config, backend),
        QueryRewriter(config, backend),
        RetrievalQualityEvaluator(config),
        config,
    )
