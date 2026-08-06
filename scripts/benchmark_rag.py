"""RAG retrieval quality baseline collection."""
from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import load_config, configure_agently, make_embedding_agent, get_index_dir

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s]: %(message)s")


async def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--index-dir", type=str, default=None)
    parser.add_argument("--output", type=str, default="docs/benchmarks/rag_baseline.json")
    args = parser.parse_args()

    agent_cfg, models_cfg = load_config()
    configure_agently(models_cfg)
    embedding_agent = make_embedding_agent(models_cfg)

    index_dir = Path(args.index_dir) if args.index_dir else get_index_dir(agent_cfg)

    from src.rag.indexer import FaissIndexer
    indexer = FaissIndexer()
    indexer.load(index_dir)

    # Use built-in test questions (if there is no annotated dataset)
    test_queries = [
        {"question": "What is the scope of insurance coverage?", "expected_chunk": ""},
        {"question": "What are the exclusion clauses?", "expected_chunk": ""},
        {"question": "What materials are needed for the claims process?", "expected_chunk": ""},
        {"question": "How many days is the waiting period?", "expected_chunk": ""},
        {"question": "How is the premium calculated?", "expected_chunk": ""},
    ]

    # Try to load an external dataset
    dataset_path = PROJECT_ROOT / "docs" / "eval" / "insurance_qa_50.json"
    if dataset_path.exists():
        with open(dataset_path) as f:
            test_queries = json.load(f)

    results = []
    for item in test_queries:
        t0 = time.time()
        result = await embedding_agent.input([item["question"]]).async_start()
        query_vec = np.array(result[0], dtype=np.float32)
        norm = np.linalg.norm(query_vec)
        if norm > 0:
            query_vec = query_vec / norm

        candidates = indexer.search(query_vec, top_k=10)
        latency_ms = (time.time() - t0) * 1000

        results.append({
            "question": item["question"],
            "latency_ms": round(latency_ms, 2),
            "top_candidates": len(candidates),
            "top_score": round(candidates[0]["score"], 4) if candidates else 0,
            "top_chunk": candidates[0].get("chunk_summary", candidates[0].get("chunk_id", ""))[:50] if candidates else "",
        })

    report = {
        "index_type": indexer.index_type,
        "total_chunks": indexer.total_vectors,
        "total_queries": len(results),
        "avg_latency_ms": round(sum(r["latency_ms"] for r in results) / len(results), 2),
        "p95_latency_ms": round(sorted(r["latency_ms"] for r in results)[int(0.95 * len(results))], 2),
        "details": results,
    }

    output_path = PROJECT_ROOT / args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print(f"RAG baseline report saved: {output_path}")
    print(f"  Average latency: {report['avg_latency_ms']}ms")
    print(f"  P95 latency: {report['p95_latency_ms']}ms")
    print(f"  Index vectors: {report['total_chunks']}")

    # Close the httpx client to release the connection pool
    if hasattr(embedding_agent, "close"):
        await embedding_agent.close()


if __name__ == "__main__":
    asyncio.run(main())
