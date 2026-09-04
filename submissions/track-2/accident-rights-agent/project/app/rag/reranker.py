"""Pluggable local rerankers with an explicit deterministic degradation."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Protocol, Sequence

from app.rag.embeddings import tokenize
from app.schemas.legal import LegalChunk


class Reranker(Protocol):
    name: str
    degraded_reason: str | None

    def score(
        self, query: str, chunks: Sequence[LegalChunk]
    ) -> list[float]: ...


class HeuristicReranker:
    name = "heuristic-overlap"

    def __init__(self, reason: str = "local reranker model not selected"):
        self.degraded_reason = reason

    def score(self, query: str, chunks: Sequence[LegalChunk]) -> list[float]:
        query_tokens = set(tokenize(query))
        normalized_query = re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", query.lower())
        scores: list[float] = []
        for chunk in chunks:
            chunk_tokens = set(tokenize(chunk.text))
            overlap = len(query_tokens & chunk_tokens) / max(1, len(query_tokens))
            title_tokens = set(tokenize(chunk.title))
            title_coverage = len(query_tokens & title_tokens) / max(
                1, len(title_tokens)
            )
            title_bonus = 0.45 * title_coverage
            identifier_parts = [
                part
                for part in re.findall(r"[a-z]+|\d+", chunk.document_id.lower())
                if part != "cn" and not (len(part) == 4 and part.isdigit())
            ]
            identifier_bonus = (
                0.30
                if len(identifier_parts) >= 2
                and all(part in normalized_query for part in identifier_parts[:2])
                else 0.0
            )
            article_bonus = 0.08 if chunk.article_no else 0.0
            definition_bonus = (
                0.55
                if "定义" in query
                and "是指" in chunk.text
                and chunk.article_no is not None
                else 0.0
            )
            compensation_order_bonus = (
                0.65
                if (
                    "赔偿顺序" in query
                    or (
                        "交强险" in query
                        and "商业三者险" in query
                        and "侵权人" in query
                    )
                )
                and "先由" in chunk.text
                and "不足部分" in chunk.text
                and "侵权人" in chunk.text
                else 0.0
            )
            scores.append(
                overlap
                + article_bonus
                + title_bonus
                + identifier_bonus
                + definition_bonus
                + compensation_order_bonus
            )
        return scores


class BgeReranker:
    name = "BAAI/bge-reranker-v2-m3"
    degraded_reason = None

    def __init__(self, model_path: Path | str, *, device: str = "cpu"):
        try:
            from sentence_transformers import CrossEncoder
        except ImportError as exc:
            raise RuntimeError(
                "Install the 'local-models' extra before enabling BGE reranking."
            ) from exc
        path = Path(model_path)
        if not path.exists():
            raise FileNotFoundError(
                f"Local reranker path does not exist: {path}. Remote loading is disabled."
            )
        self._model = CrossEncoder(str(path), device=device)

    def score(self, query: str, chunks: Sequence[LegalChunk]) -> list[float]:
        values = self._model.predict(
            [(query, chunk.text) for chunk in chunks],
            show_progress_bar=False,
        )
        return [float(value) for value in values]
