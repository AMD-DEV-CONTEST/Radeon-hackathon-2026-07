"""Evaluate the frozen synthetic fuzzy-query holdout end to end."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from core import (
    LocalCrossEncoderReranker,
    LocalEmbeddingClient,
    LocalOllama,
    LocalRetriever,
    LocalVLLM,
    assess_file_matches,
    compile_intent,
    discover_workspace,
)


TOPIC_MAP = {
    "os": "operating_system",
    "database": "database",
    "computer_org": "computer_organization",
    "network": "computer_network",
    "digital_logic": "digital_logic",
}

ROLE_EQUIVALENTS = {
    "experiment": {"experiment", "experiment_report"},
    "experiment_report": {"experiment_report"},
    "course_design_report": {"course_design_report"},
}


def _ratio(value: int, total: int) -> float:
    return round(value / max(total, 1), 3)


def run(
    root: Path,
    llm: object | None = None,
    embedder: LocalEmbeddingClient | None = None,
    reranker: LocalCrossEncoderReranker | None = None,
    require_live_stack: bool = False,
    router_concurrency: int = 1,
) -> dict[str, Any]:
    query_file = root / "queries.jsonl"
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    actual_hash = hashlib.sha256(query_file.read_bytes()).hexdigest()
    if actual_hash != manifest["query_manifest_sha256"]:
        raise ValueError("Holdout query manifest hash changed; rebuild intentionally before evaluating")
    rows = [json.loads(line) for line in query_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    retriever = LocalRetriever(embedder=embedder, reranker=reranker)
    retriever.index_paths(discover_workspace(root / "corpus"))
    results: list[dict[str, Any]] = []
    def compile_row(row: dict[str, Any]) -> tuple[Any, dict[str, Any], str]:
        return compile_intent(str(row["query"]), llm)

    if llm is not None and router_concurrency > 1:
        with ThreadPoolExecutor(max_workers=router_concurrency) as pool:
            compiled_rows = list(pool.map(compile_row, rows))
    else:
        compiled_rows = [compile_row(row) for row in rows]
    for row, compiled_row in zip(rows, compiled_rows):
        query = str(row["query"])
        plan, telemetry, compiler = compiled_row
        expected_topic = TOPIC_MAP.get(str(row.get("expected_topic", "")), "")
        expected_role = str(row.get("expected_role", ""))
        accepted_roles = ROLE_EQUIVALENTS.get(expected_role, {expected_role} if expected_role else set())
        contract_checks = {
            "mode": not row.get("expected_mode") or plan.request_mode == row["expected_mode"],
            "topic": not expected_topic or expected_topic in plan.topics,
            "role": not expected_role or bool(accepted_roles.intersection(plan.required_roles)),
            "clarification": plan.clarification_needed == bool(row.get("should_clarify", False)),
        }
        names: list[str] = []
        decision_status = "clarification_needed" if plan.clarification_needed else ""
        if not plan.clarification_needed:
            matches = retriever.locate_files(query, limit=32, intent_plan=plan)
            names = [match.source for match in matches]
            decision_status = assess_file_matches(query, plan, matches).status
        expected = [str(item) for item in row.get("expected_files", [])]
        expected_set = set(expected)
        top1 = bool(expected and names and names[0] in expected_set)
        full_coverage = bool(expected) and expected_set.issubset(names)
        if row.get("should_clarify"):
            retrieval_passed = plan.clarification_needed
        elif row.get("expect_no_match"):
            retrieval_passed = decision_status == "no_match" and not names
        elif row.get("expect_multiple"):
            retrieval_passed = full_coverage and decision_status == "multiple_matches"
        else:
            retrieval_passed = top1 and (
                decision_status == "confident"
                or (plan.request_mode == "inventory" and decision_status == "multiple_matches")
            )
        safe_selection = decision_status != "confident" or top1
        results.append({
            "id": row["id"],
            "category": row["category"],
            "query": query,
            "expected": expected,
            "actual": names,
            "decision": decision_status,
            "compiler": compiler,
            "compiler_error": telemetry.get("error"),
            "contract_checks": contract_checks,
            "contract_passed": all(contract_checks.values()),
            "retrieval_passed": retrieval_passed,
            "safe_selection": safe_selection,
            "passed": all(contract_checks.values()) and retrieval_passed and safe_selection,
            "top1": top1,
            "full_coverage": full_coverage,
        })
    category_metrics: dict[str, dict[str, Any]] = {}
    for category in sorted({str(row["category"]) for row in results}):
        category_rows = [row for row in results if row["category"] == category]
        category_metrics[category] = {
            "cases": len(category_rows),
            "pass_rate": _ratio(sum(row["passed"] for row in category_rows), len(category_rows)),
        }
    single_rows = [row for row in results if row["expected"] and len(row["expected"]) == 1]
    multi_rows = [row for row in results if len(row["expected"]) > 1]
    no_match_rows = [row for row, source in zip(results, rows) if source.get("expect_no_match")]
    clarification_rows = [row for row, source in zip(results, rows) if source.get("should_clarify")]
    metrics = {
        "cases": len(results),
        "overall_pass_rate": _ratio(sum(row["passed"] for row in results), len(results)),
        "intent_contract_accuracy": _ratio(sum(row["contract_passed"] for row in results), len(results)),
        "single_target_top1_accuracy": _ratio(sum(row["top1"] for row in single_rows), len(single_rows)),
        "multi_target_full_coverage_accuracy": _ratio(sum(row["full_coverage"] for row in multi_rows), len(multi_rows)),
        "no_match_accuracy": _ratio(sum(row["retrieval_passed"] for row in no_match_rows), len(no_match_rows)),
        "clarification_accuracy": _ratio(sum(row["retrieval_passed"] for row in clarification_rows), len(clarification_rows)),
        "safe_selection_rate": _ratio(sum(row["safe_selection"] for row in results), len(results)),
        "unsafe_wrong_auto_selections": sum(not row["safe_selection"] for row in results),
    }
    compiler_modes = sorted({row["compiler"] for row in results})
    live_stack_checks = {
        "router": llm is not None and "deterministic" not in compiler_modes,
        "embedding": embedder is not None and retriever.embedding_matrix is not None,
        "reranker": reranker is not None and bool(retriever.reranker_model) and not retriever.reranker_error,
    }
    return {
        "schema": 1,
        "query_manifest_sha256": actual_hash,
        "synthetic_only": True,
        "runtime": {
            "embedding_model": retriever.embedding_model or None,
            "embedding_active": retriever.embedding_matrix is not None,
            "reranker_model": retriever.reranker_model or None,
            "reranker_error": getattr(reranker, "error", "") if reranker else "",
            "compiler_modes": compiler_modes,
            "live_stack_required": require_live_stack,
            "live_stack_checks": live_stack_checks,
            "live_stack_passed": all(live_stack_checks.values()) if require_live_stack else None,
            "router_concurrency": router_concurrency,
        },
        "metrics": metrics,
        "category_metrics": category_metrics,
        "failure_ids": [row["id"] for row in results if not row["passed"]],
        "failures": [row for row in results if not row["passed"]],
        "rows": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).parent.parent / "evaluation" / "fuzzy_holdout_v1")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--router-runtime", choices=("vllm", "ollama"), default="vllm")
    parser.add_argument("--router-endpoint", default="")
    parser.add_argument("--router-model", default="")
    parser.add_argument("--embedding-runtime", choices=("vllm", "ollama"), default="vllm")
    parser.add_argument("--embedding-endpoint", default="")
    parser.add_argument("--embedding-model", default="")
    parser.add_argument("--reranker-model", default="")
    parser.add_argument("--reranker-device", default="")
    parser.add_argument("--require-live-stack", action="store_true")
    parser.add_argument("--router-concurrency", type=int, default=1)
    args = parser.parse_args()
    llm = None
    if args.router_endpoint and args.router_model:
        llm = LocalOllama(args.router_endpoint, args.router_model) if args.router_runtime == "ollama" else LocalVLLM(args.router_endpoint, args.router_model)
    embedder = None
    if args.embedding_endpoint and args.embedding_model:
        runtime = "Ollama ROCm" if args.embedding_runtime == "ollama" else "vLLM ROCm"
        embedder = LocalEmbeddingClient(runtime, args.embedding_endpoint, args.embedding_model)
    reranker = LocalCrossEncoderReranker(args.reranker_model, device=args.reranker_device or None) if args.reranker_model else None
    result = run(
        args.root,
        llm,
        embedder=embedder,
        reranker=reranker,
        require_live_stack=args.require_live_stack,
        router_concurrency=max(1, args.router_concurrency),
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["metrics"], ensure_ascii=False, indent=2))
    live_failed = args.require_live_stack and not result["runtime"]["live_stack_passed"]
    return 0 if not result["failure_ids"] and not live_failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
