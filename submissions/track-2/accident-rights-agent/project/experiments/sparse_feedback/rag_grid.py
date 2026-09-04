"""EXP-03: reproducible Top-K x rerank-keep legal retrieval grid."""

from __future__ import annotations

import argparse
import csv
import json
import time
from pathlib import Path
from statistics import mean
from typing import Any

from app.memory.context_builder import estimate_tokens
from app.rag.service import build_retriever


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def run_rag_grid(
    output_dir: Path,
    *,
    config_path: Path = Path("experiments/configs/rag_grid.json"),
    questions_path: Path = Path(
        "experiments/configs/evaluation_questions.json"
    ),
    corpus_path: Path = Path("data/laws/legal_corpus.sqlite3"),
    qdrant_path: Path = Path("data/qdrant/legal"),
    embedding_provider: str | None = None,
    reranker_provider: str | None = None,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    config = _load(config_path)
    questions = _load(questions_path)["questions"]
    embedding = embedding_provider or str(config["embedding_provider"])
    reranker = reranker_provider or str(config["reranker_provider"])
    retriever = build_retriever(
        corpus_path=corpus_path,
        qdrant_path=qdrant_path,
        embedding_provider=embedding,
        reranker_provider=reranker,
    )
    rows: list[dict[str, Any]] = []
    try:
        for top_k in config["retrieval_top_k"]:
            for rerank_keep in config["rerank_keep"]:
                for question in questions:
                    retrieval_query = str(
                        question.get("retrieval_query") or question["question"]
                    )
                    started = time.perf_counter()
                    hits = retriever.search(
                        retrieval_query,
                        top_k=int(top_k),
                        candidate_k=max(12, int(top_k)),
                    )
                    latency = time.perf_counter() - started
                    selected = hits[: min(int(rerank_keep), len(hits))]
                    expected = set(question["expected_document_ids"])
                    retrieved_docs = {hit.chunk.document_id for hit in hits}
                    cited_docs = {hit.chunk.document_id for hit in selected}
                    recall = len(expected & retrieved_docs) / max(1, len(expected))
                    accuracy = len(expected & cited_docs) / max(1, len(cited_docs))
                    verifier_score = 100 * (0.55 * recall + 0.45 * accuracy)
                    rows.append(
                        {
                            "configuration": f"top{top_k}-rerank{rerank_keep}",
                            "retrieval_top_k": int(top_k),
                            "rerank_keep": int(rerank_keep),
                            "effective_rerank_keep": len(selected),
                            "question_id": question["question_id"],
                            "category": question["category"],
                            "retrieval_query": retrieval_query,
                            "retrieval_recall": round(recall, 6),
                            "citation_accuracy": round(accuracy, 6),
                            "latency_seconds": round(latency, 6),
                            "token_usage": estimate_tokens(
                                [
                                    hit.citation().model_dump(mode="json")
                                    for hit in selected
                                ]
                            ),
                            "final_verifier_score": round(verifier_score, 3),
                            "retrieved_document_ids": sorted(retrieved_docs),
                            "cited_document_ids": sorted(cited_docs),
                            "expected_document_ids": sorted(expected),
                        }
                    )
    finally:
        retriever.close()
    aggregate = _aggregate(rows)
    payload = {
        "schema_version": 1,
        "embedding_provider": embedding,
        "reranker_provider": reranker,
        "question_count": len(questions),
        "configurations": aggregate,
        "rows": rows,
    }
    (output_dir / "rag_grid_results.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    _write_csv(output_dir / "rag_grid_results.csv", rows)
    return payload


def _aggregate(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(str(row["configuration"]), []).append(row)
    return [
        {
            "configuration": name,
            "retrieval_top_k": values[0]["retrieval_top_k"],
            "rerank_keep": values[0]["rerank_keep"],
            "retrieval_recall": round(mean(row["retrieval_recall"] for row in values), 6),
            "citation_accuracy": round(mean(row["citation_accuracy"] for row in values), 6),
            "latency_seconds": round(mean(row["latency_seconds"] for row in values), 6),
            "token_usage": round(mean(row["token_usage"] for row in values), 3),
            "final_verifier_score": round(
                mean(row["final_verifier_score"] for row in values), 3
            ),
        }
        for name, values in sorted(groups.items())
    ]


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = [
        "configuration",
        "retrieval_top_k",
        "rerank_keep",
        "effective_rerank_keep",
        "question_id",
        "category",
        "retrieval_query",
        "retrieval_recall",
        "citation_accuracy",
        "latency_seconds",
        "token_usage",
        "final_verifier_score",
        "retrieved_document_ids",
        "cited_document_ids",
        "expected_document_ids",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    **row,
                    "retrieved_document_ids": "|".join(row["retrieved_document_ids"]),
                    "cited_document_ids": "|".join(row["cited_document_ids"]),
                    "expected_document_ids": "|".join(row["expected_document_ids"]),
                }
            )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir", type=Path, default=Path("experiments/results")
    )
    parser.add_argument("--embedding-provider")
    parser.add_argument("--reranker-provider")
    args = parser.parse_args()
    result = run_rag_grid(
        args.output_dir,
        embedding_provider=args.embedding_provider,
        reranker_provider=args.reranker_provider,
    )
    print(json.dumps(result["configurations"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
