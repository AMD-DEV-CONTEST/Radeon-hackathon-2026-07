"""Offline comparison of baseline and advanced retrieval strategies."""

from __future__ import annotations

import math
import time
from typing import Literal

from pydantic import Field

from buildguard.rag.advanced.answer_grounding import AnswerGrounder
from buildguard.rag.advanced.corrective_retriever import AdvancedRagPipeline
from buildguard.rag.fusion import reciprocal_rank_fusion
from buildguard.rag.schemas import RagSearchInput, ScoredChunk
from buildguard.rag.service import RagService
from buildguard.schemas.common import StrictSchema

RetrievalStrategy = Literal[
    "BM25",
    "Dense",
    "Hybrid",
    "Hybrid+Reranker",
    "Advanced Corrective RAG",
]


class AdvancedEvaluationExample(StrictSchema):
    question: str = Field(min_length=1, max_length=4000)
    relevant_chunk_ids: list[str] = Field(default_factory=list)
    expected_refusal: bool = False
    candidate_answer: str | None = Field(default=None, max_length=100_000)


class AdvancedEvaluationMetrics(StrictSchema):
    strategy: RetrievalStrategy
    recall_at_5: float = Field(ge=0, le=1)
    recall_at_10: float = Field(ge=0, le=1)
    mrr: float = Field(ge=0, le=1)
    ndcg: float = Field(ge=0, le=1)
    citation_accuracy: float = Field(ge=0, le=1)
    unsupported_claim_rate: float = Field(ge=0, le=1)
    grounded_answer_rate: float = Field(ge=0, le=1)
    refusal_accuracy: float = Field(ge=0, le=1)
    latency_ms: float = Field(ge=0)
    evaluated_questions: int = Field(ge=0)


def _question_metrics(
    ids: list[str],
    relevant: set[str],
) -> tuple[float, float, float, float]:
    if not relevant:
        return 0.0, 0.0, 0.0, 0.0
    recall_5 = len(relevant & set(ids[:5])) / len(relevant)
    recall_10 = len(relevant & set(ids[:10])) / len(relevant)
    first = next(
        (rank for rank, chunk_id in enumerate(ids, start=1) if chunk_id in relevant),
        None,
    )
    mrr = 1.0 / first if first is not None else 0.0
    dcg = sum(
        1.0 / math.log2(rank + 1)
        for rank, chunk_id in enumerate(ids[:10], start=1)
        if chunk_id in relevant
    )
    ideal = sum(
        1.0 / math.log2(rank + 1)
        for rank in range(1, min(len(relevant), 10) + 1)
    )
    return recall_5, recall_10, mrr, dcg / ideal if ideal else 0.0


class AdvancedRagEvaluator:
    def __init__(
        self,
        service: RagService,
        advanced: AdvancedRagPipeline,
        grounder: AnswerGrounder,
    ) -> None:
        self.service = service
        self.advanced = advanced
        self.grounder = grounder

    def _rank(
        self,
        question: str,
        strategy: RetrievalStrategy,
    ) -> tuple[list[ScoredChunk], bool]:
        request = RagSearchInput(query=question, top_k=10)
        if strategy == "BM25":
            ranked = self.service.bm25.search(question, 10)
            return ranked, not ranked
        if strategy == "Dense":
            ranked = self.service.dense.search(question, 10)
            return ranked, not ranked
        if strategy == "Hybrid":
            ranked = reciprocal_rank_fusion(
                [
                    self.service.bm25.search(question, 20),
                    self.service.dense.search(question, 20),
                ],
                rrf_k=self.service.config.rrf_k,
                top_k=10,
            )
            return ranked, not ranked
        if strategy == "Hybrid+Reranker":
            ranked = self.service.retriever.rank(request, 10)
            return ranked, not ranked
        result = self.advanced.retrieve(request)
        ranked = [
            ScoredChunk(
                chunk=chunk,
                score=score,
                rank=rank,
                source="reranker",
            )
            for rank, (chunk, score) in enumerate(
                zip(result.chunks, result.scores, strict=True),
                start=1,
            )
        ]
        refused = result.evidence_status == "insufficient_evidence"
        return ranked, refused

    def evaluate(
        self,
        examples: list[AdvancedEvaluationExample],
    ) -> dict[RetrievalStrategy, AdvancedEvaluationMetrics]:
        strategies: tuple[RetrievalStrategy, ...] = (
            "BM25",
            "Dense",
            "Hybrid",
            "Hybrid+Reranker",
            "Advanced Corrective RAG",
        )
        results: dict[RetrievalStrategy, AdvancedEvaluationMetrics] = {}
        for strategy in strategies:
            strategy_started = time.perf_counter()
            recall_5 = 0.0
            recall_10 = 0.0
            mrr = 0.0
            ndcg = 0.0
            correct_citations = 0
            total_citations = 0
            unsupported = 0
            total_claims = 0
            correct_refusals = 0
            for example in examples:
                ranked, refused = self._rank(example.question, strategy)
                ids = [item.chunk.chunk_id for item in ranked]
                relevant = set(example.relevant_chunk_ids)
                metrics = _question_metrics(ids, relevant)
                recall_5 += metrics[0]
                recall_10 += metrics[1]
                mrr += metrics[2]
                ndcg += metrics[3]
                correct_citations += len(set(ids[:10]) & relevant)
                total_citations += len(ids[:10])
                correct_refusals += int(refused == example.expected_refusal)
                if example.candidate_answer is not None:
                    grounding = self.grounder.validate(
                        example.candidate_answer,
                        [item.chunk for item in ranked],
                    )
                    unsupported += len(grounding.unsupported_claims)
                    total_claims += (
                        len(grounding.supported_claims)
                        + len(grounding.unsupported_claims)
                    )
            count = len(examples)
            unsupported_rate = unsupported / total_claims if total_claims else 0.0
            results[strategy] = AdvancedEvaluationMetrics(
                strategy=strategy,
                recall_at_5=recall_5 / count if count else 0.0,
                recall_at_10=recall_10 / count if count else 0.0,
                mrr=mrr / count if count else 0.0,
                ndcg=ndcg / count if count else 0.0,
                citation_accuracy=(
                    correct_citations / total_citations
                    if total_citations
                    else 0.0
                ),
                unsupported_claim_rate=unsupported_rate,
                grounded_answer_rate=1.0 - unsupported_rate,
                refusal_accuracy=(
                    correct_refusals / count if count else 0.0
                ),
                latency_ms=(time.perf_counter() - strategy_started)
                * 1000
                / max(1, count),
                evaluated_questions=count,
            )
        return results
