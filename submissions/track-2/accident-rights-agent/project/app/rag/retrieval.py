"""BM25 + dense reciprocal-rank fusion and Top-10 -> Top-4 reranking."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from rank_bm25 import BM25Okapi

from app.rag.corpus import LegalCorpusStore
from app.rag.embeddings import tokenize
from app.rag.index import LegalVectorIndex
from app.rag.reranker import HeuristicReranker, Reranker
from app.schemas.legal import LegalChunk, LegalCitation


@dataclass(frozen=True)
class RetrievalHit:
    chunk: LegalChunk
    fused_score: float
    rerank_score: float

    def citation(self) -> LegalCitation:
        return LegalCitation.from_chunk(self.chunk, self.rerank_score)


class HybridLegalRetriever:
    def __init__(
        self,
        corpus: LegalCorpusStore,
        vector_index: LegalVectorIndex,
        *,
        reranker: Reranker | None = None,
        as_of: date | None = None,
    ):
        self.corpus = corpus
        self.vector_index = vector_index
        self.reranker = reranker or HeuristicReranker()
        self.as_of = as_of or date.today()

    def search(
        self,
        query: str,
        *,
        top_k: int = 4,
        candidate_k: int = 10,
        jurisdiction: str = "中华人民共和国",
        document_types: set[str] | None = None,
    ) -> list[RetrievalHit]:
        chunks = self.corpus.list_chunks(
            as_of=self.as_of,
            jurisdiction=jurisdiction,
            document_types=document_types,
        )
        if not chunks:
            return []
        by_id = {chunk.source_id: chunk for chunk in chunks}
        bm25 = BM25Okapi([tokenize(chunk.title + " " + chunk.text) for chunk in chunks])
        lexical_scores = bm25.get_scores(tokenize(query))
        lexical_rank = sorted(
            zip(chunks, lexical_scores, strict=True),
            key=lambda item: float(item[1]),
            reverse=True,
        )[:candidate_k]
        dense_rank = [
            (source_id, score)
            for source_id, score in self.vector_index.search(
                query,
                limit=max(candidate_k * 2, candidate_k),
                jurisdiction=jurisdiction,
                document_types=document_types,
                effective_as_of=self.as_of,
            )
            if source_id in by_id
        ][:candidate_k]
        fused: dict[str, float] = {}
        for rank, (chunk, _score) in enumerate(lexical_rank, start=1):
            fused[chunk.source_id] = fused.get(chunk.source_id, 0.0) + 1.0 / (60 + rank)
        for rank, (source_id, _score) in enumerate(dense_rank, start=1):
            fused[source_id] = fused.get(source_id, 0.0) + 1.0 / (60 + rank)
        candidates = sorted(
            (by_id[source_id] for source_id in fused),
            key=lambda chunk: fused[chunk.source_id],
            reverse=True,
        )[:candidate_k]
        rerank_scores = self.reranker.score(query, candidates)
        hits = [
            RetrievalHit(
                chunk=chunk,
                fused_score=fused[chunk.source_id],
                rerank_score=float(score),
            )
            for chunk, score in zip(candidates, rerank_scores, strict=True)
        ]
        return sorted(
            hits,
            key=lambda hit: (hit.rerank_score, hit.fused_score),
            reverse=True,
        )[:top_k]

    def citations(
        self,
        query: str,
        *,
        top_k: int = 4,
        candidate_k: int = 10,
        jurisdiction: str = "中华人民共和国",
        document_types: set[str] | None = None,
    ) -> list[LegalCitation]:
        return [
            hit.citation()
            for hit in self.search(
                query,
                top_k=top_k,
                candidate_k=candidate_k,
                jurisdiction=jurisdiction,
                document_types=document_types,
            )
        ]

    def close(self) -> None:
        self.vector_index.close()
