#!/usr/bin/env python3
"""Generate hash-pinned embeddings and compare exact cosine with Qdrant local mode."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import statistics
import time
from pathlib import Path

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--eval", default="fixtures/retrieval/golden-eval.json")
    parser.add_argument("--config", required=True)
    parser.add_argument("--vectors", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--repetitions", type=int, default=20)
    return parser.parse_args()


def metrics(evaluation: dict, results: dict[str, list[str]], chunks: dict[str, dict]) -> dict:
    recall = precision = complete = citations = context_tokens = 0.0
    for question in evaluation["questions"]:
        relevant = set(question["relevant_chunk_ids"])
        hits = results[question["question_id"]][: question["top_k"]]
        found = relevant.intersection(hits)
        recall += len(found) / len(relevant)
        precision += len(found) / len(hits) if hits else 0
        complete += len(found) == len(relevant)
        citations += sum(hit in chunks for hit in hits) / len(hits) if hits else 0
        context_tokens += sum(len(chunks[hit]["text"]) // 4 + 1 for hit in hits)
    count = len(evaluation["questions"])
    return {
        "question_count": count,
        "recall_at_k": recall / count,
        "precision_at_k": precision / count,
        "complete_evidence_rate": complete / count,
        "citation_correctness": citations / count,
        "mean_context_tokens": context_tokens / count,
    }


def latency(values: list[float]) -> dict:
    ordered = sorted(values)
    return {
        "p50_us": statistics.median(ordered),
        "p95_us": ordered[int((len(ordered) - 1) * 0.95)],
    }


def main() -> None:
    args = parse_args()

    from qdrant_client import QdrantClient, models
    from sentence_transformers import SentenceTransformer

    if args.repetitions < 1:
        raise SystemExit("--repetitions must be positive")
    eval_path, config_path = Path(args.eval), Path(args.config)
    eval_bytes = eval_path.read_bytes()
    evaluation, config = json.loads(eval_bytes), json.loads(config_path.read_text())
    chunks = {item["chunk_id"]: item for item in evaluation["chunks"]}
    questions = {item["question_id"]: item for item in evaluation["questions"]}

    started = time.perf_counter()
    model = SentenceTransformer(config["model_id"], revision=config["revision"], device="cpu")
    load_seconds = time.perf_counter() - started
    chunk_ids = list(chunks)
    question_ids = list(questions)
    chunk_inputs = [f"{chunks[item]['section']}\n{chunks[item]['text']}" for item in chunk_ids]
    question_inputs = [questions[item]["text"] for item in question_ids]
    started = time.perf_counter()
    chunk_vectors = model.encode(chunk_inputs, normalize_embeddings=True, convert_to_numpy=True)
    question_vectors = model.encode(question_inputs, normalize_embeddings=True, convert_to_numpy=True)
    encode_seconds = time.perf_counter() - started
    if chunk_vectors.shape[1] != config["dimensions"]:
        raise SystemExit(f"configured dimension {config['dimensions']} differs from {chunk_vectors.shape[1]}")

    dataset_sha = hashlib.sha256(eval_bytes).hexdigest()
    vector_fixture = {
        "schema_version": "signalforge/retrieval-vectors/v1",
        "model_id": config["model_id"],
        "revision": config["revision"],
        "dimension": int(chunk_vectors.shape[1]),
        "dataset_sha256": dataset_sha,
        "chunks": [{"id": item, "vector": vector.tolist()} for item, vector in zip(chunk_ids, chunk_vectors)],
        "questions": [{"id": item, "vector": vector.tolist()} for item, vector in zip(question_ids, question_vectors)],
    }
    vector_path = Path(args.vectors)
    vector_path.parent.mkdir(parents=True, exist_ok=True)
    vector_path.write_text(json.dumps(vector_fixture, indent=2) + "\n")

    qdrant = QdrantClient(":memory:")
    collection = "signalforge_retrieval_eval"
    qdrant.create_collection(
        collection_name=collection,
        vectors_config=models.VectorParams(size=int(chunk_vectors.shape[1]), distance=models.Distance.COSINE),
    )
    company_by_document = {item["document_id"]: item["company_id"] for item in evaluation["sources"]}
    qdrant.upsert(
        collection_name=collection,
        wait=True,
        points=[
            models.PointStruct(
                id=index,
                vector=vector.tolist(),
                payload={"chunk_id": chunk_id, "company_id": company_by_document[chunks[chunk_id]["document_id"]]},
            )
            for index, (chunk_id, vector) in enumerate(zip(chunk_ids, chunk_vectors))
        ],
    )

    qdrant_results: dict[str, list[str]] = {}
    qdrant_latencies: list[float] = []
    memory_results: dict[str, list[str]] = {}
    memory_latencies: list[float] = []
    for repetition in range(args.repetitions):
        for question_id, vector in zip(question_ids, question_vectors):
            question = questions[question_id]
            allowed = set(question.get("company_ids", []))
            begin = time.perf_counter_ns()
            scored = sorted(
                (
                    (float(chunk_vector @ vector), chunk_id)
                    for chunk_id, chunk_vector in zip(chunk_ids, chunk_vectors)
                    if not allowed or company_by_document[chunks[chunk_id]["document_id"]] in allowed
                ),
                key=lambda item: (-item[0], item[1]),
            )
            memory_latencies.append((time.perf_counter_ns() - begin) / 1000)
            if repetition == 0:
                memory_results[question_id] = [item[1] for item in scored[: question["top_k"]]]

            condition = None
            if allowed:
                condition = models.Filter(
                    must=[models.FieldCondition(key="company_id", match=models.MatchAny(any=sorted(allowed)))]
                )
            begin = time.perf_counter_ns()
            response = qdrant.query_points(
                collection_name=collection,
                query=vector.tolist(),
                query_filter=condition,
                limit=question["top_k"],
                with_payload=True,
            )
            qdrant_latencies.append((time.perf_counter_ns() - begin) / 1000)
            if repetition == 0:
                qdrant_results[question_id] = [point.payload["chunk_id"] for point in response.points]

    report = {
        "schema_version": "signalforge/qdrant-comparison/v1",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "dataset_sha256": dataset_sha,
        "model": {"id": config["model_id"], "revision": config["revision"], "dimensions": int(chunk_vectors.shape[1])},
        "runtime": {"python": platform.python_version(), "platform": platform.platform(), "qdrant_mode": "in-memory-local"},
        "model_load_seconds": load_seconds,
        "encode_seconds": encode_seconds,
        "exact_cosine": {"metrics": metrics(evaluation, memory_results, chunks), "latency": latency(memory_latencies)},
        "qdrant": {"metrics": metrics(evaluation, qdrant_results, chunks), "latency": latency(qdrant_latencies)},
        "ranking_equivalent": memory_results == qdrant_results,
        "operational_note": "Local mode measures Qdrant query behavior without server lifecycle or network cost; production-server operations remain a deployment benchmark.",
    }
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
