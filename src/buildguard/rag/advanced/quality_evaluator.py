"""Evidence quality scoring with configured action boundaries."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import Field

from buildguard.config import AdvancedRagConfig
from buildguard.rag.embedding_backend import lexical_tokens
from buildguard.rag.retriever import STANDARD_PATTERN
from buildguard.rag.schemas import DocumentChunk
from buildguard.schemas.common import StrictSchema

QualityAction = Literal["generate", "correct", "refuse"]


class RetrievalQuality(StrictSchema):
    reranker_score: float = Field(ge=0, le=1)
    keyword_coverage: float = Field(ge=0, le=1)
    entity_coverage: float = Field(ge=0, le=1)
    score: float = Field(ge=0, le=1)
    action: QualityAction


def _coverage(needles: set[str], haystack: str) -> float:
    if not needles:
        return 1.0
    return len({item for item in needles if item in haystack}) / len(needles)


class RetrievalQualityEvaluator:
    def __init__(self, config: AdvancedRagConfig) -> None:
        self.config = config

    def _entities(self, query: str) -> set[str]:
        standards = {
            item.replace(" ", "").upper()
            for item in STANDARD_PATTERN.findall(query)
        }
        articles = set(re.findall(r"第[一二三四五六七八九十百\d]+条", query))
        terms = {term for term in self.config.entity_terms if term in query}
        return standards | articles | terms

    def evaluate(
        self,
        query: str,
        chunks: list[DocumentChunk],
        scores: list[float],
    ) -> RetrievalQuality:
        if len(chunks) != len(scores):
            raise ValueError("retrieval chunks and scores must have equal length")
        combined = "\n".join(
            "\n".join(
                [
                    chunk.document_name,
                    chunk.article or "",
                    chunk.content,
                ]
            )
            for chunk in chunks
        ).lower()
        compact_upper = combined.replace(" ", "").upper()
        keywords = {
            token
            for token in lexical_tokens(query)
            if len(token) >= 2
        }
        entities = self._entities(query)
        keyword_coverage = _coverage(keywords, combined)
        entity_coverage = _coverage(
            {
                entity.replace(" ", "").upper()
                for entity in entities
            },
            compact_upper,
        )
        reranker_score = (
            max(0.0, min(1.0, scores[0]))
            if scores and chunks
            else 0.0
        )
        score = (
            0.5 * reranker_score
            + 0.3 * keyword_coverage
            + 0.2 * entity_coverage
        )
        if not chunks:
            action: QualityAction = "refuse"
        elif score >= self.config.quality_generate_threshold:
            action = "generate"
        elif score >= self.config.quality_correct_threshold:
            action = "correct"
        else:
            action = "refuse"
        return RetrievalQuality(
            reranker_score=reranker_score,
            keyword_coverage=keyword_coverage,
            entity_coverage=entity_coverage,
            score=score,
            action=action,
        )
