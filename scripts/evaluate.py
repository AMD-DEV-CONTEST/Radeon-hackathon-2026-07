#!/usr/bin/env python3
"""Task quality evaluation script: use a Model Judge instead of keyword matching (C2 fix).

Design audit fixes:
- C2: accuracy, source hit, and hallucination detection now use ModelRequest semantic judgment
  instead of keyword matching
- R3 node contract: independent evaluation ModelRequest, different authorization and lifecycle

Usage:
    python scripts/evaluate.py \\
        --dataset docs/eval/insurance_qa_50.json \\
        --output docs/eval/quality_report.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

# Add the project root to the path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.config import load_config, configure_agently, make_chat_agent, get_workspace_root
from src.agent.flow import run_flow

logger = logging.getLogger(__name__)


async def model_judge_answer(
    judge_agent: Any,
    question: str,
    answer: str,
    expected_answer: str,
    citations: list[dict],
    evidence_items: list[dict],
) -> dict:
    """Use the model for semantic scoring (R3 node - Model Judge).

    Node Contract (R3):
        - id: R3
        - decision: evaluation judge - semantic accuracy, source hit, hallucination detection
        - input: {question, answer, expected_answer, citations, evidence_items}
        - output: {accuracy_score, accuracy_reason, source_hit, hallucination_sentences, hallucination_rate}
        - consumers: quality_report
        - failure: return default low score, do not block the evaluation flow
    """
    try:
        result = await (
            judge_agent
            .input({
                "question": question,
                "answer": answer,
                "expected_answer": expected_answer,
                "citations": citations,
                "evidence_items": [
                    {"ref_id": e.get("ref_id", ""), "content": e.get("content", "")[:500]}
                    for e in evidence_items
                ],
            })
            .instruct([
                "You are an insurance domain QA evaluation judge. Please perform semantic scoring of the answer.",
                "1. Accuracy: compare the semantic consistency of answer and expected_answer, give a score of 0-100. Do not use keyword matching; understand the semantics.",
                "2. Source hit: check whether the ref_id in citations exists in evidence_items, and whether the cited content actually appears in the corresponding evidence.",
                "3. Hallucination detection: identify factual statements in the answer that are not supported by a citation (i.e. statements whose content cannot be found in the evidence).",
                "4. Multi-turn consistency: if the question includes context dependencies, check whether the answer correctly inherits the context.",
            ])
            .output({
                "accuracy_score": (int, "0-100 semantic accuracy score", "not_null"),
                "accuracy_reason": (str, "scoring reason (explaining why points were deducted)", "not_null"),
                "source_hit": (bool, "whether the cited source is correct (ref_id exists and the cited content matches)", "not_null"),
                "hallucination_sentences": [(str, "statements in the answer without supporting evidence")],
                "hallucination_rate": (float, "ratio of hallucinated statements to all statements in the answer, 0.0-1.0", "not_null"),
                "multi_turn_consistency": (bool, "whether the multi-turn context is correctly maintained (defaults to true when no multi-turn scenario)", "not_null"),
            })
            .async_start()
        )
        return result
    except Exception as e:
        logger.error("Model Judge scoring failed: %s", e)
        return {
            "accuracy_score": 0,
            "accuracy_reason": f"judge_error: {e}",
            "source_hit": False,
            "hallucination_sentences": [],
            "hallucination_rate": 1.0,
            "multi_turn_consistency": False,
        }


async def evaluate_single(
    chat_agent: Any,
    judge_agent: Any,
    item: dict,
    session_registry: Any = None,
    rag_retriever: Any = None,
) -> dict:
    """Evaluate a single question: run the five-step business flow + Model Judge scoring."""
    question = item["question"]
    expected = item.get("expected_answer", "")
    expected_refs = item.get("expected_refs", [])
    session_id = item.get("session_id", f"eval_{hash(question) % 10000}")

    # Run the five-step business flow (TriggerFlow orchestration)
    t0 = time.time()
    state = await run_flow(
        user_input=question,
        session_id=session_id,
        chat_agent=chat_agent,
        session_registry=session_registry,
        rag_retriever=rag_retriever,
    )
    pipeline_time = time.time() - t0

    answer = str(state.get("answer", ""))
    citations = state.get("citations", [])
    sources = state.get("sources", [])

    # Extract evidence_items (passed to the judge)
    pack = state.get("context_pack", {})
    evidence_items = pack.get("items", []) if pack else []

    # C2 fix: use the Model Judge for semantic scoring (instead of keyword matching)
    judge_result = await model_judge_answer(
        judge_agent=judge_agent,
        question=question,
        answer=answer,
        expected_answer=expected,
        citations=citations,
        evidence_items=evidence_items,
    )

    # Host deterministic check: whether expected_refs is in sources
    # This is a deterministic check (set intersection), not semantic judgment; keep it
    source_hit_deterministic = bool(set(expected_refs) & set(sources)) if expected_refs else True

    return {
        "question": question,
        "answer": answer,
        "citations": citations,
        "sources": sources,
        "expected_answer": expected,
        "pipeline_time_s": round(pipeline_time, 2),
        "status": state.get("status", "unknown"),
        "judge": {
            "accuracy_score": judge_result["accuracy_score"],
            "accuracy_reason": judge_result["accuracy_reason"],
            "source_hit": judge_result["source_hit"],
            "hallucination_rate": judge_result["hallucination_rate"],
            "hallucination_sentences": judge_result.get("hallucination_sentences", []),
            "multi_turn_consistency": judge_result.get("multi_turn_consistency", True),
        },
        "deterministic": {
            "source_hit": source_hit_deterministic,
        },
    }


async def evaluate(dataset_path: str, output_path: str) -> None:
    """Run the entire evaluation dataset and output the quality report."""
    with open(dataset_path, encoding="utf-8") as f:
        dataset = json.load(f)

    logger.info("Loading evaluation dataset: %s (%d questions)", dataset_path, len(dataset))

    # Load config and initialize the Agent
    agent_cfg, models_cfg = load_config()
    configure_agently(models_cfg)
    chat_agent = make_chat_agent(models_cfg)
    judge_agent = make_chat_agent(models_cfg)  # independent judge agent (R3 node)

    # Optional: initialize the RAG retriever
    rag_retriever = None
    try:
        from src.config import get_index_dir, make_embedding_agent
        from src.rag.indexer import FaissIndexer
        from src.rag.retriever import RAGRetriever

        index_dir = get_index_dir(agent_cfg)
        if index_dir.exists():
            indexer = FaissIndexer()
            indexer.load(index_dir)
            embedding_agent = make_embedding_agent(models_cfg)
            # Pass the Workspace root path; the retriever reads from records/*.json
            workspace_root = get_workspace_root(agent_cfg)
            rag_retriever = RAGRetriever(embedding_agent, indexer, workspace=workspace_root)
            logger.info("RAG retriever loaded (workspace: %s)", workspace_root)
    except Exception as e:
        logger.warning("RAG retriever initialization failed (RAG will not be used): %s", e)

    # Session registry
    session_registry = None
    try:
        from src.session.registry import SessionRegistry
        session_registry = SessionRegistry(agent_cfg)
    except Exception as e:
        logger.warning("Session registry initialization failed: %s", e)

    # Evaluate question by question
    results = []
    for i, item in enumerate(dataset):
        logger.info("Evaluating %d/%d: %s", i + 1, len(dataset), item["question"][:30])
        try:
            result = await evaluate_single(
                chat_agent=chat_agent,
                judge_agent=judge_agent,
                item=item,
                session_registry=session_registry,
                rag_retriever=rag_retriever,
            )
            results.append(result)
        except Exception as e:
            logger.error("Evaluation of question %d failed: %s", i + 1, e)
            results.append({
                "question": item["question"],
                "answer": "",
                "error": str(e),
                "status": "failed",
                "judge": {
                    "accuracy_score": 0,
                    "accuracy_reason": f"evaluation_error: {e}",
                    "source_hit": False,
                    "hallucination_rate": 1.0,
                    "multi_turn_consistency": False,
                },
            })

    # Summary report
    total = len(results)
    valid = [r for r in results if r.get("judge")]
    report = {
        "total": total,
        "evaluated": len(valid),
        "metrics": {
            "avg_accuracy": sum(r["judge"]["accuracy_score"] for r in valid) / len(valid) if valid else 0,
            "source_hit_rate": sum(1 for r in valid if r["judge"]["source_hit"]) / len(valid) if valid else 0,
            "avg_hallucination_rate": sum(r["judge"]["hallucination_rate"] for r in valid) / len(valid) if valid else 0,
            "multi_turn_consistency": sum(1 for r in valid if r["judge"].get("multi_turn_consistency", True)) / len(valid) if valid else 0,
            "avg_pipeline_time_s": sum(r.get("pipeline_time_s", 0) for r in valid) / len(valid) if valid else 0,
        },
        "details": results,
    }

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    m = report["metrics"]
    print(f"\n{'='*60}")
    print(f"Evaluation report: {output_path}")
    print(f"{'='*60}")
    print(f"Total questions:   {total}")
    print(f"Average accuracy:  {m['avg_accuracy']:.1f}/100")
    print(f"Source hit rate:   {m['source_hit_rate']:.1%}")
    print(f"Hallucination rate:{m['avg_hallucination_rate']:.1%}")
    print(f"Multi-turn consistency: {m['multi_turn_consistency']:.1%}")
    print(f"Average time:      {m['avg_pipeline_time_s']:.2f}s")
    print(f"{'='*60}")


def main():
    parser = argparse.ArgumentParser(description="Insurance RAG Agent task quality evaluation")
    parser.add_argument("--dataset", default="docs/eval/insurance_qa_50.json", help="evaluation dataset path")
    parser.add_argument("--output", default="docs/eval/quality_report.json", help="output report path")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    asyncio.run(evaluate(args.dataset, args.output))


if __name__ == "__main__":
    main()
