import sys
import os
import time
import json

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "agent"))
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "toolguard"))

from test_agent import (
    ask_model,
    trigger_pattern_plain_text,
    trigger_pattern_schema_leak,
)
from guard import guard_response, guard_dropped_stream

SYSTEM_MESSAGES = [
    {"role": "system", "content": "You are a helpful assistant with access to tools."},
    {"role": "user", "content": "What's the weather in Paris?"},
]

NUM_TRIALS_PER_PATTERN = 3


def time_pattern(label, trigger_fn):
    times = []
    for i in range(NUM_TRIALS_PER_PATTERN):
        raw = trigger_fn()
        start = time.time()
        result = guard_response(raw, SYSTEM_MESSAGES, ask_model)
        elapsed = time.time() - start
        times.append(elapsed)
        print(f"  {label} trial {i + 1}: repair took {elapsed:.2f}s, fixed={result['fixed_by_toolguard']}")
    return times


def time_dropped_stream():
    times = []
    for i in range(NUM_TRIALS_PER_PATTERN):
        start = time.time()
        result = guard_dropped_stream(SYSTEM_MESSAGES, ask_model)
        elapsed = time.time() - start
        times.append(elapsed)
        print(f"  dropped_stream trial {i + 1}: repair took {elapsed:.2f}s, fixed={result['fixed_by_toolguard']}")
    return times


if __name__ == "__main__":
    print("Measuring real repair latency (time for the fix step alone)...\n")

    all_times = []
    all_times += time_pattern("plain_text", trigger_pattern_plain_text)
    all_times += time_pattern("schema_leak", trigger_pattern_schema_leak)
    all_times += time_dropped_stream()

    avg = sum(all_times) / len(all_times)

    print(f"\n=== SUMMARY ===")
    print(f"Average repair latency across {len(all_times)} trials: {avg:.2f} seconds")

    with open(os.path.join(os.path.dirname(__file__), "repair_latency_results.json"), "w") as f:
        json.dump({"avg_repair_latency_sec": round(avg, 2), "raw_times_sec": [round(t, 2) for t in all_times]}, f, indent=2)
    print("Saved to benchmarks/repair_latency_results.json")
