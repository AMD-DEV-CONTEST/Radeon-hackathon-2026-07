import sys
import os
import json

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "agent"))
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "toolguard"))

from test_agent import (
    ask_model,
    trigger_normal_tool_call,
    trigger_pattern_plain_text,
    trigger_pattern_schema_leak,
    trigger_pattern_wrong_tool_name,
    classify_response,
)
from guard import guard_response, guard_dropped_stream

SYSTEM_MESSAGES = [
    {"role": "system", "content": "You are a helpful assistant with access to tools."},
    {"role": "user", "content": "What's the weather in Paris?"},
]

SCENARIOS = ["normal", "plain_text", "schema_leak", "dropped_stream", "wrong_tool_name"]
TRIALS_PER_SCENARIO = 10


def run_one(scenario):
    if scenario == "dropped_stream":
        without_success = False
        result = guard_dropped_stream(SYSTEM_MESSAGES, ask_model)
        with_success = result["fixed_by_toolguard"]
        return without_success, with_success

    trigger_fn = {
        "normal": trigger_normal_tool_call,
        "plain_text": trigger_pattern_plain_text,
        "schema_leak": trigger_pattern_schema_leak,
        "wrong_tool_name": trigger_pattern_wrong_tool_name,
    }[scenario]

    raw = trigger_fn()
    without_label, _ = classify_response(raw)
    without_success = without_label == "NORMAL_TOOL_CALL"

    result = guard_response(raw, SYSTEM_MESSAGES, ask_model)
    with_success = result["outcome"] == "NORMAL" or result["fixed_by_toolguard"]

    return without_success, with_success


def run_benchmark():
    results = []
    for scenario in SCENARIOS:
        for i in range(TRIALS_PER_SCENARIO):
            without_success, with_success = run_one(scenario)
            results.append({
                "scenario": scenario,
                "without_toolguard_success": without_success,
                "with_toolguard_success": with_success,
            })
            print(f"  {scenario} trial {i + 1}: without={without_success} with={with_success}")
    return results


def summarize(results):
    total = len(results)
    without_success = sum(r["without_toolguard_success"] for r in results)
    with_success = sum(r["with_toolguard_success"] for r in results)

    without_rate = 100 * without_success / total
    with_rate = 100 * with_success / total

    print("\n=== BENCHMARK SUMMARY ===")
    print("NOTE: this measures recovery rate WHEN one of our 5 known")
    print("scenarios occurs (including 'normal', which needs no fixing).")
    print("It is not a claim about how often these patterns occur in")
    print("general production traffic - we don't have that data.\n")
    print(f"Total trials: {total}")
    print(f"Success rate WITHOUT ToolGuard: {without_rate:.1f}%  ({without_success}/{total})")
    print(f"Success rate WITH ToolGuard:    {with_rate:.1f}%  ({with_success}/{total})")
    print(f"Improvement: +{with_rate - without_rate:.1f} percentage points")

    return {
        "total_trials": total,
        "without_toolguard_success_rate": without_rate,
        "with_toolguard_success_rate": with_rate,
        "improvement_percentage_points": with_rate - without_rate,
    }


if __name__ == "__main__":
    print(f"Running benchmark: {len(SCENARIOS)} scenarios x {TRIALS_PER_SCENARIO} trials each...\n")
    results = run_benchmark()
    summary = summarize(results)

    output_path = os.path.join(os.path.dirname(__file__), "benchmark_results.json")
    with open(output_path, "w") as f:
        json.dump({"summary": summary, "raw_results": results}, f, indent=2)
    print(f"\nSaved to {output_path}")
