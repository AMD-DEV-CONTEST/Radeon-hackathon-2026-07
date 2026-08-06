"""Benchmark fuzzy intent compilation and local file retrieval on synthetic corpus."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core import LocalOllama, LocalRetriever, LocalVLLM, compile_intent, discover_workspace


CASES = (
    {
        "query": "I remember the presentation about the customer's delayed launch and Q4 risk",
        "expected": "Customer_Delivery_Risk_Q4_Final.pptx",
    },
    {
        "query": "找一下客户延期之后我做的那个 Q4 风险 PPT",
        "expected": "Customer_Delivery_Risk_Q4_Final.pptx",
    },
    {
        "query": "找给客户看的延期风险幻灯片",
        "expected": "Customer_Delivery_Risk_Q4_Final.pptx",
    },
    {
        "query": "find the signed support addendum with availability exclusions",
        "expected": "Support_Addendum_signed.md",
    },
    {
        "query": "签过字的服务可用性例外附录",
        "expected": "Support_Addendum_signed.md",
    },
    {
        "query": "where is the migration runbook with rollback and staging credential rotation",
        "expected": "Migration_Runbook.md",
    },
    {
        "query": "which record says Priya approved the migration sequence",
        "expected": "Steering_Approval_Log.md",
    },
    {
        "query": "find the email where the customer accepted the revised Q4 launch window",
        "expected": "Customer_Change_Request.eml",
    },
)


def run(corpus: Path, output: Path | None = None, intent_llm: object | None = None) -> dict[str, object]:
    retriever = LocalRetriever()
    retriever.index_paths(discover_workspace(corpus))
    rows: list[dict[str, object]] = []
    top1 = 0
    recall3 = 0
    baseline_top1 = 0
    baseline_recall3 = 0
    compiler_modes: set[str] = set()
    compiler_failures: list[str] = []
    def lexical_baseline_names(query: str) -> list[str]:
        scores = retriever.bm25.scores(query) if retriever.bm25 else [0.0] * len(retriever.evidence)
        order = sorted(range(len(scores)), key=lambda index: scores[index], reverse=True)
        names: list[str] = []
        for index in order:
            source = retriever.evidence[index].source
            if source not in names:
                names.append(source)
            if len(names) == 3:
                break
        return names
    for case in CASES:
        plan, compiler_telemetry, compiler_mode = compile_intent(case["query"], intent_llm)
        compiler_modes.add(compiler_mode)
        if compiler_telemetry.get("error"):
            compiler_failures.append(str(compiler_telemetry["error"]))
        matches = retriever.locate_files(case["query"], limit=3, intent_plan=plan)
        names = [item.source for item in matches]
        expected = case["expected"]
        hit_top1 = bool(names and names[0] == expected)
        hit_recall3 = expected in names
        top1 += int(hit_top1)
        recall3 += int(hit_recall3)
        baseline_names = lexical_baseline_names(case["query"])
        baseline_top1 += int(bool(baseline_names and baseline_names[0] == expected))
        baseline_recall3 += int(expected in baseline_names)
        rows.append({
            "query": case["query"],
            "expected": expected,
            "top_results": names,
            "top1": hit_top1,
            "recall3": hit_recall3,
            "intent": plan.intent,
            "topics": list(plan.topics),
            "relations": list(plan.relations),
            "confidence": plan.confidence,
            "compiler": compiler_mode,
            "baseline_top_results": baseline_names,
            "baseline_top1": bool(baseline_names and baseline_names[0] == expected),
        })
    result = {
        "corpus": str(corpus.resolve()),
        "cases": len(CASES),
        "top1_accuracy": round(top1 / len(CASES), 3),
        "recall_at_3": round(recall3 / len(CASES), 3),
        "lexical_baseline_top1_accuracy": round(baseline_top1 / len(CASES), 3),
        "lexical_baseline_recall_at_3": round(baseline_recall3 / len(CASES), 3),
        "compiler_modes": sorted(compiler_modes),
        "compiler_failures": list(dict.fromkeys(compiler_failures)),
        "failures": [row for row in rows if not row["top1"]],
        "rows": rows,
    }
    if output:
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, default=Path(__file__).parent.parent / "championship_corpus")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--router-runtime", choices=("vllm", "ollama"), default="vllm")
    parser.add_argument("--router-endpoint", default="")
    parser.add_argument("--router-model", default="")
    args = parser.parse_args()
    intent_llm = None
    if args.router_endpoint and args.router_model:
        intent_llm = (
            LocalOllama(args.router_endpoint, args.router_model)
            if args.router_runtime == "ollama"
            else LocalVLLM(args.router_endpoint, args.router_model)
        )
    result = run(args.corpus, args.output, intent_llm)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not result["failures"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
