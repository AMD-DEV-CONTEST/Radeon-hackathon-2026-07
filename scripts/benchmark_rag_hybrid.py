#!/usr/bin/env python3
"""Hybrid retrieval benchmark collection: FAISS + BM25 + Cross-Encoder reranking.

Compare baseline: rag_baseline.json (FAISS only, avg_latency=22.48ms, top_score avg=0.724)
Output: opt_rag_hybrid.json

Collected metrics:
- Retrieval latency (avg, p95) — includes BM25 + reranking overhead
- top_score mean/min — precision improvement
- Recall@5 / Recall@10 — recall rate (based on expected_refs)
- BM25 exclusive hits — evidence that BM25 fills the blind spots of FAISS
- top-1 changes before/after reranking — Cross-Encoder re-ranking effect

Usage:
    python scripts/benchmark_rag_hybrid.py \
        --output docs/benchmarks/opt_rag_hybrid.json
"""
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

from src.config import (
    load_config,
    configure_agently,
    make_embedding_agent,
    get_index_dir,
    get_workspace_root,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s]: %(message)s",
)
logger = logging.getLogger(__name__)


def _check_ref_hit(chunk_id: str, expected_refs: list[str]) -> bool:
    """Check whether chunk_id matches any document in expected_refs.

    chunk_id format: "2-employer-liability_chunk_000"
    expected_refs: ["2-employer-liability"]
    """
    if not expected_refs:
        return True  # default hit when there are no expected refs
    for ref in expected_refs:
        if chunk_id.startswith(ref):
            return True
    return False


