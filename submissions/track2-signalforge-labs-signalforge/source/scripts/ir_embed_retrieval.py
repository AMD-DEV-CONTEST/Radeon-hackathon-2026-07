#!/usr/bin/env python3
"""Embed silent IR projections and compare exact cosine, Qdrant, BM25, and RRF."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import platform
from pathlib import Path
import statistics
import time
from typing import Any

import ir_eval_retrieval


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--eval", type=Path, required=True)
    parser.add_argument("--projections", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--vectors", type=Path, required=True)
    parser.add_argument("--vector-records", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--split", choices=("development", "sealed_holdout", "all"), default="development")
    return parser.parse_args()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def parse_time(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def metrics(questions: list[dict[str, Any]], results: dict[str, list[str]], chunks: dict[str, dict[str, Any]]) -> dict[str, float | int]:
    recall = precision = complete = citation = context = 0.0
    answerable = abstentions = abstain_correct = 0
    for question in questions:
        hits = results[question["question_id"]][: question["top_k"]]
        relevant = set(question["relevant_chunk_ids"])
        found = relevant.intersection(hits)
        if question["expected_abstain"]:
            abstentions += 1
            abstain_correct += not hits
        else:
            answerable += 1
            recall += len(found) / len(relevant)
            precision += len(found) / len(hits) if hits else 0
            complete += found == relevant
        citation += sum(item in chunks for item in hits) / len(hits) if hits else 1
        context += sum(chunks[item]["token_estimate"] for item in hits)
    return {
        "question_count": len(questions),
        "answerable_count": answerable,
        "abstention_count": abstentions,
        "recall_at_k": recall / answerable if answerable else 0,
        "precision_at_k": precision / answerable if answerable else 0,
        "complete_evidence_rate": complete / answerable if answerable else 0,
        "abstention_accuracy": abstain_correct / abstentions if abstentions else 1,
        "citation_correctness": citation / len(questions) if questions else 0,
        "mean_context_tokens": context / len(questions) if questions else 0,
    }


def latency(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    return {
        "p50_ms": statistics.median(ordered),
        "p95_ms": ordered[int((len(ordered) - 1) * 0.95)],
    }


def rrf(first: list[str], second: list[str], top_k: int, offset: int = 60) -> list[str]:
    scores: dict[str, float] = {}
    for ranking in (first, second):
        for rank, item in enumerate(ranking, 1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (offset + rank)
    return [item for item, _ in sorted(scores.items(), key=lambda value: (-value[1], value[0]))[:top_k]]


def main() -> int:
    args = parse_args()
    import numpy as np
    from qdrant_client import QdrantClient, models
    from sentence_transformers import SentenceTransformer

    evaluation = json.loads(args.eval.read_text())
    config = json.loads(args.config.read_text())
    embedding_config_sha256 = hashlib.sha256(args.config.read_bytes()).hexdigest()
    projections = {item["chunk_id"]: item for item in read_jsonl(args.projections)}
    chunks = {item["chunk_id"]: item for item in evaluation["chunks"]}
    questions = [item for item in evaluation["questions"] if args.split == "all" or item["split"] == args.split]
    chunk_ids = sorted(
        chunk_id
        for chunk_id, chunk in chunks.items()
        if any(
            chunk["company_id"] in question["company_ids"]
            and chunk["document_type"] in question["document_types"]
            and parse_time(chunk["available_at"]) <= parse_time(question["as_of"])
            for question in questions
        )
    )
    if any(chunk_id not in projections for chunk_id in chunk_ids):
        raise SystemExit("an evaluation chunk has no semantic projection")
    started = time.perf_counter()
    model = SentenceTransformer(config["model_id"], revision=config["revision"], device=args.device)
    load_seconds = time.perf_counter() - started
    chunk_inputs = [projections[item]["text"] for item in chunk_ids]
    question_inputs = [item["text"] for item in questions]
    started = time.perf_counter()
    chunk_vectors = model.encode(chunk_inputs, batch_size=args.batch_size, normalize_embeddings=True, convert_to_numpy=True)
    question_vectors = model.encode(question_inputs, batch_size=args.batch_size, normalize_embeddings=True, convert_to_numpy=True)
    encode_seconds = time.perf_counter() - started
    if chunk_vectors.shape[1] != config["dimensions"]:
        raise SystemExit("embedding dimension differs from pinned configuration")
    args.vectors.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(args.vectors, chunk_ids=np.array(chunk_ids), chunk_vectors=chunk_vectors, question_vectors=question_vectors)

    records = []
    for chunk_id, vector in zip(chunk_ids, chunk_vectors):
        chunk = chunks[chunk_id]
        vector_sha = hashlib.sha256(vector.astype("float32").tobytes()).hexdigest()
        records.append(
            {
                "schema_version": "signalforge/ir-vector-record/v1",
                "vector_id": "vector-" + chunk_id,
                "projection_id": projections[chunk_id]["projection_id"],
                "chunk_id": chunk_id,
                "company_id": chunk["company_id"],
                "available_at": chunk["available_at"],
                "authority_tier": chunk["authority_tier"],
                "document_type": chunk["document_type"],
                "rights_class": chunk["rights_class"],
                "document_sha256": chunk["document_sha256"],
                "source_content_sha256": chunk["content_sha256"],
                "projection_sha256": projections[chunk_id]["projection_sha256"],
                "embedding_model": config["model_id"],
                "embedding_revision": config["revision"],
                "embedding_config_sha256": embedding_config_sha256,
                "dimension": int(vector.shape[0]),
                "vector_sha256": vector_sha,
            }
        )
    args.vector_records.parent.mkdir(parents=True, exist_ok=True)
    with args.vector_records.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True) + "\n")

    exact_results: dict[str, list[str]] = {}
    exact_latencies: list[float] = []
    bm25_results: dict[str, list[str]] = {}
    fused_results: dict[str, list[str]] = {}
    for question, vector in zip(questions, question_vectors):
        eligible_indices = [
            index for index, chunk_id in enumerate(chunk_ids)
            if chunks[chunk_id]["company_id"] in question["company_ids"]
            and chunks[chunk_id]["document_type"] in question["document_types"]
            and parse_time(chunks[chunk_id]["available_at"]) <= parse_time(question["as_of"])
        ]
        begin = time.perf_counter()
        scored = sorted(
            ((float(chunk_vectors[index] @ vector), chunk_ids[index]) for index in eligible_indices),
            key=lambda item: (-item[0], item[1]),
        )
        exact_latencies.append((time.perf_counter() - begin) * 1000)
        exact_results[question["question_id"]] = [item[1] for item in scored[: question["top_k"]]]
        eligible_chunks = [chunks[chunk_ids[index]] for index in eligible_indices]
        lexical = [item[1] for item in ir_eval_retrieval.bm25(question["text"], eligible_chunks)[: question["top_k"]]]
        bm25_results[question["question_id"]] = lexical
        fused_results[question["question_id"]] = rrf(lexical, exact_results[question["question_id"]], question["top_k"])

    qdrant = QdrantClient(":memory:")
    collection = "signalforge_ir"
    qdrant.create_collection(collection_name=collection, vectors_config=models.VectorParams(size=config["dimensions"], distance=models.Distance.COSINE))
    qdrant.upsert(
        collection_name=collection,
        wait=True,
        points=[
            models.PointStruct(
                id=index,
                vector=vector.tolist(),
                payload={
                    "chunk_id": chunk_id,
                    "company_id": chunks[chunk_id]["company_id"],
                    "document_type": chunks[chunk_id]["document_type"],
                    "available_at_epoch": parse_time(chunks[chunk_id]["available_at"]).timestamp(),
                },
            )
            for index, (chunk_id, vector) in enumerate(zip(chunk_ids, chunk_vectors))
        ],
    )
    qdrant_results: dict[str, list[str]] = {}
    qdrant_latencies: list[float] = []
    for question, vector in zip(questions, question_vectors):
        query_filter = models.Filter(
            must=[
                models.FieldCondition(key="company_id", match=models.MatchAny(any=question["company_ids"])),
                models.FieldCondition(key="document_type", match=models.MatchAny(any=question["document_types"])),
                models.FieldCondition(
                    key="available_at_epoch",
                    range=models.Range(lte=parse_time(question["as_of"]).timestamp()),
                ),
            ]
        )
        begin = time.perf_counter()
        response = qdrant.query_points(collection_name=collection, query=vector.tolist(), query_filter=query_filter, limit=question["top_k"], with_payload=True)
        qdrant_latencies.append((time.perf_counter() - begin) * 1000)
        qdrant_results[question["question_id"]] = [point.payload["chunk_id"] for point in response.points]
    report = {
        "schema_version": "signalforge/ir-embedding-comparison/v1",
        "model": {"id": config["model_id"], "revision": config["revision"], "dimension": config["dimensions"]},
        "runtime": {"python": platform.python_version(), "platform": platform.platform(), "device": args.device},
        "population_sha256": hashlib.sha256(args.eval.read_bytes()).hexdigest(),
        "split": args.split,
        "projection_sha256": hashlib.sha256(args.projections.read_bytes()).hexdigest(),
        "embedded_scope": "selected split company and document-type filters",
        "embedded_chunk_count": len(chunk_ids),
        "load_seconds": load_seconds,
        "encode_seconds": encode_seconds,
        "chunks_per_second": len(chunk_ids) / encode_seconds,
        "bm25": {"metrics": metrics(questions, bm25_results, chunks)},
        "exact_cosine": {"metrics": metrics(questions, exact_results, chunks), "latency": latency(exact_latencies)},
        "qdrant": {"metrics": metrics(questions, qdrant_results, chunks), "latency": latency(qdrant_latencies)},
        "rrf": {"metrics": metrics(questions, fused_results, chunks)},
        "qdrant_ranking_equivalent": exact_results == qdrant_results,
        "claim_boundary": "Silver labels and private pending-rights artifacts support architecture selection only, not product accuracy claims.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"chunks_per_second": report["chunks_per_second"], "qdrant_ranking_equivalent": report["qdrant_ranking_equivalent"], "metrics": {key: value["metrics"] for key, value in report.items() if isinstance(value, dict) and "metrics" in value}}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
