"""Retrieval, citation, grounding, and refusal metrics."""

from __future__ import annotations

import math

from pydantic import Field

from buildguard.schemas.common import StrictSchema


class RagEvaluationCase(StrictSchema):
    case_id: str = Field(min_length=1, max_length=256)
    relevant_chunk_ids: list[str] = Field(default_factory=list)
    retrieved_chunk_ids: list[str] = Field(default_factory=list)
    citation_supported: list[bool] = Field(default_factory=list)
    claim_supported: list[bool] = Field(default_factory=list)
    expected_refusal: bool = False
    actual_refusal: bool = False


class RagMetrics(StrictSchema):
    recall_at_5: float = Field(ge=0, le=1)
    recall_at_10: float = Field(ge=0, le=1)
    mrr: float = Field(ge=0, le=1)
    ndcg_at_10: float = Field(ge=0, le=1)
    citation_accuracy: float = Field(ge=0, le=1)
    unsupported_claim_rate: float = Field(ge=0, le=1)
    refusal_accuracy: float = Field(ge=0, le=1)
    evaluated_cases: int = Field(ge=0)


def _retrieval_scores(case: RagEvaluationCase) -> tuple[float, float, float, float]:
    relevant = set(case.relevant_chunk_ids)
    if not relevant:
        return 0, 0, 0, 0
    ranked = case.retrieved_chunk_ids
    recall_5 = len(relevant & set(ranked[:5])) / len(relevant)
    recall_10 = len(relevant & set(ranked[:10])) / len(relevant)
    first = next(
        (rank for rank, chunk_id in enumerate(ranked, start=1) if chunk_id in relevant),
        None,
    )
    mrr = 1 / first if first is not None else 0
    dcg = sum(
        1 / math.log2(rank + 1)
        for rank, chunk_id in enumerate(ranked[:10], start=1)
        if chunk_id in relevant
    )
    ideal = sum(
        1 / math.log2(rank + 1)
        for rank in range(1, min(len(relevant), 10) + 1)
    )
    return recall_5, recall_10, mrr, dcg / ideal if ideal else 0


def evaluate_rag(cases: list[RagEvaluationCase]) -> RagMetrics:
    count = len(cases)
    retrieval_cases = [case for case in cases if case.relevant_chunk_ids]
    scores = [_retrieval_scores(case) for case in retrieval_cases]
    retrieval_count = len(retrieval_cases)
    citations = [value for case in cases for value in case.citation_supported]
    claims = [value for case in cases for value in case.claim_supported]
    return RagMetrics(
        recall_at_5=(
            sum(item[0] for item in scores) / retrieval_count
            if retrieval_count
            else 0
        ),
        recall_at_10=(
            sum(item[1] for item in scores) / retrieval_count
            if retrieval_count
            else 0
        ),
        mrr=(
            sum(item[2] for item in scores) / retrieval_count
            if retrieval_count
            else 0
        ),
        ndcg_at_10=(
            sum(item[3] for item in scores) / retrieval_count
            if retrieval_count
            else 0
        ),
        citation_accuracy=(
            sum(citations) / len(citations) if citations else 0
        ),
        unsupported_claim_rate=(
            sum(not value for value in claims) / len(claims) if claims else 0
        ),
        refusal_accuracy=(
            sum(case.expected_refusal == case.actual_refusal for case in cases) / count
            if count
            else 0
        ),
        evaluated_cases=count,
    )
