#!/usr/bin/env python3
"""Recompute the published five-run Radeon configuration comparison.

This verifies the arithmetic in the preserved JSON. It does not call a model
and does not claim to reproduce the historical inference requests.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from pathlib import Path
from typing import Any


DEFAULT_RESULT = Path(__file__).resolve().parent / "results" / "ab-20260730.json"
ABS_TOLERANCE = 0.02
PUBLISHED_PERCENT_DECIMALS = 1


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def require_number(value: Any, label: str) -> float:
    require(isinstance(value, (int, float)) and not isinstance(value, bool), f"{label} must be numeric")
    number = float(value)
    require(math.isfinite(number), f"{label} must be finite")
    return number


def close(actual: float, expected: float, label: str) -> None:
    require(
        math.isclose(actual, expected, rel_tol=0.0, abs_tol=ABS_TOLERANCE),
        f"{label}: recomputed {actual:.4f}, published {expected:.4f}",
    )


def close_published_percent(actual: float, expected: float, label: str) -> None:
    rounded = round(actual, PUBLISHED_PERCENT_DECIMALS)
    require(
        math.isclose(rounded, expected, rel_tol=0.0, abs_tol=1e-9),
        f"{label}: recomputed {actual:.4f}% ({rounded:.1f}% published), expected {expected:.1f}%",
    )


def percent_change(baseline: float, optimized: float) -> float:
    require(baseline != 0.0, "baseline must be non-zero")
    return 100.0 * (optimized / baseline - 1.0)


def aggregate_arm(payload: dict[str, Any], arm_name: str) -> dict[str, float]:
    runs = payload.get("runs")
    require(isinstance(runs, list), f"{arm_name}.runs must be a list")
    require(len(runs) == 5, f"{arm_name}.runs must contain exactly five measurements")

    metrics: dict[str, float] = {}
    for key in ("wall_ms", "prompt_tps", "decode_tps"):
        values = [require_number(run.get(key), f"{arm_name}.runs[{index}].{key}") for index, run in enumerate(runs)]
        metrics[key] = statistics.fmean(values)

    summary = payload.get("summary")
    require(isinstance(summary, dict), f"{arm_name}.summary must be an object")
    close(metrics["wall_ms"], require_number(summary.get("wall_ms_mean"), f"{arm_name}.summary.wall_ms_mean"), f"{arm_name}.wall_ms_mean")
    close(metrics["prompt_tps"], require_number(summary.get("prompt_tps_mean"), f"{arm_name}.summary.prompt_tps_mean"), f"{arm_name}.prompt_tps_mean")
    close(metrics["decode_tps"], require_number(summary.get("decode_tps_mean"), f"{arm_name}.summary.decode_tps_mean"), f"{arm_name}.decode_tps_mean")
    metrics["ttft_ms"] = require_number(summary.get("ttft_ms_median"), f"{arm_name}.summary.ttft_ms_median")
    return metrics


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("result", nargs="?", type=Path, default=DEFAULT_RESULT)
    args = parser.parse_args()

    try:
        data = json.loads(args.result.read_text(encoding="utf-8"))
        require(data.get("schema_version") == 1, "unexpected schema_version")
        require(data.get("hardware", {}).get("gpu_arch") == "gfx1100", "unexpected GPU architecture")

        model = data.get("model", {})
        require(model.get("id") == "Qwen3-Next-80B-A3B-Instruct", "unexpected model ID")
        require(model.get("file_bytes") == 48410988384, "unexpected model size")
        require(model.get("weight_quantization") == "Q4_K_M", "unexpected weight quantization")
        require(model.get("context_tokens") == 262144, "unexpected context length")

        runtime = data.get("runtime", {})
        require(runtime.get("backend") == "llama.cpp HIP", "unexpected runtime backend")
        require(runtime.get("flash_attention") is True, "Flash Attention was not enabled")
        require(runtime.get("threads") == 32 and runtime.get("batch_threads") == 32, "unexpected thread count")
        require(runtime.get("parallel_slots") == 1, "unexpected parallel slot count")

        method = data.get("method", {})
        require(method.get("warmup_runs") == 1, "unexpected warm-up count")
        require(method.get("measured_runs") == 5, "unexpected measured-run count")
        require(method.get("prompt_tokens_per_run") == 2332, "unexpected prompt shape")
        require(method.get("max_output_tokens") == 64, "unexpected output limit")
        require(method.get("temperature") == 0, "unexpected sampling temperature")

        baseline_payload = data.get("baseline", {})
        require(baseline_payload.get("kv_cache") == "Q8_0/Q8_0", "unexpected baseline KV cache")
        require(baseline_payload.get("gpu_layers") == 45, "unexpected baseline GPU layers")
        baseline = aggregate_arm(baseline_payload, "baseline")
        optimized_payload = data.get("optimized", {})
        require(optimized_payload.get("kv_cache") == "Q4_0/Q4_0", "unexpected optimized KV cache")
        require(optimized_payload.get("gpu_layers") == 47, "unexpected optimized GPU layers")
        optimized = aggregate_arm(optimized_payload, "optimized")

        published_change = optimized_payload.get("relative_change")
        require(isinstance(published_change, dict), "optimized.relative_change must be an object")

        changes = {
            "wall_time_percent": percent_change(baseline["wall_ms"], optimized["wall_ms"]),
            "prompt_tps_percent": percent_change(baseline["prompt_tps"], optimized["prompt_tps"]),
            "decode_tps_percent": percent_change(baseline["decode_tps"], optimized["decode_tps"]),
            "ttft_percent": percent_change(baseline["ttft_ms"], optimized["ttft_ms"]),
        }
        for key, actual in changes.items():
            close_published_percent(
                actual,
                require_number(published_change.get(key), f"optimized.relative_change.{key}"),
                key,
            )

        quality = data.get("quality_canaries", {})
        require(quality.get("openai_tool_call_schema") is True, "tool-call schema canary did not pass")
        require(quality.get("tool_arguments_json") is True, "tool-arguments JSON canary did not pass")
        require(quality.get("tool_result_continuation") is True, "tool-result continuation canary did not pass")
        long_context = quality.get("long_context", {})
        require(long_context.get("prompt_tokens") == 42028, "unexpected long-context canary length")
        require(long_context.get("needle_retrieved") is True, "long-context needle was not retrieved")
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    print("Radeon Qwen3-Next-80B configuration A/B (5 measured runs per arm)")
    print(f"{'Metric':<24}{'Baseline':>14}{'Optimized':>14}{'Change':>12}")
    rows = (
        ("Prefill (tok/s)", "prompt_tps", changes["prompt_tps_percent"]),
        ("Decode (tok/s)", "decode_tps", changes["decode_tps_percent"]),
        ("TTFT median (ms)*", "ttft_ms", changes["ttft_percent"]),
        ("Wall latency (ms)", "wall_ms", changes["wall_time_percent"]),
    )
    for label, key, delta in rows:
        print(f"{label:<24}{baseline[key]:>14.2f}{optimized[key]:>14.2f}{delta:>+11.1f}%")
    print("\nOK: raw wall/prefill/decode means and every published delta are consistent.")
    print("* TTFT has summary medians only; per-run TTFT samples were not archived.")
    print("Boundary: this verifies saved evidence; it does not rerun model inference.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