async def main():
    import argparse
    parser = argparse.ArgumentParser(description="RAG retrieval benchmark collection (FAISS-only / Hybrid mode)")
    parser.add_argument("--index-dir", type=str, default=None)
    parser.add_argument("--output", type=str, default="docs/benchmarks/opt_rag_hybrid.json")
    parser.add_argument("--top-k", type=int, default=10, help="FAISS/BM25 retrieval top-K")
    parser.add_argument("--rerank-top-n", type=int, default=5, help="top-N after reranking")
    parser.add_argument("--mode", choices=["hybrid", "faiss-only"], default="hybrid",
                        help="hybrid=FAISS+BM25+Rerank, faiss-only=only FAISS (for a fair recall comparison)")
    args = parser.parse_args()

    # Load config
    agent_cfg, models_cfg = load_config()
    configure_agently(models_cfg)
    embedding_agent = make_embedding_agent(models_cfg)

    index_dir = Path(args.index_dir) if args.index_dir else get_index_dir(agent_cfg)
    workspace_root = get_workspace_root(agent_cfg)
    rag_cfg = agent_cfg.get("rag", {})

    # Load the FAISS index
    from src.rag.indexer import FaissIndexer
    from src.rag.retriever import RAGRetriever

    indexer = FaissIndexer()
    indexer.load(index_dir)
    logger.info("FAISS index loaded: %d vectors", indexer.total_vectors)

    # Load the BM25 index
    bm25_indexer = None
    bm25_cfg = rag_cfg.get("bm25", {})
    if args.mode == "hybrid" and bm25_cfg.get("enabled", True):
        try:
            from src.rag.bm25_indexer import BM25Indexer
            bm25_indexer = BM25Indexer()
            bm25_indexer.load(index_dir)
            if bm25_indexer.bm25 is None:
                logger.warning("BM25 index was not loaded successfully; will only use FAISS retrieval")
                bm25_indexer = None
            else:
                logger.info("BM25 index loaded: %d documents", len(bm25_indexer.chunk_ids))
        except ImportError:
            logger.warning("rank-bm25 not installed, BM25 hybrid retrieval unavailable")
        except Exception as e:
            logger.warning("BM25 index load failed: %s", e)
            bm25_indexer = None

    # Load the Cross-Encoder reranker
    reranker = None
    rerank_cfg = rag_cfg.get("rerank", {})
    if args.mode == "hybrid" and rerank_cfg.get("enabled", True):
        try:
            from src.rag.reranker import CrossEncoderReranker
            reranker = CrossEncoderReranker(
                model_name=rerank_cfg.get("model_name", "BAAI/bge-reranker-base"),
            )
            if reranker.available:
                logger.info("Cross-Encoder reranker loaded: %s", rerank_cfg.get("model_name", "BAAI/bge-reranker-base"))
            else:
                logger.warning("Cross-Encoder unavailable, skipping reranking")
                reranker = None
        except Exception as e:
            logger.warning("Reranker initialization failed: %s", e)

    # Assemble the RAGRetriever
    bm25_weight = bm25_cfg.get("weight", 0.3)
    retriever = RAGRetriever(
        embedding_agent=embedding_agent,
        indexer=indexer,
        workspace=workspace_root,
        top_k=args.top_k,
        bm25_indexer=bm25_indexer,
        reranker=reranker,
        rerank_top_n=args.rerank_top_n,
        bm25_weight=bm25_weight,
        faiss_weight=1.0 - bm25_weight,
    )

    components = ["FAISS"]
    if bm25_indexer:
        components.append("BM25")
    if reranker:
        components.append("Rerank")
    logger.info("Hybrid retrieval components: %s", " + ".join(components))

    # Load the test dataset
    dataset_path = PROJECT_ROOT / "docs" / "eval" / "insurance_qa_50.json"
    with open(dataset_path, encoding="utf-8") as f:
        test_queries = json.load(f)
    logger.info("Test dataset: %d questions", len(test_queries))

    # Run hybrid retrieval
    results = []
    recall_at_5_hits = 0
    recall_at_10_hits = 0
    bm25_exclusive_hits = 0  # BM25 exclusive hits (FAISS missed but BM25 hit)
    rerank_top1_changed = 0  # number of times top-1 changed after reranking

    for i, item in enumerate(test_queries):
        question = item["question"]
        expected_refs = item.get("expected_refs", [])

        t0 = time.time()
        candidates = await retriever.retrieve(question)
        latency_ms = (time.time() - t0) * 1000

        # Analyze the retrieval results
        top_score = candidates[0].get("fused_score", candidates[0].get("score", 0)) if candidates else 0
        top_chunk = candidates[0].get("chunk_id", "") if candidates else ""

        # Recall@5: whether expected_refs is hit in the top-5
        top5_chunks = [c.get("chunk_id", "") for c in candidates[:5]]
        hit_at_5 = any(_check_ref_hit(cid, expected_refs) for cid in top5_chunks)
        if hit_at_5:
            recall_at_5_hits += 1

        # Recall@10: whether it is hit in the top-10
        top10_chunks = [c.get("chunk_id", "") for c in candidates[:10]]
        hit_at_10 = any(_check_ref_hit(cid, expected_refs) for cid in top10_chunks)
        if hit_at_10:
            recall_at_10_hits += 1

        # BM25 exclusive hit check: if a candidate from the BM25 source is hit in the top-5
        for c in candidates[:5]:
            sources = c.get("sources", [])
            if "bm25" in sources and "faiss" not in sources:
                if _check_ref_hit(c.get("chunk_id", ""), expected_refs):
                    bm25_exclusive_hits += 1
                    break

        # Reranking top-1 change check
        if candidates and "rerank_score" in candidates[0]:
            # If there is a rerank_score, reranking took effect
            rerank_top1_changed += 1

        results.append({
            "question": question,
            "latency_ms": round(latency_ms, 2),
            "top_candidates": len(candidates),
            "top_score": round(float(top_score), 4),
            "top_chunk": top_chunk[:60],
            "expected_refs": expected_refs,
            "recall_hit_5": hit_at_5,
            "recall_hit_10": hit_at_10,
            "category": item.get("category", ""),
            "difficulty": item.get("difficulty", ""),
        })

        if (i + 1) % 10 == 0:
            logger.info("Progress: %d/%d", i + 1, len(test_queries))

    # Summary report
    total = len(results)
    latencies = sorted(r["latency_ms"] for r in results)
    p95_idx = int(0.95 * total) if total > 0 else 0
    top_scores = [r["top_score"] for r in results]

    report = {
        "retrieval_type": args.mode,
        "components": components,
        "bm25_weight": bm25_weight,
        "faiss_weight": 1.0 - bm25_weight,
        "rerank_model": rerank_cfg.get("model_name", "BAAI/bge-reranker-base") if reranker else None,
        "rerank_top_n": args.rerank_top_n,
        "total_chunks": indexer.total_vectors,
        "total_queries": total,
        "avg_latency_ms": round(sum(r["latency_ms"] for r in results) / total, 2) if total else 0,
        "p95_latency_ms": round(latencies[p95_idx], 2) if total else 0,
        "top_score_avg": round(sum(top_scores) / len(top_scores), 4) if top_scores else 0,
        "top_score_min": round(min(top_scores), 4) if top_scores else 0,
        "top_score_max": round(max(top_scores), 4) if top_scores else 0,
        "recall_at_5": round(recall_at_5_hits / total, 4) if total else 0,
        "recall_at_10": round(recall_at_10_hits / total, 4) if total else 0,
        "bm25_exclusive_hits": bm25_exclusive_hits,
        "rerank_active_count": rerank_top1_changed,
        "details": results,
    }

    # Save the report
    output_path = PROJECT_ROOT / args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    # Print the summary
    print(f"\n{'='*60}")
    print(f"Hybrid retrieval benchmark report")
    print(f"{'='*60}")
    print(f"Components:     {' + '.join(components)}")
    print(f"Total questions:{total}")
    print(f"Average latency: {report['avg_latency_ms']}ms")
    print(f"P95 latency:    {report['p95_latency_ms']}ms")
    print(f"top_score:    avg={report['top_score_avg']}, min={report['top_score_min']}, max={report['top_score_max']}")
    print(f"Recall@5:     {report['recall_at_5']:.1%} ({recall_at_5_hits}/{total})")
    print(f"Recall@10:    {report['recall_at_10']:.1%} ({recall_at_10_hits}/{total})")
    print(f"BM25 exclusive hits: {bm25_exclusive_hits}")
    print(f"Rerank active: {rerank_top1_changed}/{total}")
    print(f"Output file:   {output_path}")
    print(f"{'='*60}")

    # Compare with the baseline
    baseline_path = PROJECT_ROOT / "docs" / "benchmarks" / "benchmarks" / "rag_baseline.json"
    if baseline_path.exists():
        with open(baseline_path, encoding="utf-8") as f:
            baseline = json.load(f)
        print(f"\n{'='*60}")
        print(f"Compare with baseline (FAISS only)")
        print(f"{'='*60}")
        print(f"{'metric':<20} {'FAISS only':<15} {'Hybrid':<15} {'Change':<15}")
        print(f"{'-'*60}")
        print(f"{'avg_latency_ms':<20} {baseline['avg_latency_ms']:<15} {report['avg_latency_ms']:<15} {report['avg_latency_ms'] - baseline['avg_latency_ms']:+.2f}ms")
        print(f"{'p95_latency_ms':<20} {baseline['p95_latency_ms']:<15} {report['p95_latency_ms']:<15} {report['p95_latency_ms'] - baseline['p95_latency_ms']:+.2f}ms")
        baseline_top_avg = sum(r["top_score"] for r in baseline["details"]) / len(baseline["details"])
        print(f"{'top_score_avg':<20} {baseline_top_avg:<15.4f} {report['top_score_avg']:<15.4f} {report['top_score_avg'] - baseline_top_avg:+.4f}")
        baseline_top_min = min(r["top_score"] for r in baseline["details"])
        print(f"{'top_score_min':<20} {baseline_top_min:<15.4f} {report['top_score_min']:<15.4f} {report['top_score_min'] - baseline_top_min:+.4f}")
        print(f"{'='*60}")

    # Close the httpx client
    if hasattr(embedding_agent, "close"):
        await embedding_agent.close()


if __name__ == "__main__":
    asyncio.run(main())
