"""Evaluate a local intent model without persisting private query text."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics
import sys
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from core import INTENT_COMPILER_PROMPT, LocalVLLM, _validate_compiled_intent, compile_intent


def _expected_intent(value: str) -> str:
    if value in {"file_locator", "artifact_summary"}:
        return "locate_artifact"
    if value == "sensitive_record_scan":
        return value
    return "evidence_question"


def run(queries: Path, endpoint: str, model: str, compiled: bool = False) -> dict[str, Any]:
    rows = [json.loads(line) for line in queries.read_text(encoding="utf-8").splitlines() if line]
    llm = LocalVLLM(endpoint, model)
    results: list[dict[str, Any]] = []
    latencies: list[float] = []
    throughputs: list[float] = []
    for position, row in enumerate(rows, start=1):
        expected_intent = _expected_intent(str(row["intent"]))
        expected_clarification = bool(row.get("should_clarify", False))
        try:
            if compiled:
                plan, telemetry, compiler = compile_intent(str(row["query"]), llm)
                actual_intent = plan.intent
                actual_clarification = plan.clarification_needed
                schema_valid = True
                error = str(telemetry.get("error") or "")
                latency = float(telemetry.get("latency_seconds", 0))
                throughput = float(telemetry.get("tokens_per_second", 0))
            else:
                value, telemetry = llm.complete_json(
                    INTENT_COMPILER_PROMPT,
                    f"User recollection:\n<query>{row['query']}</query>\nCompile the local search plan.",
                )
                value = _validate_compiled_intent(value)
                actual_intent = str(value["intent"])
                actual_clarification = bool(value["clarification_needed"])
                schema_valid = True
                error = ""
                latency = float(telemetry.get("latency_seconds", 0))
                throughput = float(telemetry.get("tokens_per_second", 0))
            latencies.append(latency)
            throughputs.append(throughput)
        except Exception as exc:
            actual_intent = "invalid"
            actual_clarification = False
            schema_valid = False
            error = f"{type(exc).__name__}: {exc}"
        intent_correct = actual_intent == expected_intent
        clarification_correct = actual_clarification == expected_clarification
        results.append({
            "id": row["id"],
            "expected_intent": expected_intent,
            "actual_intent": actual_intent,
            "expected_clarification": expected_clarification,
            "actual_clarification": actual_clarification,
            "schema_valid": schema_valid,
            "intent_correct": intent_correct,
            "clarification_correct": clarification_correct,
            "joint_correct": schema_valid and intent_correct and clarification_correct,
            "error": error,
        })
        print(
            f"case={position}/{len(rows)} id={row['id']} "
            f"schema={schema_valid} intent={intent_correct} clarification={clarification_correct}",
            flush=True,
        )
    count = len(results)
    return {
        "model": model,
        "mode": "compiled" if compiled else "raw",
        "cases": count,
        "metrics": {
            "schema_accuracy": round(sum(item["schema_valid"] for item in results) / max(count, 1), 3),
            "intent_accuracy": round(sum(item["intent_correct"] for item in results) / max(count, 1), 3),
            "clarification_accuracy": round(sum(item["clarification_correct"] for item in results) / max(count, 1), 3),
            "joint_accuracy": round(sum(item["joint_correct"] for item in results) / max(count, 1), 3),
            "median_latency_seconds": round(statistics.median(latencies), 3) if latencies else 0.0,
            "median_tokens_per_second": round(statistics.median(throughputs), 2) if throughputs else 0.0,
        },
        "failures": [item for item in results if not item["joint_correct"]],
        "rows": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--queries", type=Path, required=True)
    parser.add_argument("--endpoint", default="http://127.0.0.1:8000/v1")
    parser.add_argument("--model", required=True)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--compiled", action="store_true")
    args = parser.parse_args()
    result = run(args.queries, args.endpoint, args.model, compiled=args.compiled)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["metrics"], ensure_ascii=False, indent=2))
    return 0 if not result["failures"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
