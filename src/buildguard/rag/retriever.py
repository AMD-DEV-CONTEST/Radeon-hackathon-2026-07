"""Hybrid retrieval and evidence quality gate."""

from __future__ import annotations

import re
import time

from buildguard.config import RagConfig
from buildguard.rag.bm25_index import BM25Index
from buildguard.rag.citation import make_citation
from buildguard.rag.dense_index import DenseIndex
from buildguard.rag.embedding_backend import lexical_tokens
from buildguard.rag.fusion import reciprocal_rank_fusion
from buildguard.rag.reranker import Reranker
from buildguard.rag.schemas import RagSearchInput, RagSearchOutput, ScoredChunk

STANDARD_PATTERN = re.compile(
    r"\b(?:GB|GB/T|JGJ|JGJ/T|DB\d*/T?)\s*[\d.-]+", re.IGNORECASE
)


def _filter_candidates(
    candidates: list[ScoredChunk], request: RagSearchInput
) -> list[ScoredChunk]:
    document_filters = {item.lower() for item in request.document_filters}
    return [
        item
        for item in candidates
        if (
            not document_filters
            or item.chunk.document_name.lower() in document_filters
            or str(item.chunk.source_path).lower() in document_filters
        )
        and (
            request.project_filter is None
            or item.chunk.project == request.project_filter
        )
    ]


def evidence_is_sufficient(
    query: str,
    results: list[ScoredChunk],
    *,
    min_top_score: float,
    min_keyword_coverage: float,
) -> bool:
    if not results or results[0].score < min_top_score:
        return False
    combined = "\n".join(item.chunk.content.lower() for item in results)
    keywords = {token for token in lexical_tokens(query) if len(token) >= 2}
    coverage = (
        len({token for token in keywords if token in combined}) / len(keywords)
        if keywords
        else 1.0
    )
    if coverage < min_keyword_coverage:
        return False
    standards = {item.replace(" ", "").upper() for item in STANDARD_PATTERN.findall(query)}
    return not standards or all(
        standard in combined.replace(" ", "").upper() for standard in standards
    )


class HybridRetriever:
    def __init__(
        self,
        bm25: BM25Index,
        dense: DenseIndex,
        reranker: Reranker,
        config: RagConfig,
    ) -> None:
        self.bm25 = bm25
        self.dense = dense
        self.reranker = reranker
        self.config = config

    def _rank_with_metrics(
        self,
        request: RagSearchInput,
        limit: int,
    ) -> tuple[list[ScoredChunk], list[str], dict[str, float]]:
        stage_started = time.perf_counter()
        bm25 = _filter_candidates(
            self.bm25.search(request.query, self.config.bm25_top_k),
            request,
        )
        bm25_ms = (time.perf_counter() - stage_started) * 1000
        stage_started = time.perf_counter()
        dense = _filter_candidates(
            self.dense.search(request.query, self.config.dense_top_k),
            request,
        )
        dense_ms = (time.perf_counter() - stage_started) * 1000
        stage_started = time.perf_counter()
        fused = reciprocal_rank_fusion(
            [bm25, dense],
            rrf_k=self.config.rrf_k,
            top_k=self.config.fusion_top_k,
        )
        fusion_ms = (time.perf_counter() - stage_started) * 1000
        stage_started = time.perf_counter()
        final = self.reranker.rerank(request.query, fused, limit)
        reranker_ms = (time.perf_counter() - stage_started) * 1000
        return final, [item.chunk.chunk_id for item in fused], {
            "bm25": bm25_ms,
            "dense": dense_ms,
            "fusion": fusion_ms,
            "reranker": reranker_ms,
        }

    def rank(self, request: RagSearchInput, limit: int) -> list[ScoredChunk]:
        final, _, _ = self._rank_with_metrics(request, limit)
        return final

    def search(self, request: RagSearchInput) -> RagSearchOutput:
        started = time.perf_counter()
        limit = min(request.top_k, self.config.final_top_k)
        final, retrieved_ids, stage_metrics = self._rank_with_metrics(request, limit)
        sufficient = evidence_is_sufficient(
            request.query,
            final,
            min_top_score=self.config.min_top_score,
            min_keyword_coverage=self.config.min_keyword_coverage,
        )
        return RagSearchOutput(
            chunks=[item.chunk for item in final],
            retrieved_chunk_ids=retrieved_ids,
            reranked_chunk_ids=[item.chunk.chunk_id for item in final],
            scores=[item.score for item in final],
            citations=[make_citation(item.chunk) for item in final],
            evidence_status="sufficient" if sufficient else "insufficient_evidence",
            retrieval_latency_ms=(time.perf_counter() - started) * 1000,
            stage_latency_ms=stage_metrics,
        )
