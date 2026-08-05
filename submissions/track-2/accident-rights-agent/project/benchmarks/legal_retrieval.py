"""Twelve-question legal retrieval regression benchmark."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.rag.service import build_retriever


def citation_complete(citation: dict[str, object]) -> bool:
    required = {
        "title",
        "version",
        "effective_date",
        "source_id",
        "source_url",
        "text_source_url",
        "quote_type",
        "quote",
        "retrieval_score",
    }
    return all(citation.get(key) not in (None, "") for key in required)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--questions",
        type=Path,
        default=Path("data/laws/regression_questions.json"),
    )
    parser.add_argument(
        "--corpus-db", type=Path, default=Path("data/laws/legal_corpus.sqlite3")
    )
    parser.add_argument(
        "--qdrant-path", type=Path, default=Path("data/qdrant/legal")
    )
    parser.add_argument(
        "--output", type=Path, default=Path("benchmarks/reports/legal-retrieval.json")
    )
    parser.add_argument(
        "--embedding-provider",
        choices=("bge", "hash"),
        default="hash",
        help="Local embedding implementation used to query the matching index.",
    )
    parser.add_argument(
        "--reranker-provider",
        choices=("bge", "heuristic"),
        default="heuristic",
        help="Local reranker implementation used for Top-10 to Top-4 ranking.",
    )
    args = parser.parse_args()
    questions = json.loads(args.questions.read_text(encoding="utf-8"))
    retriever = build_retriever(
        corpus_path=args.corpus_db,
        qdrant_path=args.qdrant_path,
        embedding_provider=args.embedding_provider,
        reranker_provider=args.reranker_provider,
    )
    rows: list[dict[str, object]] = []
    reciprocal_ranks: list[float] = []
    recalls: list[float] = []
    complete = 0
    total_citations = 0
    try:
        for question in questions:
            hits = retriever.search(question["question"], top_k=4)
            expected = {
                (item["document_id"], item["article_no"])
                for item in question["expected"]
            }
            rank = 0
            citations = []
            for index, hit in enumerate(hits, start=1):
                key = (hit.chunk.document_id, hit.chunk.article_no)
                if not rank and key in expected:
                    rank = index
                citation = hit.citation().model_dump(mode="json")
                citations.append(citation)
                total_citations += 1
                complete += int(citation_complete(citation))
            recalls.append(float(rank > 0))
            reciprocal_ranks.append(0.0 if not rank else 1.0 / rank)
            rows.append(
                {
                    "id": question["id"],
                    "question": question["question"],
                    "rank": rank,
                    "hits": citations,
                }
            )
    finally:
        retriever.vector_index.close()
    result = {
        "question_count": len(questions),
        "recall_at_4": sum(recalls) / len(recalls),
        "mrr": sum(reciprocal_ranks) / len(reciprocal_ranks),
        "citation_completeness": complete / max(1, total_citations),
        "embedding_provider": retriever.vector_index.embedding.name,
        "reranker": retriever.reranker.name,
        "reranker_degraded_reason": retriever.reranker.degraded_reason,
        "rows": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["recall_at_4"] >= 0.75 else 2


if __name__ == "__main__":
    raise SystemExit(main())
